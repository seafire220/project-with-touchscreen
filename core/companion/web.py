"""The web console's server: a password-protected API on the home network.

Rules:
- Only addresses on the local network are served.
- A password is set on first use; after that every API call needs a login.
- Keys can be set or cleared, never read back.
- Requests that change anything must carry the header `X-Companion: 1`,
  which a web page on another site cannot add, so it cannot act for you.
"""
import asyncio
import io
import ipaddress
import json
import os
import re
import secrets
import time
import urllib.parse

from aiohttp import web

from . import animations, cards, motions, package, persona, providers, speech_text, temperament, vrm
from . import memory as memory_module
from .memory import when
from .network import NetworkError
from .providers import ProviderError, clone_voice_elevenlabs
from .stage_link import CONTROL_NAMES, CONTROLS

SESSION_COOKIE = "companion_session"
SESSION_HOURS = 12
MAX_UPLOAD = package.MAX_TOTAL + 1024 * 1024
STATIC = os.path.join(os.path.dirname(__file__), "console")
OPEN_PATHS = {"/api/login", "/api/setup", "/api/hello"}


def local_address(remote):
    try:
        ip = ipaddress.ip_address((remote or "").split("%")[0])
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


class Console:
    def __init__(self, device):
        self.device = device
        self.sessions = {}
        self.failures = {}

    # ----- middleware
    @web.middleware
    async def guard(self, request, handler):
        if not local_address(request.remote):
            raise web.HTTPForbidden(text="this device only answers on its home network")
        path = request.path
        self.device.last_use = time.time()
        if path.startswith("/api/"):
            if request.method not in ("GET", "HEAD") and request.headers.get("X-Companion") != "1":
                raise web.HTTPForbidden(text="missing X-Companion header")
            if path not in OPEN_PATHS and not self._session_ok(request):
                raise web.HTTPUnauthorized(text="please log in")
        response = await handler(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'")
        return response

    def _session_ok(self, request):
        token = request.cookies.get(SESSION_COOKIE, "")
        expires = self.sessions.get(token)
        if not expires or expires < time.time():
            self.sessions.pop(token, None)
            return False
        return True

    def _new_session(self, response):
        token = secrets.token_urlsafe(32)
        self.sessions[token] = time.time() + SESSION_HOURS * 3600
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Strict", max_age=SESSION_HOURS * 3600)
        return response

    # ----- login
    async def hello(self, request):
        return web.json_response({"needs_setup": not self.device.store.has_password(),
                                  "logged_in": self._session_ok(request)})

    async def setup(self, request):
        if self.device.store.has_password():
            raise web.HTTPConflict(text="a password is already set")
        body = await request.json()
        try:
            self.device.store.set_password(body.get("password", ""))
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error))
        return self._new_session(web.json_response({"ok": True}))

    async def login(self, request):
        ip = request.remote
        count, until = self.failures.get(ip, (0, 0))
        if until > time.time():
            raise web.HTTPTooManyRequests(text="too many attempts; wait %d seconds" % (until - time.time()))
        body = await request.json()
        if not self.device.store.check_password(body.get("password", "")):
            count += 1
            self.failures[ip] = (count, time.time() + 30 if count >= 5 else 0)
            await asyncio.sleep(0.5)
            raise web.HTTPUnauthorized(text="wrong password")
        self.failures.pop(ip, None)
        return self._new_session(web.json_response({"ok": True}))

    async def logout(self, request):
        self.sessions.pop(request.cookies.get(SESSION_COOKIE, ""), None)
        response = web.json_response({"ok": True})
        response.del_cookie(SESSION_COOKIE)
        return response

    async def password(self, request):
        body = await request.json()
        if not self.device.store.check_password(body.get("old", "")):
            raise web.HTTPUnauthorized(text="the current password is wrong")
        try:
            self.device.store.set_password(body.get("new", ""))
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error))
        self.sessions.clear()
        return self._new_session(web.json_response({"ok": True}))

    # ----- status and events
    async def status(self, request):
        return web.json_response(self.device.status())

    async def animation(self, request):
        """What the character is doing now: its state, mood, drives, gestures and budget, and its latest
        gestures (with those skipped, and why)."""
        return web.json_response({"status": self.device.animation, "log": self.device.gesture_log[-60:]})

    async def events(self, request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store"})
        await response.prepare(request)
        queue = asyncio.Queue()
        self.device.subscribers.add(queue)
        try:
            for event in self.device.log[-30:]:
                await response.write(("data: %s\n\n" % json.dumps(event)).encode())
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), 15)
                    await response.write(("data: %s\n\n" % json.dumps(event)).encode())
                except asyncio.TimeoutError:
                    await response.write(b": keep-alive\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.device.subscribers.discard(queue)
        return response

    # ----- settings and keys
    async def get_settings(self, request):
        return web.json_response(self.device.store.settings())

    async def put_settings(self, request):
        changes = await request.json()
        if not isinstance(changes, dict):
            raise web.HTTPBadRequest(text="settings must be an object")
        old = self.device.store.settings()
        try:
            merged = self.device.store.update_settings(changes)
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error))
        self.device.conversation = None
        if merged.get("character_format") != old.get("character_format"):
            self.device.show_character()          # the other drawing of the same character, if it has one
        random_now = merged["conversation"].get("random_gestures", True)
        if random_now != old["conversation"].get("random_gestures", True) and hasattr(self.device.stage, "random_gestures"):
            self.device.stage.random_gestures(random_now)
        return web.json_response(merged)

    async def get_keys(self, request):
        return web.json_response(self.device.store.secret_status())

    async def put_key(self, request):
        body = await request.json()
        try:
            self.device.store.set_secret(request.match_info["name"], body.get("value", ""))
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error))
        self.device.conversation = None
        return web.json_response(self.device.store.secret_status())

    async def test_provider(self, request):
        which = request.match_info["which"]
        if which not in ("llm", "stt", "tts"):
            raise web.HTTPNotFound()
        try:
            result = await asyncio.wait_for(self.device.build(which).test(), 60)
        except (ProviderError, asyncio.TimeoutError) as error:
            return web.json_response({"ok": False, "message": str(error) or "timed out"})
        return web.json_response({"ok": True, "message": result})

    async def models(self, request):
        try:
            names = await asyncio.wait_for(self.device.build("llm").models(), 30)
        except (ProviderError, asyncio.TimeoutError, AttributeError) as error:
            return web.json_response({"ok": False, "message": str(error) or "timed out", "models": []})
        return web.json_response({"ok": True, "models": names})

    async def find_llm(self, request):
        """Language-model servers on the home network, or at the address the owner typed, to choose from."""
        try:
            body = await request.json()
        except ValueError:
            body = {}
        typed = str((body or {}).get("host") or "").strip() if isinstance(body, dict) else ""
        hosts, ports = None, None
        if typed:
            try:
                parts = urllib.parse.urlsplit(typed if "://" in typed else "http://" + typed)
                hosts = [parts.hostname] if parts.hostname else None
                if parts.port:
                    ports = sorted({v["port"] for v in providers.LOCAL_SERVERS.values() if v["port"]} | {parts.port})
            except ValueError:
                raise web.HTTPBadRequest(text="that does not look like a computer's address")
        try:
            found = await asyncio.wait_for(providers.find_servers(hosts=hosts, ports=ports), 25)
        except asyncio.TimeoutError:
            found = []
        return web.json_response({"servers": found})

    async def voices(self, request):
        try:
            tts = self.device.build("tts")
            names = await asyncio.wait_for(tts.voices(), 30)
        except AttributeError:
            return web.json_response({"ok": False, "message": "this voice service has no voice list", "voices": []})
        except (ProviderError, asyncio.TimeoutError) as error:
            return web.json_response({"ok": False, "message": str(error) or "timed out", "voices": []})
        return web.json_response({"ok": True, "voices": names})

    # ----- characters
    async def list_characters(self, request):
        return web.json_response({"active": self.device.active_id(), "characters": self.device.characters.list()})

    async def upload_character(self, request):
        data = await request.read()
        replace = request.query.get("replace") == "1"
        try:
            if package.is_live2d_zip(data):
                # A buyer's own Live2D-format model, zipped as it comes for VTube Studio and the like.
                data = package.from_live2d_zip(io.BytesIO(data), name=request.query.get("name") or None)
            elif vrm.is_vrm(data):
                # A VRM avatar (3D): its textures are scaled down for this device, which takes a while.
                data = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: package.from_vrm(data, name=request.query.get("name") or None,
                                                   texture_side=vrm.device_texture_side()))
            cid = self.device.characters.install(data, replace=replace)
        except package.PackageError as error:
            raise web.HTTPBadRequest(text=str(error))
        self.device.emit("character", {"id": cid, "did": "installed"})
        if len(self.device.characters.ids()) == 1:
            self.device.activate(cid)
        return web.json_response({"id": cid})

    def _cid(self, request):
        cid = request.match_info["cid"]
        if cid not in self.device.characters.ids():
            raise web.HTTPNotFound(text="no such character")
        return cid

    async def activate(self, request):
        self.device.activate(self._cid(request))
        return web.json_response({"ok": True})

    async def delete_character(self, request):
        cid = self._cid(request)
        if cid == self.device.active_id() and len(self.device.characters.ids()) > 1:
            other = next(c for c in self.device.characters.ids() if c != cid)
            self.device.activate(other)
        self.device.characters.delete(cid)
        return web.json_response({"ok": True})

    async def preview(self, request):
        cid = self._cid(request)
        for name, kind in (("preview.png", "image/png"), ("preview.webp", "image/webp")):
            path = self.device.characters.file(cid, name)
            if os.path.exists(path):
                return web.FileResponse(path, headers={"Content-Type": kind})
        raise web.HTTPNotFound()

    async def export(self, request):
        cid = self._cid(request)
        data = self.device.characters.export(cid)
        return web.Response(body=data, content_type="application/octet-stream",
                            headers={"Content-Disposition": 'attachment; filename="%s.char"' % cid})

    async def get_persona(self, request):
        cid = self._cid(request)
        device = self.device.characters.device_settings(cid)
        return web.json_response({"persona": self.device.characters.persona(cid), "device": device,
                                  "form": device.get("persona_form") or {}, "questions": list(persona.NAMES)})

    async def get_emotions(self, request):
        cid = self._cid(request)
        from .speech_text import EMOTIONS
        return web.json_response({"emotions": [e for e in EMOTIONS if e != "neutral"],
                                  "expressions": self.device.characters.expressions(cid),
                                  "map": self.device.characters.emotion_map(cid)})

    async def put_emotions(self, request):
        """Choose which of the character's own expressions shows each emotion ("" for none)."""
        cid = self._cid(request)
        from .speech_text import EMOTIONS
        body = await request.json()
        wanted = body.get("map") if isinstance(body, dict) else None
        known = set(self.device.characters.expressions(cid))
        if not isinstance(wanted, dict) or any(k not in EMOTIONS or not isinstance(v, str) or (v and v not in known)
                                               for k, v in wanted.items()):
            raise web.HTTPBadRequest(text="map must name our emotions and the character's own expressions")
        self.device.characters.set_device_settings(cid, {"emotions": wanted})
        if cid == self.device.active_id():
            self.device.use_emotion_map(cid)
        return web.json_response({"map": self.device.characters.emotion_map(cid)})

    async def read_card(self, request):
        """A character card (PNG or JSON) as a persona to review; nothing is saved."""
        data = await request.read()
        try:
            card = cards.read_card(data)
        except cards.CardError as error:
            raise web.HTTPBadRequest(text=str(error))
        text, greeting = cards.to_persona(card)
        if package.contains_secret(text):
            raise web.HTTPBadRequest(text="the card appears to contain an API key; it was not used")
        return web.json_response({"name": card["name"], "persona": text, "greeting": greeting, "tags": card["tags"],
                                  "creator": card["creator"]})

    # ----- full-body animation for 3D (VRM) avatars
    def _vrm_cid(self, request):
        cid = self._cid(request)
        if self.device.characters.drawing(cid) != "vrm":
            raise web.HTTPBadRequest(text="only 3D (VRM) avatars have full-body animations")
        return cid

    def _stage_gestures(self):
        link = self.device.stage
        return list(getattr(link, "gestures", []) or []) + list(getattr(link, "actions", []) or [])

    def _restage(self, cid):
        """Show the character again with its new settings, if it is the one on the screen."""
        self.device.vrm_failures.pop(cid, None)
        if cid == self.device.active_id():
            self.device.show_character()

    async def get_animations(self, request):
        cid = self._vrm_cid(request)
        out = self.device.animations.describe(cid, self._stage_gestures())
        out["active"] = cid == self.device.active_id()
        return web.json_response(out)

    async def put_animations(self, request):
        """The animation style (full or light), how much the drawing may cost, and the shot."""
        cid = self._vrm_cid(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="send animation, quality and shot")
        try:
            settings = self.device.animations.set_settings(cid, body)
        except animations.AnimationError as error:
            raise web.HTTPBadRequest(text=str(error))
        self._restage(cid)
        return web.json_response({"settings": settings})

    async def add_animation(self, request):
        """Keep a VRM Animation clip for the character, in the role named (an idle loop, a gesture it
        replaces, or a new gesture with the words that say what it means)."""
        cid = self._vrm_cid(request)
        role = request.match_info["role"]
        data = await request.read()
        try:
            entry = self.device.animations.add(cid, role, data, title=request.query.get("title", ""),
                                               words=request.query.get("words"), gestures=self._stage_gestures())
        except animations.AnimationError as error:
            raise web.HTTPBadRequest(text=str(error))
        self.device.emit("animation_added", {"id": cid, "role": role})
        self._restage(cid)
        return web.json_response(dict(entry, role=role))

    async def delete_animation(self, request):
        cid = self._vrm_cid(request)
        if not self.device.animations.remove(cid, request.match_info["role"]):
            raise web.HTTPNotFound(text="no such animation")
        self._restage(cid)
        return web.json_response({"ok": True})

    async def try_animation(self, request):
        """Play one of the character's added clips once on the screen."""
        cid = self._vrm_cid(request)
        if cid != self.device.active_id():
            raise web.HTTPConflict(text="put the character on the screen first")
        try:
            path = self.device.animations.path(cid, request.match_info["role"])
        except KeyError:
            raise web.HTTPNotFound(text="no such animation")
        if self.device.stage.send({"try_animation": path}) is False:
            raise web.HTTPServiceUnavailable(text="the character's screen is not running")
        return web.json_response({"ok": True})

    # ----- movement settings: which of the character's own parameters each kind of movement uses
    async def get_movement(self, request):
        cid = self._cid(request)
        link = self.device.stage
        active = cid == self.device.active_id()
        ready = active and bool(getattr(link, "param_info", None))
        saved = self.device.characters.device_settings(cid).get("controls") or {}
        return web.json_response({
            "active": active, "ready": ready,
            "controls": [{"control": key, "label": label} for key, label in CONTROLS],
            "current": list(getattr(link, "controls", [])) if ready else [],
            "params": list(getattr(link, "param_info", [])) if ready else [],
            "gestures": list(getattr(link, "gestures", [])) if ready else [],
            "actions": list(getattr(link, "actions", [])) if ready else [],
            "saved": saved,
            **self._temperament(cid)})

    def _temperament(self, cid):
        settings = self.device.characters.device_settings(cid)
        saved = settings.get("temperament")
        return {"temperament": temperament.clean(saved) if saved else None,
                "suggested": temperament.suggest(self.device.characters.persona(cid)),
                "gestures_off": list(settings.get("gestures_off") or [])}

    # ----- the gesture editor
    async def get_motions(self, request):
        """Every gesture and idle action as the stage has it now, for the editor."""
        link = self.device.stage
        library = await link.describe_library() if hasattr(link, "describe_library") else None
        if not library:
            return web.json_response({"ready": False})
        clips = library["clips"]
        for name, entry in self.device.custom_motions.all().items():
            if name in clips and entry.get("words"):
                clips[name]["words"] = entry["words"]
        return web.json_response({"ready": True, "clips": clips, "controls": library.get("controls") or list(motions.CONTROLS),
                                  "channels": list(motions.CHANNELS)})

    def _check_instead(self, entry):
        library = getattr(self.device.stage, "library", None) or {}
        other = entry.get("instead")
        if other and library.get("clips") is not None and other not in library["clips"]:
            raise web.HTTPBadRequest(text="there is no gesture called %s to play instead" % other)

    async def put_motion(self, request):
        """Save a changed or added gesture on the device, and give it to the stage."""
        name = request.match_info["name"]
        if name == motions.TRY:
            raise web.HTTPBadRequest(text="choose another name")
        body = await request.json()
        try:
            entry = motions.clean(name, body)
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error))
        self._check_instead(entry)
        self.device.custom_motions.set(name, entry)
        speech_text.set_custom_gestures(self.device.custom_motions.words())
        if hasattr(self.device.stage, "define"):
            self.device.stage.define(name, entry)
        return web.json_response({"ok": True, "saved": entry})

    async def delete_motion(self, request):
        """Put a changed gesture back as built, or take an added one away."""
        name = request.match_info["name"]
        if not motions.NAME.fullmatch(name):
            raise web.HTTPBadRequest(text="no such gesture")
        self.device.custom_motions.remove(name)
        speech_text.set_custom_gestures(self.device.custom_motions.words())
        if hasattr(self.device.stage, "undefine"):
            self.device.stage.undefine(name)
        return web.json_response({"ok": True})

    async def try_motion(self, request):
        """Play a gesture as it is in the editor, on the device's screen, without keeping it."""
        body = await request.json()
        try:
            entry = motions.clean(motions.TRY, body)
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error))
        self._check_instead(entry)
        link = self.device.stage
        if not hasattr(link, "define") or not link.define(motions.TRY, entry):
            raise web.HTTPServiceUnavailable(text="the character's screen is not running")
        link.send({"gesture": motions.TRY})
        return web.json_response({"ok": True})

    async def put_temperament(self, request):
        """Save how lively and expressive the character is, and the gestures it never makes by itself."""
        cid = self._cid(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="send liveliness, expressiveness and gestures_off")
        changes = {}
        if "liveliness" in body or "expressiveness" in body:
            changes["temperament"] = temperament.clean(body)
        if "gestures_off" in body:
            off = body["gestures_off"]
            if not isinstance(off, list) or not all(isinstance(g, str) and re.fullmatch(r"[a-z_]{1,40}", g) for g in off):
                raise web.HTTPBadRequest(text="gestures_off is a list of gesture names")
            changes["gestures_off"] = sorted(set(off))[:100]
        self.device.characters.set_device_settings(cid, changes)
        if cid == self.device.active_id():
            self.device.use_character_motion(cid)
        return web.json_response({"ok": True, **self._temperament(cid)})

    async def put_movement(self, request):
        """Save the movement settings ({control: {"param", "invert"} or null to switch it off}) and show the
        character with them. Controls left out keep the stage's own choice."""
        cid = self._cid(request)
        body = await request.json()
        controls = body.get("controls") if isinstance(body, dict) else None
        if not isinstance(controls, dict):
            raise web.HTTPBadRequest(text="send the controls to set")
        active = cid == self.device.active_id()
        known = {p.get("name") for p in getattr(self.device.stage, "param_info", [])} if active else set()
        clean = {}
        for key, spec in controls.items():
            if key not in CONTROL_NAMES:
                raise web.HTTPBadRequest(text="unknown movement: %s" % key)
            if spec is None:
                clean[key] = None
                continue
            if not isinstance(spec, dict) or not isinstance(spec.get("param"), str) or not spec["param"].strip():
                raise web.HTTPBadRequest(text="%s needs one of the character's parameters" % CONTROL_NAMES[key])
            if known and spec["param"] not in known:
                raise web.HTTPBadRequest(text="this character has no parameter called %s" % spec["param"])
            entry = {"param": spec["param"][:100]}
            if spec.get("invert"):
                entry["invert"] = True
            clean[key] = entry
        self.device.characters.set_device_settings(cid, {"controls": clean})
        if active:
            self.device.show_character()          # writes the settings for the stage and starts it again
        return web.json_response({"ok": True, "saved": clean})

    async def reset_movement(self, request):
        cid = self._cid(request)
        self.device.characters.set_device_settings(cid, {"controls": {}})
        if cid == self.device.active_id():
            self.device.show_character()
        return web.json_response({"ok": True})

    async def stage_preview(self, request):
        """Move the character on the screen while its movement is being set up: hold some parameters
        for a moment ({"set": {name: value or null}}), play a gesture, or hand everything back."""
        link = self.device.stage
        body = await request.json()
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="send set, gesture or clear")
        if "set" in body:
            params = {p.get("name"): p for p in getattr(link, "param_info", [])}
            values = body["set"]
            if not isinstance(values, dict) or not values or len(values) > 8:
                raise web.HTTPBadRequest(text="set names up to 8 parameters")
            out = {}
            for name, value in values.items():
                p = params.get(name)
                if p is None:
                    raise web.HTTPBadRequest(text="the character has no parameter called %s" % name)
                if value is None:
                    out[name] = None
                    continue
                if not isinstance(value, (int, float)) or value != value:
                    raise web.HTTPBadRequest(text="%s needs a number" % name)
                lo, hi = sorted((float(p.get("min", [0])[0]), float(p.get("max", [1])[0])))
                out[name] = min(max(float(value), lo), hi)
            ease = body.get("ease", 0.3)
            ease = min(max(float(ease), 0.0), 2.0) if isinstance(ease, (int, float)) else 0.3
            link.send({"set": out, "ease": ease})
        elif "gesture" in body:
            if body["gesture"] not in getattr(link, "gestures", ()):
                raise web.HTTPBadRequest(text="this character cannot make that gesture")
            link.send({"gesture": body["gesture"]})
        elif body.get("clear"):
            link.send({"clear": True, "ease": 0.3})
        else:
            raise web.HTTPBadRequest(text="send set, gesture or clear")
        return web.json_response({"ok": True})

    async def put_persona(self, request):
        cid = self._cid(request)
        body = await request.json()
        try:
            written = None
            if "form" in body:
                # The guided form: the answers are kept, so the form can be opened again.
                form = persona.clean(body["form"])
                written = persona.build(form)
                self.device.characters.set_persona(cid, written)
                self.device.characters.set_device_settings(cid, {"persona_form": form})
            elif "persona" in body:
                self.device.characters.set_persona(cid, str(body["persona"]))
            if ("form" in body or "persona" in body) and not self.device.characters.device_settings(cid).get("temperament"):
                # A first temperament from the personality (a shy character moves less); the sliders change it.
                suggested = temperament.suggest(self.device.characters.persona(cid))
                self.device.characters.set_device_settings(cid, {"temperament": suggested})
                if cid == self.device.active_id():
                    self.device.use_character_motion(cid)
            if "voice" in body:
                self.device.characters.set_device_settings(cid, {"voice": str(body["voice"])[:200]})
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error))
        self.device.conversation = None
        return web.json_response({"ok": True, "persona": written} if written else {"ok": True})

    async def clone_voice(self, request):
        cid = self._cid(request)
        key = self.device.store.secret("elevenlabs")
        if not key:
            raise web.HTTPBadRequest(text="set an ElevenLabs key first")
        sample = await request.read()
        if not sample.startswith(b"RIFF") or len(sample) > 20 * 1024 * 1024:
            raise web.HTTPBadRequest(text="send a WAV recording of up to 20 MB")
        name = self.device.characters.manifest(cid).get("name", cid)
        try:
            voice = await clone_voice_elevenlabs(key, name, sample)
        except ProviderError as error:
            raise web.HTTPBadGateway(text=str(error))
        self.device.characters.set_device_settings(cid, {"voice": voice})
        self.device.conversation = None
        return web.json_response({"voice": voice})

    # ----- memory
    async def get_memory(self, request):
        """Everything a character remembers, for the Memory tab: the owner's notes, its memories, its
        conversations (newest first), the one going on, and its diary."""
        memory = self.device.memory(self._cid(request))
        now = time.time()
        memory.close_stale(now)               # one gone quiet is shown as ended, waiting to be summed up
        sessions = memory.sessions()
        open_session = memory.open_session()
        return web.json_response({
            "notes": memory.notes(),
            "memories": sorted(memory.memories(), key=lambda m: (-m.get("pinned", False), -m.get("importance", 3), -m.get("updated", 0))),
            "retired": [m for m in memory.memories(everything=True) if m.get("status", "active") != "active"][-100:][::-1],
            "categories": list(memory_module.CATEGORIES),
            "sessions": [dict(s, when=when(s.get("start", 0), now)) for s in reversed(sessions[-300:])],
            "session_count": len(sessions),
            "open": dict(open_session, when=when(open_session.get("start", 0), now),
                         turns_now=memory.session_turns(open_session["id"])) if open_session else None,
            "diary": list(reversed(memory.diary()[-200:])),
        })

    async def put_memory(self, request):
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("notes", ""), str):
            raise web.HTTPBadRequest(text="send the notes as text")
        self.device.memory(self._cid(request)).set_notes(body.get("notes", ""))
        return web.json_response({"ok": True})

    async def clear_memory(self, request):
        self.device.memory(self._cid(request)).clear()
        return web.json_response({"ok": True})

    async def new_conversation(self, request):
        """Start afresh: the conversation going on ends now (it is summed up as usual)."""
        cid = self._cid(request)
        closed = self.device.memory(cid).new_conversation()
        asyncio.ensure_future(self.device.keep_memory(cid))
        return web.json_response({"ok": True, "ended": closed["id"] if closed else None})

    def _number(self, request, name="id"):
        try:
            return int(request.match_info[name])
        except ValueError:
            raise web.HTTPNotFound()

    async def get_session(self, request):
        memory = self.device.memory(self._cid(request))
        return web.json_response({"turns": memory.transcript(self._number(request))})

    async def put_session(self, request):
        memory = self.device.memory(self._cid(request))
        body = await request.json()
        if not isinstance(body, dict) or not any(isinstance(body.get(k), str) and body[k].strip() for k in ("summary", "title")):
            raise web.HTTPBadRequest(text="a summary needs some words")
        if not memory.edit_session(self._number(request), title=body.get("title"), summary=body.get("summary")):
            raise web.HTTPNotFound(text="no such conversation")
        return web.json_response({"ok": True})

    async def delete_session(self, request):
        if not self.device.memory(self._cid(request)).forget_session(self._number(request)):
            raise web.HTTPNotFound(text="no such conversation")
        return web.json_response({"ok": True})

    def _memory_fields(self, body):
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="send the memory's text and category")
        fields = {}
        if "text" in body:
            fields["text"] = str(body["text"] or "")
        if body.get("category") is not None:
            if body["category"] not in memory_module.CATEGORIES:
                raise web.HTTPBadRequest(text="the category is one of: " + ", ".join(memory_module.CATEGORIES))
            fields["category"] = body["category"]
        if body.get("importance") is not None:
            try:
                fields["importance"] = max(1, min(5, int(body["importance"])))
            except (TypeError, ValueError):
                raise web.HTTPBadRequest(text="importance is 1 to 5")
        if "when" in body:
            day = str(body["when"] or "")
            if day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                raise web.HTTPBadRequest(text="a date is written 2026-11-21")
            fields["when"] = day or None
        for flag in ("pinned", "follow_up"):
            if flag in body:
                fields[flag] = bool(body[flag])
        if body.get("status") is not None:
            if body["status"] not in ("active", "retired"):
                raise web.HTTPBadRequest(text="a memory is active or retired")
            fields["status"] = body["status"]
        return fields

    async def add_memory_item(self, request):
        memory = self.device.memory(self._cid(request))
        fields = self._memory_fields(await request.json())
        entry = memory.add_memory(fields.get("text", ""), fields.get("category", "other"), fields.get("importance", 3),
                                  fields.get("when"), follow_up=fields.get("follow_up", False), source="owner",
                                  pinned=fields.get("pinned", False))
        if not entry:
            raise web.HTTPBadRequest(text="a memory needs some words")
        return web.json_response(entry)

    async def put_memory_item(self, request):
        memory = self.device.memory(self._cid(request))
        if not memory.edit_memory(self._number(request), **self._memory_fields(await request.json())):
            raise web.HTTPNotFound(text="no such memory")
        return web.json_response({"ok": True})

    async def delete_memory_item(self, request):
        if not self.device.memory(self._cid(request)).forget_memory(self._number(request)):
            raise web.HTTPNotFound(text="no such memory")
        return web.json_response({"ok": True})

    async def put_diary(self, request):
        memory = self.device.memory(self._cid(request))
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("text"), str) or not body["text"].strip():
            raise web.HTTPBadRequest(text="a diary entry needs some words (or remove it)")
        if not memory.set_diary(request.match_info["day"], body["text"]):
            raise web.HTTPNotFound(text="no diary entry for that day")
        return web.json_response({"ok": True})

    async def delete_diary(self, request):
        if not self.device.memory(self._cid(request)).set_diary(request.match_info["day"], ""):
            raise web.HTTPNotFound(text="no diary entry for that day")
        return web.json_response({"ok": True})

    # ----- talking from the console
    async def say(self, request):
        body = await request.json()
        asyncio.ensure_future(self.device.say(str(body.get("text", ""))))
        return web.json_response({"ok": True})

    async def press(self, request):
        self.device.button()
        return web.json_response({"ok": True, "state": self.device.state, "listening": self.device.listening})

    async def interrupt(self, request):
        self.device.interrupt()
        return web.json_response({"ok": True})

    # ----- Wi-Fi
    async def wifi_status(self, request):
        wifi = self.device.wifi
        if wifi is None:
            return web.json_response({"available": False})
        try:
            connected = await wifi.connected()
            networks = await wifi.networks()
            address = await wifi.address() if connected else ""
        except NetworkError as error:
            return web.json_response({"available": True, "error": str(error), "networks": []})
        return web.json_response({"available": True, "connected": connected, "address": address,
                                  "hotspot": bool(wifi.hotspot), "networks": networks})

    async def wifi_join(self, request):
        if self.device.wifi is None:
            raise web.HTTPNotFound(text="this device has no Wi-Fi control")
        body = await request.json()
        try:
            await self.device.join_wifi(str(body.get("ssid", "")), str(body.get("password", "")))
        except NetworkError as error:
            raise web.HTTPBadRequest(text=str(error))
        return web.json_response({"ok": True})

    # ----- device
    async def set_timezone(self, request):
        body = await request.json()
        try:
            await self.device.set_timezone(str(body.get("zone", "")))
        except (ValueError, RuntimeError) as error:
            raise web.HTTPBadRequest(text=str(error))
        return web.json_response({"timezone": self.device.timezone()})

    async def reset(self, request):
        body = await request.json()
        if not self.device.store.check_password(str(body.get("password", ""))):
            raise web.HTTPUnauthorized(text="the password is wrong")
        if body.get("confirm") != "RESET":
            raise web.HTTPBadRequest(text="type RESET to confirm")
        asyncio.ensure_future(self.device.factory_reset())
        return web.json_response({"ok": True})

    async def index(self, request):
        return web.FileResponse(os.path.join(STATIC, "index.html"))


