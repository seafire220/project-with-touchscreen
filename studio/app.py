#!/usr/bin/env python3
"""Character Studio: make a character from a picture on this computer, then send it to the device.

    python studio/app.py [--port 8770] [--data ~/.character-studio] [--no-browser]

Opens a page in the browser. Drop a picture in: the studio finds the body
parts, cuts them into layers, rigs them and draws a preview of the character
moving. Check what it can do, keep an arm still if it moved wrongly, say who
the character is, then send it to the device over the home network (with the
device's settings-page password) or save the .char file.

Everything runs on this computer, and nothing is sent anywhere but to your
own device. The part-finding model is downloaded once, on first use (about
1.3 GB, from its authors' pages on GitHub and Hugging Face).

The page is served to this computer only (127.0.0.1). Changes need the
header `X-Studio: 1`, which another web site cannot add, and the Host header
must name this computer, so a web page elsewhere cannot use the studio. The
device password is used for the one upload and never kept.
"""
import argparse
import asyncio
import functools
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile

import numpy as np
from aiohttp import ClientError, ClientSession, ClientTimeout, CookieJar, web
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "core"))

import make_character  # noqa: E402
import preview  # noqa: E402
from companion import cards, package, persona  # noqa: E402

STATIC = os.path.join(HERE, "app")
MAX_PICTURE = 30 * 1024 * 1024
SEE_THROUGH_COMMIT = "fc4440db7c076518e313f378e28b1504e9886a95"
SEE_THROUGH_ZIP = "https://github.com/shitagaki-lab/see-through/archive/%s.zip" % SEE_THROUGH_COMMIT
SEE_THROUGH_GIT = "https://github.com/shitagaki-lab/see-through"
WEIGHTS_URL = "https://huggingface.co/24yearsold/l2d_sam_iter2/resolve/main/checkpoint-18000.pt"
WEIGHTS_SIZE = 1_340_000_000            # about; for the progress bar until the server says
ADDRESS = re.compile(r"^(\[[0-9a-fA-F:.]+\]|[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)(:\d{1,5})?$")
SIDES = {"l": "left", "r": "right"}


class Job:
    """One character being made, and everything the page shows about it."""

    def __init__(self, folder, name, filename):
        self.id = secrets.token_hex(6)
        self.folder = folder
        self.name = name
        self.filename = filename
        self.state = "waiting"           # waiting, working, done, failed
        self.steps = []
        self.error = None
        self.report = None
        self.data = None                 # the package
        self.preview = None              # GIF bytes
        self.still = None                # PNG bytes
        self.still_arms = set()
        self.form = {"name": name}
        self.card = None                 # (persona text, greeting, card's name) when the picture is a character card
        self.created = time.time()

    def summary(self):
        out = {"id": self.id, "name": self.name, "state": self.state, "steps": self.steps, "error": self.error,
               "has_preview": self.preview is not None, "has_package": self.data is not None,
               "still_arms": sorted(self.still_arms), "form": self.form}
        if self.card:
            out["card"] = {"name": self.card[2], "greeting": self.card[1]}
        if self.report:
            out["warnings"] = self.report.get("warnings", [])
            out["capabilities"] = self.report.get("capabilities", {})
            arms = (self.report.get("refine") or {}).get("arms")
            out["arms"] = sorted(arms) if isinstance(arms, dict) else []
        if self.data:
            out["size_mb"] = round(len(self.data) / 1e6, 1)
        return out


