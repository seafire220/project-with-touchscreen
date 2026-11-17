"""The device: ties settings, characters, memory, providers, sound, the button and the stage together."""
import asyncio
import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import time

from . import providers
from .audio import Detector, Microphone, Speaker, tone
from .characters import Characters, split_persona
from .conversation import Conversation
from .memory import Memory
from . import screen
from .network import NetworkError, WiFi
from .providers import ProviderError
from .stage_link import StageLink
from .store import Store, redact, write_atomic

log = logging.getLogger("companion")

NOTES_EVERY = 6          # update the memory notes after this many turns


class Device:
    def __init__(self, data_dir, stage_socket=None, speaker=None, microphone=None, stage=None,
                 provider_factory=None, wifi=None, restart=None, run=None):
        self.data_dir = data_dir
        self.store = Store(os.path.join(data_dir, "config"))
        self.characters = Characters(os.path.join(data_dir, "characters"))
        self.memory_dir = os.path.join(data_dir, "memory")
        self.stt_model_dir = os.path.join(data_dir, "models", "stt")
        self.current_puppet = os.path.join(data_dir, "current.inp")
        self.speaker = speaker or Speaker()
        self.microphone = microphone
        self.stage = stage or StageLink(stage_socket or "/run/companion/stage.sock", self._stage_event)
        self.provider_factory = provider_factory
        self.subscribers = set()
        self.state = "idle"
        self.listening = False
        self.recording = None
        self.conversation = None
        self.timers = {}
        self.started = time.time()
        self.log = []
        self.wifi = wifi
        self.card = os.path.join(data_dir, "card.inp")
        # How to restart the service after a reset (systemd starts it again), and
        # how to run system commands; both replaceable in tests.
        self.restart = restart or (lambda: os._exit(0))
        self.run = run or _run_command
        self.stage_seen = time.time()

    # ----- events for the console
    def emit(self, kind, data=None):
        event = {"t": round(time.time(), 2), "kind": kind}
        event.update(data or {})
        if "message" in event:
            event["message"] = redact(event["message"], self.store)
        self.log = (self.log + [event])[-200:]
        for queue in list(self.subscribers):
            if queue.qsize() < 500:
                queue.put_nowait(event)

    def _stage_event(self, event):
        self.stage_seen = time.time()
        if event.get("event") in ("error", "fatal"):
            self.emit("stage_error", {"message": event.get("message", "")})

    async def stage_watch(self, patience=25.0):
        """If the character cannot be shown (the stage keeps failing to start), show a card instead.

        A puppet the stage cannot load makes it exit before it can report
        why, so the sign is that it never connects.
        """
        while True:
            await asyncio.sleep(5.0)
            if getattr(self.stage, "writer", None) is not None:
                self.stage_seen = time.time()
                continue
            showing = os.path.realpath(self.current_puppet)
            if time.time() - self.stage_seen > patience and showing != os.path.realpath(self.card):
                self.emit("error", {"message": "the character could not be shown; showing a message instead"})
                self.show_card(screen.message_card(
                    "Character problem", "This character could not be shown. Choose another one, or add it "
                    "again, on the settings page."))
                self.stage_seen = time.time()

    # ----- time zone, resets
    def timezone(self):
        try:
            return os.path.relpath(os.path.realpath("/etc/localtime"), "/usr/share/zoneinfo")
        except ValueError:
            return ""

    async def set_timezone(self, zone):
        if not re.fullmatch(r"[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+){0,2}", zone or "") or \
                not os.path.isfile(os.path.join("/usr/share/zoneinfo", zone)):
            raise ValueError("unknown time zone: %s" % zone)
        await self.run("timedatectl", "set-timezone", zone)
        self.emit("device", {"timezone": zone})

    async def forget_wifi(self):
        """Forget every saved Wi-Fi network (not the setup hotspot)."""
        if self.wifi is None:
            return
        try:
            out = await self.run("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show")
        except Exception:
            return
        from .network import HOTSPOT_NAME, split_terse
        for line in out.splitlines():
            name, kind = (split_terse(line) + ["", ""])[:2]
            if kind.endswith("wireless") and name != HOTSPOT_NAME:
                try:
                    await self.run("nmcli", "connection", "delete", name)
                except Exception:
                    pass

    async def setup_reset(self):
        """Long press of the button: forget the settings-page password and Wi-Fi, keep characters and keys."""
        self.interrupt()
        if os.path.exists(self.store.password_path):
            os.remove(self.store.password_path)
        await self.forget_wifi()
        self.emit("device", {"did": "setup reset"})
        self.show_card(screen.message_card("Setup reset", "The settings-page password and Wi-Fi were "
                                           "forgotten. Starting again…"))
        await asyncio.sleep(2.0)
        self.restart()

    async def factory_reset(self):
        """Remove everything the owner added: characters, memories, keys, settings, timers, Wi-Fi."""
        self.interrupt()
        await self.forget_wifi()
        keep = {"models"}
        for name in os.listdir(self.data_dir):
            if name in keep:
                continue
            path = os.path.join(self.data_dir, name)
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        self.emit("device", {"did": "factory reset"})
        self.show_card(screen.message_card("Reset", "Everything was removed. Starting again…"))
        await asyncio.sleep(2.0)
        self.restart()

    # ----- providers, rebuilt from the settings for each conversation
    def build(self, which, **extra):
        if self.provider_factory:
            return self.provider_factory(which, self)
        settings = self.store.settings()
        if which == "llm":
            return providers.build_llm(settings, self.store)
        if which == "stt":
            # Kept between uses: the on-device model takes about 200 MB and
            # seconds to load, so it is loaded once and reused until the
            # speech settings or keys change.
            key = (json.dumps(settings["stt"], sort_keys=True), json.dumps(self.store.secret_status(), sort_keys=True))
            if getattr(self, "_stt_key", None) != key:
                self._stt = None
                self._stt = providers.build_stt(settings, self.store, self.stt_model_dir)
                self._stt_key = key
            return self._stt
        if which == "tts":
            return providers.build_tts(settings, self.store, **extra)
        raise ValueError(which)

    # ----- characters
    def active_id(self):
        cid = self.store.settings().get("active_character", "")
        ids = self.characters.ids()
        if cid in ids:
            return cid
        return ids[0] if ids else ""

    def memory(self, cid=None):
        cid = cid or self.active_id()
        return Memory(os.path.join(self.memory_dir, cid or "_none"))

    def activate(self, cid):
        if cid not in self.characters.ids():
            raise KeyError(cid)
        self.interrupt()
        self.store.update_settings({"active_character": cid})
        self._link_puppet(cid)
        self.conversation = None
        self.stage.send({"quit": True})      # the service manager restarts the stage with the new puppet
        self.emit("character", {"id": cid})

    def _link_puppet(self, cid):
        target = self.characters.file(cid, "visual/puppet.inp")
        if not os.path.exists(target):
            target = self.characters.file(cid, "visual/puppet.inx")
        self._point_stage_at(target)

    def show_card(self, png):
        """Show a message on the screen instead of the character."""
        write_atomic(self.card, screen.card_puppet(png))
        self._point_stage_at(self.card)
        self.stage.send({"quit": True})

    def show_character(self):
        cid = self.active_id()
        if cid:
            self._link_puppet(cid)
            self.stage.send({"quit": True})
        return cid

    def _point_stage_at(self, target):
        tmp = self.current_puppet + ".new"
        if os.path.lexists(tmp):
            os.remove(tmp)
        os.symlink(target, tmp)
        os.replace(tmp, self.current_puppet)

    def make_conversation(self):
        cid = self.active_id()
        if not cid:
            raise ProviderError("no character is installed yet")
        voice = self.characters.device_settings(cid).get("voice") or None
        settings = self.store.settings()
        self.speaker.volume = float(settings.get("volume", 0.8))
        return Conversation(
            llm=self.build("llm"), tts=self.build("tts", voice=voice),
            speaker=self.speaker, stage=self.stage, memory=self.memory(cid),
            persona=self.characters.persona(cid),
            history_turns=int(settings["conversation"].get("history_turns", 12)),
            on_event=self._conversation_event, on_action=self.action, search=self._search_function(settings))

    def _search_function(self, settings):
        """Search for models without their own: only with a search key, and not for Claude (it has its own)."""
        if not settings["conversation"].get("web_search", True) or settings["llm"].get("provider") == "anthropic":
            return None
        if self.provider_factory:
            return self.provider_factory("search", self)
        key = self.store.secret("search")
        if not key:
            return None
        from .search import TavilySearch
        return TavilySearch(key).search

    def _conversation_event(self, kind, data):
        if kind == "heard":
            self.set_state("thinking")
        elif kind == "saying":
            self.set_state("speaking")
        elif kind == "replied":
            self.set_state("listening" if self.listening else "idle")
            asyncio.ensure_future(self._maybe_update_notes())
        self.emit(kind, data)

    async def _maybe_update_notes(self):
        if not self.store.settings()["conversation"].get("memory", True):
            return
        memory = self.memory()
        if memory.turns_since_update < NOTES_EVERY:
            return
        try:
            count = await memory.update_notes(self.build("llm"))
            self.emit("memory", {"notes": count})
        except ProviderError as error:
            self.emit("error", {"message": "memory notes were not updated: %s" % error})

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self.emit("state", {"state": state})

    # ----- talking
    async def say(self, text):
        """Reply to typed or recognised words."""
        text = (text or "").strip()[:2000]
        if not text:
            return None
        try:
            self.conversation = self.conversation or self.make_conversation()
        except ProviderError as error:
            self.emit("error", {"message": str(error)})
            await self.notice()
            return None
        return await self.conversation.start(text)

    async def hear(self, pcm):
        """Recognise a recording and reply to it."""
        self.set_state("thinking")
        self.stage.state("thinking")
        try:
            text = await self.build("stt").transcribe(pcm)
        except ProviderError as error:
            self.emit("error", {"message": "speech recognition: %s" % error})
            self.set_state("listening" if self.listening else "idle")
            self.stage.state("listening" if self.listening else "idle")
            await self.notice()
            return None
        if not text:
            self.set_state("listening" if self.listening else "idle")
            self.stage.state("listening" if self.listening else "idle")
            return None
        return await self.say(text)

    def interrupt(self):
        if self.conversation is not None:
            self.conversation.interrupt()

    async def notice(self):
        try:
            await self.speaker.play(tone(), 24000, lambda level: None)
        except Exception:
            pass

    # ----- the button
    def button(self):
        """One press. Interrupts speech; otherwise turns listening on or off (or ends a push-to-talk recording)."""
        mode = self.store.settings()["listening"].get("mode", "auto")
        if self.conversation is not None and self.conversation.busy:
            self.interrupt()
            self.emit("button", {"did": "interrupt"})
            return
        if mode == "push":
            if self.recording is None:
                self.recording = []
                self.set_state("listening")
                self.stage.state("listening")
                self.emit("button", {"did": "record"})
            else:
                pcm, self.recording = b"".join(self.recording), None
                self.emit("button", {"did": "send"})
                asyncio.ensure_future(self.hear(pcm))
            return
        self.listening = not self.listening
        self.set_state("listening" if self.listening else "idle")
        self.stage.state("listening" if self.listening else "idle")
        self.emit("button", {"did": "listen on" if self.listening else "listen off"})

    async def listen_loop(self):
        """Feed the microphone to the speech detector while listening is on."""
        if self.microphone is None:
            return
        settings = self.store.settings()["listening"]
        detector = Detector(float(settings.get("end_silence", 0.8)), float(settings.get("max_turn", 30.0)))
        while True:
            try:
                async for frame in self.microphone.frames():
                    if self.recording is not None:
                        self.recording.append(frame)
                        continue
                    busy = self.state in ("thinking", "speaking")
                    barge_in = self.store.settings()["listening"].get("voice_interrupt", False)
                    if not self.listening or (busy and not barge_in):
                        detector.reset()          # without echo cancellation, ignore our own voice
                        continue
                    was_speaking = detector.speaking
                    pcm = detector.feed(frame)
                    if busy and detector.speaking and not was_speaking:
                        # The person started talking over the character: stop it and keep listening.
                        self.interrupt()
                        self.emit("button", {"did": "interrupted by voice"})
                    if pcm:
                        asyncio.ensure_future(self.hear(pcm))
            except Exception as error:
                self.emit("error", {"message": "microphone: %s" % error})
            await asyncio.sleep(2.0)

    # ----- timers and alarms
    def action(self, action):
        kind = action.get("kind")
        label = action.get("label") or kind
        if kind == "timer":
            self._schedule(label, time.time() + action["seconds"], "timer")
        elif kind == "alarm":
            hour, minute = (int(x) for x in action["time"].split(":"))
            now = datetime.datetime.now()
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if due <= now:
                due += datetime.timedelta(days=1)
            self._schedule(label, due.timestamp(), "alarm")
        elif kind == "cancel":
            for key in [k for k in self.timers if label.lower() in k.lower()]:
                self.timers.pop(key)[1].cancel()
                self.emit("timer", {"label": key, "did": "cancelled"})
        self._save_timers()

    def _schedule(self, label, due, kind):
        if label in self.timers:
            self.timers.pop(label)[1].cancel()
        handle = asyncio.get_running_loop().call_later(max(0.0, due - time.time()),
                                                       lambda: asyncio.ensure_future(self._ring(label, kind)))
        self.timers[label] = (due, handle, kind)
        self.emit("timer", {"label": label, "due": round(due), "kind": kind})

    async def _ring(self, label, kind):
        self.timers.pop(label, None)
        self._save_timers()
        self.emit("timer", {"label": label, "did": "rang"})
        words = "Your %s timer is done." % label if kind == "timer" else "It's time: %s." % label
        try:
            self.conversation = self.conversation or self.make_conversation()
            await self.conversation.start("(The %s you asked for has just gone off. Tell the person, briefly: %s)" % (kind, words))
        except ProviderError:
            for _ in range(3):
                await self.notice()

    def _save_timers(self):
        data = [{"label": k, "due": v[0], "kind": v[2]} for k, v in self.timers.items()]
        write_atomic(os.path.join(self.data_dir, "timers.json"), json.dumps(data))

    def restore_timers(self):
        try:
            with open(os.path.join(self.data_dir, "timers.json"), encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return
        for item in saved:
            if item["due"] > time.time() - 60:
                self._schedule(item["label"], item["due"], item.get("kind", "timer"))

    # ----- status for the console
    def status(self):
        cid = self.active_id()
        settings = self.store.settings()
        return {
            "state": self.state,
            "listening": self.listening,
            "character": cid,
            "characters": len(self.characters.ids()),
            "providers": {k: settings[k].get("provider", "") for k in ("llm", "stt", "tts")},
            "keys": self.store.secret_status(),
            "timers": [{"label": k, "due": round(v[0]), "kind": v[2]} for k, v in self.timers.items()],
            "uptime": round(time.time() - self.started),
            "stage_connected": getattr(self.stage, "writer", True) is not None,
            "timezone": self.timezone(),
            # timedatectl needs systemd running (true on the device, not in every test machine)
            "can_set_timezone": shutil.which("timedatectl") is not None and os.path.isdir("/run/systemd/system"),
        }

    def start(self):
        """Start background work. Call from inside the event loop."""
        if hasattr(self.stage, "start"):
            self.stage.start()
        cid = self.active_id()
        if cid and not os.path.exists(self.current_puppet):
            self._link_puppet(cid)
        if not cid:
            write_atomic(self.card, screen.card_puppet(screen.setup_card("this device's address")))
            self._point_stage_at(self.card)
        self.restore_timers()
        if self.microphone is not None:
            asyncio.ensure_future(self.listen_loop())
        if self.wifi is not None:
            asyncio.ensure_future(self.network_watch())
        if isinstance(self.stage, StageLink):
            asyncio.ensure_future(self.stage_watch())

    # ----- Wi-Fi
    async def network_watch(self, wait=40.0):
        """Open a setup hotspot if the device has no network a while after starting."""
        deadline = time.time() + wait
        while time.time() < deadline:
            try:
                if await self.wifi.connected():
                    await self._connected()
                    return
            except NetworkError as error:
                self.emit("error", {"message": "network: %s" % error})
                return
            await asyncio.sleep(2.0)
        try:
            suffix = (await self._serial())[-4:].upper() or "0000"
            ssid, password = await self.wifi.start_hotspot(suffix)
        except NetworkError as error:
            self.emit("error", {"message": "could not open the setup hotspot: %s" % error})
            return
        self.emit("network", {"hotspot": ssid})
        self.show_card(screen.hotspot_card(ssid, password))

    async def _connected(self):
        address = await self.wifi.address()
        self.emit("network", {"connected": True, "address": address})
        if not self.active_id():
            self.show_card(screen.setup_card(address or "this device's address"))

    async def _serial(self):
        try:
            with open("/proc/device-tree/serial-number", "rb") as f:
                return f.read().strip(b"\0").decode() or "0000"
        except OSError:
            return "%04x" % (os.getpid() & 0xffff)

    async def join_wifi(self, ssid, password):
        self.show_card(screen.message_card("Joining Wi-Fi", "Connecting to %s…" % ssid))
        try:
            await self.wifi.join(ssid, password)
        except NetworkError as error:
            ssid_hs, pw = await self.wifi.start_hotspot((await self._serial())[-4:].upper() or "0000")
            self.show_card(screen.hotspot_card(ssid_hs, pw))
            raise
        await self._connected()
        if self.active_id():
            self.show_character()


async def _run_command(*args, timeout=30):
    """Run a system command; return its output or raise RuntimeError with its message."""
    try:
        proc = await asyncio.create_subprocess_exec(*args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise RuntimeError("%s is not installed on this machine" % args[0])
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("%s took too long" % args[0])
    if proc.returncode != 0:
        raise RuntimeError(err.decode("utf-8", "replace").strip() or "%s failed" % args[0])
    return out.decode("utf-8", "replace")