def make_app(device):
    console = Console(device)
    app = web.Application(middlewares=[console.guard], client_max_size=MAX_UPLOAD)
    r = app.router
    r.add_get("/", console.index)
    r.add_get("/api/hello", console.hello)
    r.add_post("/api/setup", console.setup)
    r.add_post("/api/login", console.login)
    r.add_post("/api/logout", console.logout)
    r.add_post("/api/password", console.password)
    r.add_get("/api/status", console.status)
    r.add_get("/api/events", console.events)
    r.add_get("/api/animation", console.animation)
    r.add_get("/api/settings", console.get_settings)
    r.add_put("/api/settings", console.put_settings)
    r.add_get("/api/keys", console.get_keys)
    r.add_put("/api/keys/{name}", console.put_key)
    r.add_post("/api/test/{which}", console.test_provider)
    r.add_get("/api/models", console.models)
    r.add_post("/api/llm/find", console.find_llm)
    r.add_get("/api/voices", console.voices)
    r.add_get("/api/characters", console.list_characters)
    r.add_post("/api/characters", console.upload_character)
    r.add_post("/api/characters/{cid}/activate", console.activate)
    r.add_delete("/api/characters/{cid}", console.delete_character)
    r.add_get("/api/characters/{cid}/preview", console.preview)
    r.add_get("/api/characters/{cid}/export", console.export)
    r.add_get("/api/characters/{cid}/persona", console.get_persona)
    r.add_put("/api/characters/{cid}/persona", console.put_persona)
    r.add_post("/api/characters/{cid}/voice", console.clone_voice)
    r.add_get("/api/characters/{cid}/emotions", console.get_emotions)
    r.add_put("/api/characters/{cid}/emotions", console.put_emotions)
    r.add_get("/api/characters/{cid}/movement", console.get_movement)
    r.add_put("/api/characters/{cid}/movement", console.put_movement)
    r.add_delete("/api/characters/{cid}/movement", console.reset_movement)
    r.add_put("/api/characters/{cid}/temperament", console.put_temperament)
    r.add_get("/api/characters/{cid}/animations", console.get_animations)
    r.add_put("/api/characters/{cid}/animations", console.put_animations)
    r.add_post("/api/characters/{cid}/animations/{role}", console.add_animation)
    r.add_delete("/api/characters/{cid}/animations/{role}", console.delete_animation)
    r.add_post("/api/characters/{cid}/animations/{role}/try", console.try_animation)
    r.add_get("/api/motions", console.get_motions)
    r.add_post("/api/motions/try", console.try_motion)
    r.add_put("/api/motions/{name}", console.put_motion)
    r.add_delete("/api/motions/{name}", console.delete_motion)
    r.add_post("/api/stage/preview", console.stage_preview)
    r.add_post("/api/cards/read", console.read_card)
    r.add_get("/api/memory/{cid}", console.get_memory)
    r.add_put("/api/memory/{cid}", console.put_memory)
    r.add_delete("/api/memory/{cid}", console.clear_memory)
    r.add_post("/api/memory/{cid}/new", console.new_conversation)
    r.add_get("/api/memory/{cid}/sessions/{id}", console.get_session)
    r.add_put("/api/memory/{cid}/sessions/{id}", console.put_session)
    r.add_delete("/api/memory/{cid}/sessions/{id}", console.delete_session)
    r.add_post("/api/memory/{cid}/items", console.add_memory_item)
    r.add_put("/api/memory/{cid}/items/{id}", console.put_memory_item)
    r.add_delete("/api/memory/{cid}/items/{id}", console.delete_memory_item)
    r.add_put("/api/memory/{cid}/diary/{day}", console.put_diary)
    r.add_delete("/api/memory/{cid}/diary/{day}", console.delete_diary)
    r.add_post("/api/say", console.say)
    r.add_post("/api/button", console.press)
    r.add_post("/api/interrupt", console.interrupt)
    r.add_post("/api/timezone", console.set_timezone)
    r.add_post("/api/reset", console.reset)
    r.add_get("/api/wifi", console.wifi_status)
    r.add_post("/api/wifi", console.wifi_join)
    if os.path.isdir(STATIC):
        r.add_static("/static/", STATIC)
    return app