class Studio:
    def __init__(self, data_dir, port=8770, label=None, make=None, draw_preview=None):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        # Characters are kept for one session; earlier sessions' pictures and work files go.
        shutil.rmtree(os.path.join(data_dir, "jobs"), ignore_errors=True)
        self.port = port
        self.jobs = {}
        self.order = []
        self._label = label                       # tests pass a stand-in part finder
        self._make = make or make_character.make
        self._preview = draw_preview or preview.preview_gif
        self._model = None
        self._model_lock = threading.Lock()
        self._work = asyncio.Lock()               # one character at a time
        self.setup = {"state": "idle", "message": "", "done": 0, "total": 0}

    # ----- settings and the part-finding model
    @property
    def config_path(self):
        return os.path.join(self.data_dir, "config.json")

    def config(self):
        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_config(self, **changes):
        data = self.config()
        data.update(changes)
        tmp = self.config_path + ".new"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.config_path)

    def finder(self):
        """Whether the part-finding model can run here, and if not, what is missing."""
        if self._label is not None:
            return {"ready": True, "missing": []}
        cfg = self.config()
        missing = []
        if not (cfg.get("see_through") and os.path.isdir(cfg["see_through"])):
            missing.append("model code")
        if not (cfg.get("weights") and os.path.isfile(cfg["weights"])):
            missing.append("model weights")
        if importlib.util.find_spec("torch") is None:      # (importing it takes seconds)
            missing.append("PyTorch")
        return {"ready": not missing, "missing": missing}

    def label(self, image):
        """The body-part masks for a picture."""
        if self._label is not None:
            return self._label(image)
        import parts_model
        import torch
        with self._model_lock:
            if self._model is None:
                cfg = self.config()
                device = parts_model.pick_device("auto", torch)
                self._model = parts_model.load_model(cfg["see_through"], cfg["weights"], device)
            return parts_model.label(self._model, image)

    async def download_model(self):
        """Fetch the model's code (a zip of the pinned commit) and weights into the studio's folder."""
        models = os.path.join(self.data_dir, "models")
        os.makedirs(models, exist_ok=True)
        self.setup = {"state": "running", "message": "Downloading the model's code", "done": 0, "total": 0}
        try:
            async with ClientSession(timeout=ClientTimeout(total=None, sock_read=120), trust_env=True) as session:
                target = os.path.join(models, "see-through")
                if os.path.isdir(target):
                    shutil.rmtree(target)
                try:
                    code = os.path.join(models, "see-through.zip")
                    await self._fetch(session, SEE_THROUGH_ZIP, code, 0)
                    with zipfile.ZipFile(code) as z:
                        root = z.namelist()[0].split("/")[0]
                        z.extractall(models)
                    os.replace(os.path.join(models, root), target)
                    os.remove(code)
                except (ClientError, zipfile.BadZipFile, IndexError):
                    if shutil.which("git") is None:
                        raise
                    self.setup.update(message="Downloading the model's code (with git)", done=0, total=0)
                    await git_fetch(SEE_THROUGH_GIT, SEE_THROUGH_COMMIT, target)
                self.save_config(see_through=target)
                self.setup.update(message="Downloading the model's weights (about 1.3 GB)")
                weights = os.path.join(models, "checkpoint-18000.pt")
                if not os.path.isfile(weights):
                    await self._fetch(session, WEIGHTS_URL, weights, WEIGHTS_SIZE)
                self.save_config(weights=weights)
            self.setup = {"state": "done", "message": "The part-finding model is ready", "done": 0, "total": 0}
        except (ClientError, OSError, zipfile.BadZipFile, asyncio.TimeoutError, IndexError) as error:
            self.setup = {"state": "failed", "message": "The download failed (%s). Check the internet connection "
                          "and try again." % type(error).__name__, "done": 0, "total": 0}

    async def _fetch(self, session, url, path, expected):
        partial = path + ".part"
        async with session.get(url) as response:
            if response.status != 200:
                raise ClientError("HTTP %d" % response.status)
            self.setup.update(done=0, total=response.content_length or expected)
            with open(partial, "wb") as f:
                async for chunk in response.content.iter_chunked(1 << 20):
                    f.write(chunk)
                    self.setup["done"] += len(chunk)
        os.replace(partial, path)

    # ----- making characters
    def add_job(self, picture, filename, name):
        name = " ".join((name or "").split())[:60]
        if not name:
            raise ValueError("give the character a name")
        try:
            with Image.open(io.BytesIO(picture)) as im:
                im.verify()
        except Exception:
            raise ValueError("this file is not a picture the studio can read (PNG, JPEG or WebP)")
        folder = tempfile.mkdtemp(prefix="job-", dir=self._jobs_dir())
        job = Job(folder, name, os.path.basename(filename or "picture.png"))
        try:                                         # a character card: the picture and who they are together
            card = cards.read_card(picture)
            text, greeting = cards.to_persona(card)
            if not package.contains_secret(text):
                job.card = (text, greeting, card["name"])
        except cards.CardError:
            pass
        with open(os.path.join(folder, "picture.png"), "wb") as f:
            f.write(picture)
        self.jobs[job.id] = job
        self.order.insert(0, job.id)
        return job

    def _jobs_dir(self):
        path = os.path.join(self.data_dir, "jobs")
        os.makedirs(path, exist_ok=True)
        return path

    async def run(self, job):
        async with self._work:
            job.state, job.error = "working", None
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, functools.partial(self._build, job))
                job.steps.append("Drawing a preview of the character moving")
                puppet = zipfile.ZipFile(io.BytesIO(job.data)).read("visual/puppet.inp")
                job.preview = await loop.run_in_executor(None, functools.partial(self._preview, puppet))
                job.steps.append("Ready")
                job.state = "done"
            except Exception as error:                      # shown to the owner on the page
                job.state = "failed"
                job.error = str(error) or type(error).__name__

    def _build(self, job):
        picture = os.path.join(job.folder, "picture.png")
        labels = os.path.join(job.folder, "labels.npz")
        if not os.path.exists(labels):
            job.steps.append("Finding the character's parts (the slowest step without a graphics card)")
            with Image.open(picture) as im:
                im.load()
                masks = self.label(im)
            np.savez_compressed(labels, masks=masks)
        args = argparse.Namespace(labels=labels, see_through=None, weights=None, device="auto",
                                  persona=None, author="", live2d=True, still_arms=set(job.still_arms))
        work = tempfile.mkdtemp(prefix="work-", dir=job.folder)
        try:
            data, report = self._make(picture, job.name, args, work, progress=lambda m: job.steps.append(_say(m)))
        finally:
            shutil.rmtree(work, ignore_errors=True)
        job.report = report
        job.data = data
        job.still = zipfile.ZipFile(io.BytesIO(data)).read("preview.png")
        if job.form.get("personality"):              # a remake keeps the personality written so far
            job.data = with_persona(job.data, job.form)
        elif job.card:
            job.data = with_persona_text(job.data, job.card[0], job.name)
            job.steps.append("Who they are taken from the character card")

    # ----- sending
    async def send(self, job, address, password):
        """Log in to the device's settings page and add (or update) the character there."""
        if not ADDRESS.match(address or ""):
            raise ValueError("the device's address looks wrong (for example: companion.local or 192.168.1.20)")
        base = "http://%s" % address
        headers = {"X-Companion": "1"}
        try:
            async with ClientSession(cookie_jar=CookieJar(unsafe=True), timeout=ClientTimeout(total=120)) as s:
                async with s.post(base + "/api/login", json={"password": password}, headers=headers) as r:
                    if r.status == 401:
                        raise ValueError("the device did not accept that password")
                    if r.status == 429:
                        raise ValueError(await r.text())
                    if r.status == 403:
                        raise ValueError("the device only accepts characters from its own home network")
                    if r.status != 200:
                        raise ValueError("the device answered %d: %s" % (r.status, (await r.text())[:200]))
                async with s.post(base + "/api/characters?replace=1", data=io.BytesIO(job.data),
                                  headers=dict(headers, **{"Content-Type": "application/octet-stream"})) as r:
                    text = await r.text()
                    if r.status != 200:
                        raise ValueError("the device refused the character: %s" % text[:300])
                    return json.loads(text).get("id")
        except (ClientError, asyncio.TimeoutError, OSError) as error:
            raise ValueError("could not reach the device at %s (%s). Is it on, and on this network?"
                             % (address, type(error).__name__))


