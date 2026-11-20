"""The device: ties settings, characters, memory, providers, sound, the button and the stage together."""
import asyncio
import datetime
import json
import logging
import os
import random
import re
import shutil
import subprocess
import time

from . import animations, package, providers
from .audio import Detector, Microphone, Speaker, tone
from .characters import Characters, split_persona
from .conversation import Conversation
from .memory import Memory
from . import motions, screen, speech_text, temperament
from . import meaning as meaning_module
from . import updates as updates_module
from .network import NetworkError, WiFi
from .providers import ProviderError
from .stage_link import StageLink
from .store import Store, redact, write_atomic

log = logging.getLogger("companion")

UPDATE_CHECK_EVERY = 12 * 3600
# Speaking first: what the model is told, how long it listens for an answer, and how much speech-like
# sound means someone is there.
GREETING_PROMPT = ("(Nothing has been said yet. You hear someone nearby, most likely them, after %s without "
                   "talking. Speak first: greet them warmly and briefly, one or two short sentences, in your own "
                   "way. If a plan of theirs has had its day, you may ask how it went.)")
ANSWER_WINDOW = 30.0
PRESENCE_SECONDS = 0.8
MEMORY_TEMPERATURE = 0.3      # the background memory work: summing up, memories, the diary
MEMORY_MAX_TOKENS = 700

# Memory is kept up to date in the background (memory.Memory.process): a conversation is summed up, and
# its memories changed, once it is over; a long one's early part as it goes; the diary at night.



# What the settings page shows of the stage's heartbeat.
ANIMATION_FIELDS = ("fps", "state", "mood", "playing", "channels", "budget", "drives", "update_ms", "draw_ms")

