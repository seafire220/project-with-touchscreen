"""The web console's server: a password-protected API on the home network.

Rules:
- Only addresses on the local network are served.
- A password is set on first use; after that every API call needs a login.
- Keys can be set or cleared, never read back.
- Requests that change anything must carry the header `X-Companion: 1`,
  which a web page on another site cannot add, so it cannot act for you.
"""
import asyncio
import ipaddress
import json
import os
import secrets
import time

from aiohttp import web

from . import package
from .network import NetworkError
from .providers import ProviderError, clone_voice_elevenlabs

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
        try:
            merged = self.device.store.update_settings(await request.json())
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error))
        self.device.conversation = None
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

    # ----- characters
    async def list_characters(self, request):
        return web.json_response({"active": self.device.active_id(), "characters": self.device.characters.list()})

    async def upload_character(self, request):
        data = await request.read()
        replace = request.query.get("replace") == "1"
        try:
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
        return web.json_response({"persona": self.device.characters.persona(cid),
                                  "device": self.device.characters.device_settings(cid)})

    async def put_persona(self, request):
        cid = self._cid(request)
        body = await request.json()
        try:
            if "persona" in body:
                self.device.characters.set_persona(cid, str(body["persona"]))
            if "voice" in body:
                self.device.characters.set_device_settings(cid, {"voice": str(body["voice"])[:200]})
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error))
        self.device.conversation = None
        return web.json_response({"ok": True})

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
        memory = self.device.memory(self._cid(request))
        return web.json_response({"notes": memory.notes(), "history": memory.history()[-100:]})

    async def put_memory(self, request):
        body = await request.json()
        self.device.memory(self._cid(request)).set_notes(str(body.get("notes", "")))
        return web.json_response({"ok": True})

    async def clear_memory(self, request):
        self.device.memory(self._cid(request)).clear()
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
    r.add_get("/api/settings", console.get_settings)
    r.add_put("/api/settings", console.put_settings)
    r.add_get("/api/keys", console.get_keys)
    r.add_put("/api/keys/{name}", console.put_key)
    r.add_post("/api/test/{which}", console.test_provider)
    r.add_get("/api/models", console.models)
    r.add_get("/api/characters", console.list_characters)
    r.add_post("/api/characters", console.upload_character)
    r.add_post("/api/characters/{cid}/activate", console.activate)
    r.add_delete("/api/characters/{cid}", console.delete_character)
    r.add_get("/api/characters/{cid}/preview", console.preview)
    r.add_get("/api/characters/{cid}/export", console.export)
    r.add_get("/api/characters/{cid}/persona", console.get_persona)
    r.add_put("/api/characters/{cid}/persona", console.put_persona)
    r.add_post("/api/characters/{cid}/voice", console.clone_voice)
    r.add_get("/api/memory/{cid}", console.get_memory)
    r.add_put("/api/memory/{cid}", console.put_memory)
    r.add_delete("/api/memory/{cid}", console.clear_memory)
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