async def git_fetch(url, commit, target):
    """One commit of a repository, without its history (when its zip cannot be downloaded)."""
    os.makedirs(target)
    for args in (["init", "-q"], ["remote", "add", "origin", url], ["fetch", "-q", "--depth", "1", "origin", commit],
                 ["checkout", "-q", "FETCH_HEAD"]):
        process = await asyncio.create_subprocess_exec("git", "-C", target, *args, stdout=asyncio.subprocess.DEVNULL,
                                                       stderr=asyncio.subprocess.PIPE)
        _, err = await process.communicate()
        if process.returncode != 0:
            shutil.rmtree(target, ignore_errors=True)
            raise OSError("git %s failed: %s" % (args[0], err.decode(errors="replace").strip()[-200:]))


def _say(message):
    """The maker's step messages, in the page's words."""
    if message.startswith("parts read from"):
        return "Parts found"
    return message[0].upper() + message[1:] if message else message


def with_persona(data, form):
    """The package with a persona written from the form, under the form's name."""
    return with_persona_text(data, persona.build(form), form["name"].strip())


def with_persona_text(data, text, name):
    """The package with the given persona, under the given name."""
    old = package.open_package(io.BytesIO(data))
    files = {k: v for k, v in old.files.items() if k != "manifest.json"}
    files["persona.md"] = text
    manifest = dict(old.manifest, name=name, id=package.slug(name))
    return package.build(files, manifest)


# --------------------------------------------------------------------------------------------------
# The web page and its API
# --------------------------------------------------------------------------------------------------