class Device:
    def __init__(self, data_dir, stage_socket=None, speaker=None, microphone=None, stage=None,
                 provider_factory=None, wifi=None, restart=None, run=None):
        self.data_dir = data_dir
        self.store = Store(os.path.join(data_dir, "config"))
        self.characters = Characters(os.path.join(data_dir, "characters"))
        self.memory_dir = os.path.join(data_dir, "memory")
        self.stt_model_dir = os.path.join(data_dir, "models", "stt")
        self.tts_model_dir = os.path.join(data_dir, "models", "tts")
        self.current_puppet = os.path.join(data_dir, "current.inp")
        self.movement_map = os.path.join(data_dir, "current-map.json")   # read by the stage at start
        # A 3D avatar's animation style, clip folders, drawing cost and shot, also read by the stage at start.
        self.stage_settings = os.path.join(data_dir, "current-stage.json")
        self.animations = animations.Animations(self.characters)
        # Gestures and idle actions changed or added on the settings page, for every character.
        self.custom_motions = motions.CustomMotions(os.path.join(data_dir, "config", "custom-motions.json"))
        speech_text.set_custom_gestures(self.custom_motions.words())
        self.speaker = speaker or Speaker()
        self.microphone = microphone
        self.stage = stage or StageLink(stage_socket or "/run/companion/stage.sock", self._stage_event)
        self.provider_factory = provider_factory
        self.subscribers = set()
        self.animation = {}                 # the stage's latest report of what the character is doing
        self.gesture_log = []               # its latest gestures, moods and skipped gestures
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
        # A 3D avatar the stage keeps failing with: when the stage was last asked to start again (so a
        # lost connection then is expected), and how many times it failed since the avatar was shown.
        self.stage_restarted = 0.0
        self.stage_ready_at = 0.0
        self.vrm_failures = {}
        self.last_use = 0.0                 # when the settings page was last used
        self.last_talk = 0.0                # when the character last replied
        self.summarising = False            # a memory update is under way
        self.memory_retry = 0.0             # after a failed memory update, wait until then
        self.updates = updates_module.Updates(data_dir)
        self.last_greeting = 0.0            # when the character last spoke first
        self.answer_until = 0.0             # after speaking first, it listens for an answer until then
        self.updating = False               # an update is being fetched or handed to the installer

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

    def publish(self, kind, data=None):
        """A live event for open settings pages that is not kept in the log (frequent ones)."""
        event = {"t": round(time.time(), 2), "kind": kind}
        event.update(data or {})
        for queue in list(self.subscribers):
            if queue.qsize() < 500:
                queue.put_nowait(event)

    def _stage_event(self, event):
        self.stage_seen = time.time()
        kind = event.get("event")
        if kind == "heartbeat":
            # What the character is doing, for the settings page's live view.
            self.animation = {k: event.get(k) for k in ANIMATION_FIELDS}
            self.publish("animation", {"status": self.animation})
        elif kind in ("gesture", "gesture_skipped", "gesture_waiting", "emotion"):
            entry = {"t": round(time.time(), 2), "event": kind, "name": event.get("name") or event.get("emotion")}
            entry.update({k: event[k] for k in ("cause", "played", "why") if event.get(k)})
            self.gesture_log = (self.gesture_log + [entry])[-60:]
            self.publish("animation", {"gesture": entry})
        if kind == "quality":
            self._quality_stepped(event)
        # Stopping soon after it started, unasked, is a failure (a crash or running out of memory).
        lost = kind == "lost" and time.time() - self.stage_restarted > 10.0 and time.time() - self.stage_ready_at < 60.0
        if kind == "fatal" or lost:
            self._stage_failed(event.get("message") or "the screen program stopped")
        if kind == "ready":
            self.stage_ready_at = time.time()
        if event.get("event") in ("error", "fatal"):
            self.emit("stage_error", {"message": event.get("message", "")})
        elif event.get("event") == "ready":
            if hasattr(self.stage, "random_gestures"):
                self.stage.random_gestures(self.store.settings()["conversation"].get("random_gestures", True))
            self.use_emotion_map()
            self.use_custom_motions()
            self.use_character_motion()
            self.tell_the_time()

    def tell_the_time(self):
        """Tell the stage the local time of day (the character is sleepy at night)."""
        if hasattr(self.stage, "clock"):
            now = time.localtime()
            self.stage.clock(now.tm_hour + now.tm_min / 60.0 + now.tm_sec / 3600.0)

    async def clock_watch(self, every=600.0):
        """Keep the stage's time of day right (the clock may change, or be set, while it runs)."""
        while True:
            await asyncio.sleep(every)
            self.tell_the_time()

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
                # A 3D avatar gets a second try, drawn lightly, before the card.
                if self._stage_failed("the screen program did not start"):
                    self.stage_seen = time.time()
                    continue
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
        keep = {"models", "updates"}           # the software's, not the owner's: kept like the speech models
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
            if settings["tts"].get("provider") == "local":
                # The on-device voice is kept loaded too (about 110 MB, a second to load); only the
                # speaker changes from character to character.
                key = json.dumps(settings["tts"], sort_keys=True)
                if getattr(self, "_tts_key", None) != key:
                    self._tts = None
                    self._tts = providers.build_tts(settings, self.store, model_dir=self.tts_model_dir)
                    self._tts_key = key
                self._tts.set_voice(extra.get("voice") or settings["tts"].get("voice", ""))
                return self._tts
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
        return Memory(os.path.join(self.memory_dir, cid or "_none"),
                      meaning=meaning_module.load(os.path.join(self.data_dir, "models", "meaning")))

    def activate(self, cid):
        if cid not in self.characters.ids():
            raise KeyError(cid)
        self.interrupt()
        self.vrm_failures.pop(cid, None)          # chosen again: a fresh start
        self.store.update_settings({"active_character": cid})
        self._link_puppet(cid)
        self.use_emotion_map(cid)
        self.conversation = None
        self.restart_stage()                 # the service manager starts it again with the new puppet
        self.emit("character", {"id": cid})

    def use_emotion_map(self, cid=None):
        """Tell the stage link which of the character's own expressions shows each emotion."""
        cid = cid or self.active_id()
        if cid and hasattr(self.stage, "emotion_map"):
            self.stage.emotion_map = self.characters.emotion_map(cid)

    def use_custom_motions(self):
        """Give the stage the gestures and idle actions changed or added on this device (and tell the
        language model about them, with the new gestures a 3D avatar's own clips add)."""
        words = self.custom_motions.words()
        cid = self.active_id()
        if cid:
            words.update(self.animations.words(cid))
        speech_text.set_custom_gestures(words)
        if hasattr(self.stage, "define"):
            for name, entry in self.custom_motions.all().items():
                self.stage.define(name, entry)

    def use_character_motion(self, cid=None):
        """Tell the stage the character's temperament, and the gestures it never makes by itself."""
        cid = cid or self.active_id()
        saved = self.characters.device_settings(cid) if cid else {}
        energy, expressiveness = temperament.for_stage(saved.get("temperament"))
        off = [str(g)[:60] for g in saved.get("gestures_off") or []][:100]
        if hasattr(self.stage, "temperament"):
            self.stage.temperament(energy, expressiveness)
        if hasattr(self.stage, "gestures_off"):
            self.stage.gestures_off(off)
        if self.conversation is not None:
            self.conversation.planner.expressiveness = expressiveness

    def _link_puppet(self, cid):
        """Point the stage at the character's drawing. The stage tells the formats apart by content."""
        inochi = ("visual/puppet.inp", "visual/puppet.inx")
        live2d = (package.LIVE2D_MODEL,)
        prefer_inochi = self.store.settings().get("character_format") == "inochi2d"
        # A VRM avatar (3D) is the character's only drawing when it has one.
        for name in (package.VRM_MODEL,) + ((inochi + live2d) if prefer_inochi else (live2d + inochi)):
            target = self.characters.file(cid, name)
            if os.path.exists(target):
                # The owner's movement settings name the drawing's parameters; both drawings of a character
                # use the same names, and the stage keeps its own choice for any it lacks.
                self.write_movement_map(cid)
                self.write_stage_settings(cid)
                self._point_stage_at(target)
                return
        self.write_movement_map()
        self.write_stage_settings()
        write_atomic(self.card, screen.card_puppet(screen.message_card(
            "Can't show this character",
            "Its package has no drawing this device can show. Try installing it again.")))
        self._point_stage_at(self.card)

    def show_card(self, png):
        """Show a message on the screen instead of the character."""
        self.write_movement_map()
        self.write_stage_settings()
        write_atomic(self.card, screen.card_puppet(png))
        self._point_stage_at(self.card)
        self.restart_stage()

    def show_character(self):
        cid = self.active_id()
        if cid:
            self._link_puppet(cid)
            self.restart_stage()
        return cid

    def restart_stage(self):
        """Ask the stage to start again (the service manager does), with what it is to show now."""
        self.stage_restarted = time.time()
        self.stage.send({"quit": True})

    def _stage_failed(self, why):
        """The stage stopped, or never started, while showing a 3D avatar: draw it lighter once; if that
        fails too, show a card saying it is too much for this device. Other characters are left to the
        service manager (it starts the stage again) and to stage_watch."""
        cid = self.active_id()
        if not cid or self.characters.drawing(cid) != "vrm" or os.path.realpath(self.current_puppet) == os.path.realpath(self.card):
            return False
        failures = self.vrm_failures.get(cid, 0) + 1
        self.vrm_failures[cid] = failures
        quality = self.animations.settings(cid)["quality"]
        if quality != "lite":
            self.animations.set_settings(cid, {"quality": "lite"})
            self.characters.set_device_settings(cid, {"vrm_failsafe": {"why": str(why)[:200], "at": int(time.time())}})
            self.write_stage_settings(cid)
            self.emit("error", {"message": "the 3D avatar stopped the screen (%s); showing it with a lighter drawing" % str(why)[:120]})
            return True
        if failures >= 2:
            self.emit("error", {"message": "the 3D avatar is too much for this device, even drawn lightly; showing a message instead"})
            self.show_card(screen.message_card(
                "Too detailed for this device",
                "This 3D avatar needs more than this device has, even drawn lightly. Choose another character, "
                "or export it with fewer polygons and smaller textures and add it again."))
            return True
        return False

    def _quality_stepped(self, event):
        """The stage drew a 3D avatar more simply because frames came too slowly: keep a note for the
        settings page."""
        cid = self.active_id()
        if not cid:
            return
        seen = {"level": int(event.get("level") or 0), "change": str(event.get("change") or "")[:80],
                "fps": event.get("fps"), "at": int(time.time())}
        self.characters.set_device_settings(cid, {"vrm_quality_seen": seen})
        self.emit("stage_quality", {"message": "the screen was too slow, so the avatar is now " + seen["change"]})

    def write_movement_map(self, cid=None):
        """The movement settings of the character on the screen (none for a message card), for the stage."""
        controls = self.characters.device_settings(cid).get("controls") if cid else None
        write_atomic(self.movement_map, json.dumps(controls if isinstance(controls, dict) else {}, indent=1))

    def write_stage_settings(self, cid=None):
        """The stage settings of the character on the screen (a 3D avatar's animation style and the
        like; none for others)."""
        write_atomic(self.stage_settings, json.dumps(self.animations.stage_settings(cid) if cid else {}, indent=1))

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
        conversation = Conversation(
            llm=self.build("llm"), tts=self.build("tts", voice=voice),
            speaker=self.speaker, stage=self.stage, memory=self.memory(cid),
            persona=self.characters.persona(cid),
            history_turns=int(settings["conversation"].get("history_turns", 12)),
            on_event=self._conversation_event, on_action=self.action, search=self._search_function(settings),
            gestures=None if settings["conversation"].get("gestures", True) else [])
        # A reserved character's words call for fewer gestures; an expressive one's for more.
        conversation.planner.expressiveness = temperament.for_stage(
            self.characters.device_settings(cid).get("temperament"))[1]
        return conversation

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
            self.last_talk = time.time()
            self.set_state("listening" if self.listening else "idle")
            asyncio.ensure_future(self.keep_memory())
        self.emit(kind, data)

    async def keep_memory(self, cid=None, now=None, force=False):
        """Bring a character's memory up to date if anything is due: a conversation that is over summed
        up (with its memories), the early part of a long one, the diary. One at a time, never while the
        character is talking, and after a failure not again for a while (unless `force`)."""
        settings = self.store.settings()["conversation"]
        if not settings.get("memory", True) or self.summarising:
            return None
        if (self.conversation is not None and self.conversation.busy) or (not force and time.time() < self.memory_retry):
            return None
        cid = cid or self.active_id()
        if not cid:
            return None
        memory = self.memory(cid)
        memory.close_stale(now)               # needs no model: a conversation ends on time even without one
        keep = int(settings.get("history_turns", 12))
        if not memory.needs_work(now, keep=keep):
            return None
        self.summarising = True
        try:
            name = self.characters.manifest(cid).get("name", "")
            persona, _ = split_persona(self.characters.persona(cid))
            llm = self.build("llm")
            # Careful note-taking, not lively talk: a low temperature, and room for a full answer.
            if isinstance(getattr(llm, "temperature", None), (int, float)):
                llm.temperature = min(llm.temperature, MEMORY_TEMPERATURE)
            if isinstance(getattr(llm, "max_tokens", None), int):
                llm.max_tokens = max(llm.max_tokens, MEMORY_MAX_TOKENS)
            done = await memory.process(llm, now=now, name=name, persona=persona, keep=keep)
            if done["summed"] or done["diary"]:
                self.emit("memory", dict(done, character=cid))
            return done
        except ProviderError as error:
            self.memory_retry = time.time() + 15 * 60
            self.emit("error", {"message": "the memory was not brought up to date: %s" % error})
            return None
        finally:
            self.summarising = False

    async def memory_watch(self, every=60.0):
        """Keep every character's memory up to date: conversations that have gone quiet are summed up
        (so short chats, and the last turns before a restart or a change of character, are remembered
        too), and each day's diary is written."""
        while True:
            await asyncio.sleep(every)
            try:
                for cid in self.characters.ids():
                    await self.keep_memory(cid)
            except Exception:
                log.exception("memory watch failed")

    # ----- software updates (docs/32-updates.md)
    async def install_update(self):
        """Fetch the update found (if not already) and ask the installer to install it. The service
        restarts on the new version; if that does not start properly, the installer goes back."""
        if self.updating:
            return None
        self.updating = True
        try:
            status = self.updates.status()
            if not status["ready"]:
                found = status["found"] or await self.updates.check()
                if not found:
                    raise updates_module.UpdateError("there is no newer version")
                self.emit("update", {"did": "downloading", "version": found["version"]})
                await self.updates.download(found)
            version = self.updates.request_install()
            self.emit("update", {"did": "installing", "version": version})
            self.show_card(screen.message_card("Updating", "Installing version %s…" % version))
            return version
        except updates_module.UpdateError as error:
            self.emit("error", {"message": "update: %s" % error})
            raise
        finally:
            self.updating = False

    async def update_step(self, now=None):
        """One pass of keeping the software up to date: look for an update twice a day, fetch it, and
        install it at night (2 to 5 am) when nobody has talked for half an hour. Returns what it did."""
        now = now or time.time()
        settings = self.store.settings().get("updates", {})
        status = self.updates.status()
        if not settings.get("check", True) or not status["online"] or self.updating:
            return None
        try:
            found = status["found"]
            if now - (status.get("checked") or 0) >= UPDATE_CHECK_EVERY:
                found = await self.updates.check()
                if found:
                    self.emit("update", {"did": "found", "version": found["version"]})
            if not settings.get("auto_install", True) or not (found or status["ready"]):
                return "found" if found else None
            hour = datetime.datetime.fromtimestamp(now).hour
            quiet = now - self.last_talk > 30 * 60 and self.state == "idle"
            if 2 <= hour < 5 and quiet:
                await self.install_update()
                return "installing"
            if found and not status["ready"]:
                self.updating = True
                try:
                    await self.updates.download(found)
                finally:
                    self.updating = False
                return "downloaded"
            return "waiting"
        except updates_module.UpdateError as error:
            self.emit("error", {"message": "update: %s" % error})
            return None

    async def update_watch(self, every=30 * 60):
        await asyncio.sleep(10 * 60 + random.random() * 600)      # devices sold together do not all ask at once
        while True:
            try:
                await self.update_step()
            except Exception:
                log.exception("update watch failed")
            await asyncio.sleep(every)

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

    # ----- speaking first (docs/31-memory.md)
    async def greet(self, now=None):
        """Speak first, when someone seems to be back after a while: a short greeting, from what the
        character remembers (how long it has been, plans whose day has come). Only when the owner has
        turned it on, outside quiet hours, at most once a while, and never over a conversation."""
        now = now or time.time()
        opts = self.store.settings().get("speak_first", {})
        if not opts.get("on") or self.state not in ("idle",) or (self.conversation is not None and self.conversation.busy):
            return None
        hour = datetime.datetime.fromtimestamp(now).hour
        start, end = int(opts.get("quiet_from", 22)), int(opts.get("quiet_to", 8))
        if (start <= hour or hour < end) if start > end else (start <= hour < end):
            return None
        cid = self.active_id()
        if not cid:
            return None
        apart = now - max(self.memory(cid).last_turn_time(), self.last_greeting)
        if apart < float(opts.get("after_hours", 3)) * 3600:
            return None
        try:
            self.conversation = self.conversation or self.make_conversation()
        except ProviderError:
            return None
        self.last_greeting = now
        days = apart / 86400
        gap = ("about %d days" % round(days)) if days >= 1.5 else ("about %d hours" % max(1, round(apart / 3600))) \
            if apart < 30 * 86400 else "a long time"
        self.emit("speaking first", {"apart": round(apart)})
        task = self.conversation.start("", prompt=GREETING_PROMPT % gap)
        reply = await task
        if reply is not None and not reply.error and not reply.interrupted and \
                self.store.settings()["listening"].get("mode", "auto") == "auto" and not self.listening:
            # Listen a little while for an answer, so they can just reply.
            self.listening = True
            self.answer_until = time.time() + ANSWER_WINDOW
            self.set_state("listening")
            self.stage.state("listening")
        return reply

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
        if hasattr(self.stage, "poke"):
            self.stage.poke()                 # someone is there
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
        # Someone seems to be there (for speaking first): speech-like sound, from its loudness alone.
        presence = Detector(0.6, 8.0)
        while True:
            try:
                async for frame in self.microphone.frames():
                    if self.recording is not None:
                        self.recording.append(frame)
                        self._heard(detector.loudness(frame))
                        continue
                    busy = self.state in ("thinking", "speaking")
                    barge_in = self.store.settings()["listening"].get("voice_interrupt", False)
                    if self.answer_until and self.listening and not detector.speaking and time.time() > self.answer_until:
                        self.answer_until = 0.0     # no answer to its greeting: stop listening, as before it spoke
                        self.listening = False
                        self.set_state("idle")
                        self.stage.state("idle")
                    if not self.listening or (busy and not barge_in):
                        detector.reset()          # without echo cancellation, ignore our own voice
                        if not busy and self.store.settings().get("speak_first", {}).get("on"):
                            sound = presence.feed(frame)
                            if sound and len(sound) / 2 / 16000 >= PRESENCE_SECONDS:
                                asyncio.ensure_future(self.greet())
                        else:
                            presence.reset()
                        continue
                    if detector.speaking:
                        self.answer_until = 0.0     # they answered: carry on as usual
                    was_speaking = detector.speaking
                    pcm = detector.feed(frame)
                    if self.state == "listening":
                        # The character hears the person: it looks up as they start, and nods in their pauses.
                        self._heard(detector.loudness(frame))
                    if busy and detector.speaking and not was_speaking:
                        # The person started talking over the character: stop it and keep listening.
                        self.interrupt()
                        self.emit("button", {"did": "interrupted by voice"})
                    if pcm:
                        asyncio.ensure_future(self.hear(pcm))
            except Exception as error:
                self.emit("error", {"message": "microphone: %s" % error})
            await asyncio.sleep(2.0)

    def _heard(self, level):
        if hasattr(self.stage, "heard"):
            self.stage.heard(level)

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
            write_atomic(self.card, screen.card_puppet(screen.setup_card()))
            self._point_stage_at(self.card)
        self.restore_timers()
        if self.microphone is not None:
            asyncio.ensure_future(self.listen_loop())
        if self.wifi is not None:
            asyncio.ensure_future(self.network_watch())
        if isinstance(self.stage, StageLink):
            asyncio.ensure_future(self.stage_watch())
        asyncio.ensure_future(self.memory_watch())
        asyncio.ensure_future(self.clock_watch())
        asyncio.ensure_future(self.update_watch())

    # ----- Wi-Fi
    async def network_watch(self, wait=40.0, retry=180.0, busy=120.0):
        """Keep the device on a network, opening a setup hotspot when it has none.

        With no network a while after starting, the device opens its setup
        hotspot. If it has joined a home network before (the usual case after
        a power cut, when the router starts more slowly than the device), it
        closes the hotspot every few minutes to try that network again, unless
        someone is using the settings page through the hotspot right now.
        """
        while True:
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
                saved = await self.wifi.saved_networks()
                if self.wifi.hotspot is None:
                    suffix = (await self._serial())[-4:].upper() or "0000"
                    ssid, password = await self.wifi.start_hotspot(suffix)
                    self.emit("network", {"hotspot": ssid})
                    self.show_card(screen.hotspot_card(ssid, password))
            except NetworkError as error:
                self.emit("error", {"message": "could not open the setup hotspot: %s" % error})
                return
            if not saved:
                return                      # a new device: wait in the hotspot for the owner
            while True:
                await asyncio.sleep(retry)
                if self.wifi.hotspot is None:
                    return                  # the owner joined a network meanwhile
                if time.time() - self.last_use > busy:
                    break
            await self.wifi.stop_hotspot()  # let NetworkManager try the saved networks again
            self.emit("network", {"retrying": saved})

    async def _connected(self):
        address = await self.wifi.address()
        self.emit("network", {"connected": True, "address": address})
        if not self.active_id():
            self.show_card(screen.setup_card(address))

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