def make_app(studio):
    @web.middleware
    async def guard(request, handler):
        if request.host not in ("127.0.0.1:%d" % studio.port, "localhost:%d" % studio.port):
            raise web.HTTPForbidden(text="the studio only answers on this computer")
        if request.method not in ("GET", "HEAD") and request.headers.get("X-Studio") != "1":
            raise web.HTTPForbidden(text="missing X-Studio header")
        response = await handler(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy",
                                    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'")
        return response

    def job_of(request):
        job = studio.jobs.get(request.match_info["job"])
        if job is None:
            raise web.HTTPNotFound(text="no such character")
        return job

    async def index(request):
        return web.FileResponse(os.path.join(STATIC, "index.html"))

    async def status(request):
        return web.json_response({"finder": studio.finder(), "setup": studio.setup,
                                  "questions": list(persona.NAMES),
                                  "jobs": [studio.jobs[i].summary() for i in studio.order]})

    async def setup(request):
        if studio.setup["state"] != "running" and not studio.finder()["ready"]:
            asyncio.ensure_future(studio.download_model())
        return web.json_response(studio.setup)

    async def new_job(request):
        if not studio.finder()["ready"]:
            raise web.HTTPConflict(text="set up the part-finding model first")
        picture = await request.read()
        if not picture:
            raise web.HTTPBadRequest(text="send a picture")
        try:
            job = studio.add_job(picture, request.query.get("file"), request.query.get("name"))
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error))
        asyncio.ensure_future(studio.run(job))
        return web.json_response(job.summary())

    async def get_job(request):
        return web.json_response(job_of(request).summary())

    async def job_preview(request):
        job = job_of(request)
        if job.preview is None:
            raise web.HTTPNotFound(text="no preview yet")
        return web.Response(body=job.preview, content_type="image/gif")

    async def job_still(request):
        job = job_of(request)
        if job.still is None:
            raise web.HTTPNotFound(text="no picture yet")
        return web.Response(body=job.still, content_type="image/png")

    async def remake(request):
        job = job_of(request)
        if job.state == "working":
            raise web.HTTPConflict(text="the character is still being made")
        body = await request.json()
        still = set(body.get("still_arms") or []) if isinstance(body, dict) else None
        if still is None or not still <= set(SIDES):
            raise web.HTTPBadRequest(text="still_arms lists 'l' and/or 'r'")
        job.still_arms = still
        job.steps, job.preview = [], None
        asyncio.ensure_future(studio.run(job))
        return web.json_response(job.summary())

    async def put_persona(request):
        job = job_of(request)
        if job.data is None:
            raise web.HTTPConflict(text="the character is not made yet")
        body = await request.json()
        form = body.get("form") if isinstance(body, dict) else None
        try:
            job.data = with_persona(job.data, form)
            job.form = persona.clean(form)
        except (ValueError, TypeError, package.PackageError) as error:
            raise web.HTTPBadRequest(text=str(error))
        job.name = job.form["name"]
        return web.json_response(job.summary())

    async def download(request):
        job = job_of(request)
        if job.data is None:
            raise web.HTTPNotFound(text="the character is not made yet")
        name = package.slug(job.name) + ".char"
        return web.Response(body=job.data, content_type="application/zip",
                            headers={"Content-Disposition": 'attachment; filename="%s"' % name})

    async def send(request):
        job = job_of(request)
        if job.data is None:
            raise web.HTTPConflict(text="the character is not made yet")
        body = await request.json()
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="send an address and a password")
        address = str(body.get("address", "")).strip()
        try:
            cid = await studio.send(job, address, str(body.get("password", "")))
        except ValueError as error:
            raise web.HTTPBadGateway(text=str(error))
        studio.save_config(device_address=address)
        return web.json_response({"ok": True, "id": cid})

    async def peek(request):
        """The character card's name, if the chosen picture is one (to fill in the name)."""
        try:
            return web.json_response({"card": cards.read_card(await request.read())["name"]})
        except cards.CardError:
            return web.json_response({"card": None})

    async def last_address(request):
        return web.json_response({"address": studio.config().get("device_address", "companion.local")})

    app = web.Application(middlewares=[guard], client_max_size=MAX_PICTURE)
    r = app.router
    r.add_get("/", index)
    r.add_static("/static", STATIC)
    r.add_get("/api/status", status)
    r.add_post("/api/setup", setup)
    r.add_get("/api/device", last_address)
    r.add_post("/api/peek", peek)
    r.add_post("/api/jobs", new_job)
    r.add_get("/api/jobs/{job}", get_job)
    r.add_get("/api/jobs/{job}/preview.gif", job_preview)
    r.add_get("/api/jobs/{job}/still.png", job_still)
    r.add_post("/api/jobs/{job}/remake", remake)
    r.add_put("/api/jobs/{job}/persona", put_persona)
    r.add_get("/api/jobs/{job}/package", download)
    r.add_post("/api/jobs/{job}/send", send)
    return app


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--data", default=os.path.join(os.path.expanduser("~"), ".character-studio"))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv[1:])
    studio = Studio(args.data, args.port)
    url = "http://127.0.0.1:%d/" % args.port
    print("Character Studio is at %s (close this window to stop it)" % url, flush=True)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    web.run_app(make_app(studio), host="127.0.0.1", port=args.port, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
