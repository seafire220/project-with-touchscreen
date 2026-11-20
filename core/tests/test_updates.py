"""Software updates: signed, checked twice, installed beside the running version, and undone when the new
version does not start (docs/32-updates.md)."""
import asyncio
import http.server
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from companion import updates  # noqa: E402
from companion.updates import UpdateError, Updates, newer, read_update, version_key  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INSTALLER = os.path.join(REPO, "device", "updater", "companion-update.py")


def load_release_tool():
    spec = importlib.util.spec_from_file_location("release_tool", os.path.join(REPO, "device", "release.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_key(folder, name="key"):
    private = os.path.join(folder, name + "-private.pem")
    public = os.path.join(folder, name + ".pem")
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", private], check=True, capture_output=True)
    with open(public, "wb") as f:
        f.write(subprocess.run(["openssl", "pkey", "-in", private, "-pubout"], check=True, capture_output=True).stdout)
    return private, public


class Workshop:
    """The owner's side: a key pair and updates made with device/release.py."""

    def __init__(self, folder):
        self.folder = folder
        self.private, self.public = make_key(folder)
        self.tool = load_release_tool()
        self.stage = os.path.join(folder, "stage-binary")
        with open(self.stage, "wb") as f:
            f.write(b"\x7fELF fake stage for tests")

    def make(self, version, notes="Fixes things.", out=None):
        out = out or os.path.join(self.folder, "dist-" + version)
        return self.tool.build(version, self.stage, self.private, out, notes=notes, any_arch=True, public_key=self.public)


def fake_app(folder, version, public_key, url=""):
    """Software installed the way an image built before updates had it: core, bin and share as folders."""
    app = os.path.join(folder, "opt")
    os.makedirs(os.path.join(app, "core", "companion"))
    with open(os.path.join(app, "core", "companion", "__main__.py"), "w") as f:
        f.write("# the old core\n")
    with open(os.path.join(app, "core", "companion", "VERSION"), "w") as f:
        f.write(version + "\n")
    os.makedirs(os.path.join(app, "bin"))
    with open(os.path.join(app, "bin", "stage"), "w") as f:
        f.write("old stage")
    os.makedirs(os.path.join(app, "share"))
    with open(public_key, "rb") as src, open(os.path.join(app, "share", "update-key.pem"), "wb") as dst:
        dst.write(src.read())
    with open(os.path.join(app, "share", "update.json"), "w") as f:
        json.dump({"url": url}, f)
    return app


class VersionTest(unittest.TestCase):
    def test_versions_compare_as_numbers(self):
        self.assertTrue(newer("2026.11.21", "2026.11.20"))
        self.assertTrue(newer("2026.12.1", "2026.11.30"))
        self.assertTrue(newer("2026.11.21.2", "2026.11.21"))
        self.assertFalse(newer("2026.11.21", "2026.11.21.0"))
        self.assertTrue(newer("2026.11.21", "0"), "a development copy takes any release")
        self.assertTrue(newer("2026.11.21", "0.20261120101010"))
        self.assertEqual(version_key("2026.11.21-rc1"), (2026, 11, 21))


class SignatureTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.shop = Workshop(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_only_a_signed_newer_update_for_this_device_is_accepted(self):
        bundle = self.shop.make("2026.12.1")
        manifest = read_update(bundle, self.shop.public, installed="2026.11.20")
        self.assertEqual((manifest["version"], manifest["notes"], manifest["product"]), ("2026.12.1", "Fixes things.", "companion"))
        _, stranger = make_key(self.dir.name, "stranger")
        with self.assertRaisesRegex(UpdateError, "not signed by this device's maker"):
            read_update(bundle, stranger, installed="2026.11.20")
        with self.assertRaisesRegex(UpdateError, "not newer"):
            read_update(bundle, self.shop.public, installed="2026.12.1")
        with self.assertRaisesRegex(UpdateError, "not newer"):
            read_update(bundle, self.shop.public, installed="2027.1.1")

    def test_a_tampered_or_strange_file_is_refused(self):
        bundle = self.shop.make("2026.12.1")
        with tarfile.open(bundle) as t:
            parts = {m.name: t.extractfile(m).read() for m in t.getmembers()}
        evil = os.path.join(self.dir.name, "evil.update")
        with tarfile.open(evil, "w:") as t:
            for name, data in parts.items():
                if name == "payload.tar.gz":
                    data = data[:-10] + b"0123456789"
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        with self.assertRaisesRegex(UpdateError, "do not match its signed description"):
            read_update(evil, self.shop.public, installed="0")
        extra = os.path.join(self.dir.name, "extra.update")
        with tarfile.open(extra, "w:") as t:
            for name, data in list(parts.items()) + [("run-me.sh", b"rm -rf /")]:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        with self.assertRaisesRegex(UpdateError, "should not"):
            read_update(extra, self.shop.public, installed="0")
        junk = os.path.join(self.dir.name, "junk.update")
        with open(junk, "wb") as f:
            f.write(b"not a tar file at all" * 100)
        with self.assertRaisesRegex(UpdateError, "not an update file"):
            read_update(junk, self.shop.public, installed="0")

    def test_the_release_tool_will_not_sign_with_a_key_devices_do_not_have(self):
        stranger_private, _ = make_key(self.dir.name, "stranger")
        with self.assertRaisesRegex(SystemExit, "does not match"):
            self.shop.tool.build("2026.12.1", self.shop.stage, stranger_private, self.dir.name, any_arch=True,
                                 public_key=self.shop.public)
        with self.assertRaisesRegex(SystemExit, "64-bit ARM"):
            self.shop.tool.build("2026.12.1", self.shop.stage, self.shop.private, self.dir.name,
                                 public_key=self.shop.public)


class FetchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.shop = Workshop(self.dir.name)
        self.bundle = self.shop.make("2026.12.1", notes="Better memory.")
        self.dist = os.path.dirname(self.bundle)
        self.served = []

        async def serve(request):
            name = request.match_info["name"]
            self.served.append(name)
            path = os.path.join(self.dist, name)
            if not os.path.isfile(path):
                raise web.HTTPNotFound()
            with open(path, "rb") as f:
                data = f.read()
            if name.endswith(".update") and getattr(self, "damage", False):
                data = data[:-1] + b"!"
            return web.Response(body=data)
        app = web.Application()
        app.router.add_get("/updates/{name}", serve)
        self.server = TestServer(app)
        await self.server.start_server()
        self.url = str(self.server.make_url("/updates/latest.json"))
        self.app = fake_app(self.dir.name, "2026.11.20", self.shop.public, self.url)
        self.data = os.path.join(self.dir.name, "data")
        self.old_version = updates.current_version
        updates.current_version = lambda: "2026.11.20"

    async def asyncTearDown(self):
        updates.current_version = self.old_version
        await self.server.close()
        self.dir.cleanup()

    async def test_the_device_finds_fetches_checks_and_asks_for_an_update(self):
        device_side = Updates(self.data, app=self.app)
        self.assertEqual(device_side.status()["online"], True)
        found = await device_side.check()
        self.assertEqual((found["version"], found["notes"]), ("2026.12.1", "Better memory."))
        self.assertTrue(found["url"].endswith("/updates/companion-2026.12.1.update"), "relative to latest.json")
        await device_side.download(found)
        status = device_side.status()
        self.assertEqual(status["ready"], {"version": "2026.12.1", "notes": "Better memory."})
        self.assertEqual(device_side.request_install(), "2026.12.1")
        with open(os.path.join(self.data, "updates", "request.json")) as f:
            request = json.load(f)
        self.assertEqual((request["do"], os.path.basename(request["bundle"])), ("install", "companion-2026.12.1.update"))
        with self.assertRaisesRegex(UpdateError, "no earlier version"):
            device_side.request_rollback()

    async def test_a_damaged_download_is_refused_and_nothing_is_kept(self):
        self.damage = True
        device_side = Updates(self.data, app=self.app)
        found = await device_side.check()
        with self.assertRaisesRegex(UpdateError, "damaged"):
            await device_side.download(found)
        self.assertIsNone(device_side.status()["ready"])
        self.assertEqual([n for n in os.listdir(os.path.join(self.data, "updates")) if n.endswith((".update", ".part"))], [])

    async def test_nothing_newer_means_up_to_date(self):
        updates.current_version = lambda: "2026.12.1"
        device_side = Updates(self.data, app=self.app)
        self.assertIsNone(await device_side.check())
        self.assertIsNotNone(device_side.status()["checked"])


class SettingsPageTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from companion.audio import Speaker
        from companion.device import Device
        from companion.web import make_app
        from fakes import FakeStage
        self.dir = tempfile.TemporaryDirectory()
        self.shop = Workshop(self.dir.name)
        self.app = fake_app(self.dir.name, "2026.11.20", self.shop.public)
        self.device = Device(os.path.join(self.dir.name, "data"), speaker=Speaker(command=None, realtime=False),
                             stage=FakeStage())
        self.device.updates = Updates(self.device.data_dir, app=self.app)
        self.old_version = updates.current_version
        updates.current_version = lambda: "2026.11.20"
        self.client = TestClient(TestServer(make_app(self.device)))
        await self.client.start_server()

    async def asyncTearDown(self):
        updates.current_version = self.old_version
        await self.client.close()
        self.dir.cleanup()

    async def test_an_update_file_is_checked_shown_and_installed_from_the_settings_page(self):
        h = {"X-Companion": "1"}
        r = await self.client.get("/api/health")
        self.assertEqual(await r.json(), {"ok": True, "version": "2026.11.20"}, "open to the installer, without a login")
        r = await self.client.get("/api/update")
        self.assertEqual(r.status, 401, "everything else needs the password")
        await self.client.post("/api/setup", json={"password": "a good password"}, headers=h)
        status = await (await self.client.get("/api/update")).json()
        self.assertEqual((status["can_update"], status["online"], status["ready"]), (True, False, None))
        with open(os.path.join(self.dir.name, "junk.update"), "wb") as f:
            f.write(b"junk")
        r = await self.client.put("/api/update/file", data=b"junk", headers=h)
        self.assertEqual(r.status, 400)
        with open(self.shop.make("2026.12.1", notes="Kinder."), "rb") as f:
            r = await self.client.put("/api/update/file", data=f.read(), headers=h)
        self.assertEqual(await r.json(), {"ok": True, "version": "2026.12.1", "notes": "Kinder."})
        status = await (await self.client.get("/api/update")).json()
        self.assertEqual(status["ready"], {"version": "2026.12.1", "notes": "Kinder."})
        r = await self.client.post("/api/update/install", headers=h)
        self.assertEqual(r.status, 200)
        request = os.path.join(self.device.data_dir, "updates", "request.json")
        for _ in range(100):
            if os.path.exists(request):
                break
            await asyncio.sleep(0.02)
        with open(request) as f:
            self.assertEqual(json.load(f)["do"], "install")
        r = await self.client.post("/api/update/rollback", headers=h)
        self.assertEqual(r.status, 400, "nothing earlier to go back to yet")
        r = await self.client.put("/api/update/settings", json={"auto_install": False}, headers=h)
        self.assertEqual((await r.json())["settings"], {"check": True, "auto_install": False})
        r = await self.client.put("/api/update/settings", json={"check": "yes"}, headers=h)
        self.assertEqual(r.status, 400)

    async def test_updates_install_themselves_only_at_night_when_nobody_is_talking(self):
        import datetime
        with open(self.shop.make("2026.12.1"), "rb") as f:
            data = f.read()
        part = os.path.join(self.device.updates.folder, "upload.part")
        with open(part, "wb") as f:
            f.write(data)
        self.device.updates.accept(part)
        with open(os.path.join(self.app, "share", "update.json"), "w") as f:
            json.dump({"url": "http://127.0.0.1:9/latest.json"}, f)
        day = datetime.datetime(2026, 11, 21, 14, 0).timestamp()
        night = datetime.datetime(2026, 11, 22, 3, 0).timestamp()

        async def step(now):
            self.device.updates._save(checked=int(now) - 60)        # checked a minute ago: no need to ask again
            return await self.device.update_step(now=now)
        self.assertEqual(await step(day), "waiting")
        self.device.last_talk = night - 600
        self.assertEqual(await step(night), "waiting", "someone talked ten minutes ago")
        self.device.last_talk = night - 3600
        self.assertEqual(await step(night), "installing")
        self.assertTrue(os.path.exists(os.path.join(self.device.updates.folder, "request.json")))
        self.device.store.update_settings({"updates": {"auto_install": False, "check": True}})
        os.remove(os.path.join(self.device.updates.folder, "request.json"))
        self.assertNotEqual(await step(night + 60), "installing")


class Health(http.server.BaseHTTPRequestHandler):
    version = ""

    def do_GET(self):
        body = json.dumps({"ok": True, "version": Health.version}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class InstallerTest(unittest.TestCase):
    """device/updater/companion-update.py, run as it is on the device, against a stand-in system."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = self.dir.name
        self.shop = Workshop(root)
        self.app = fake_app(root, "2026.11.20", self.shop.public)
        self.data = os.path.join(root, "data")
        self.etc = os.path.join(root, "etc-root")
        os.makedirs(os.path.join(self.data, "updates"))
        self.calls = os.path.join(root, "systemctl.log")
        self.systemctl = os.path.join(root, "systemctl")
        with open(self.systemctl, "w") as f:
            f.write("#!/bin/sh\necho \"$@\" >> %s\ncase \"$1\" in is-active) echo active;; show) echo 0;; esac\n" % self.calls)
        os.chmod(self.systemctl, 0o755)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Health)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.dir.cleanup()

    def run_installer(self, request):
        with open(os.path.join(self.data, "updates", "request.json"), "w") as f:
            json.dump(request, f)
        env = dict(os.environ, COMPANION_APP=self.app, COMPANION_DATA=self.data, COMPANION_ETC=self.etc,
                   COMPANION_SYSTEMCTL=self.systemctl, COMPANION_HEALTH_WAIT="3", COMPANION_STAGE_WATCH="0",
                   COMPANION_HEALTH="http://127.0.0.1:%d/api/health" % self.server.server_address[1])
        done = subprocess.run([sys.executable, INSTALLER], env=env, capture_output=True, text=True, timeout=120)
        with open(os.path.join(self.data, "updates", "status.json")) as f:
            return done.returncode, json.load(f)

    def bundle(self, version):
        built = self.shop.make(version)
        target = os.path.join(self.data, "updates", os.path.basename(built))
        os.replace(built, target)
        return target

    def where(self, name):
        return os.readlink(os.path.join(self.app, name))

    def test_an_update_is_installed_beside_the_old_one_and_the_device_switches_to_it(self):
        bundle = self.bundle("2026.12.1")
        Health.version = "2026.12.1"
        code, status = self.run_installer({"do": "install", "bundle": bundle})
        self.assertEqual((code, status["state"], status["version"]), (0, "installed", "2026.12.1"), status)
        self.assertEqual((self.where("current"), self.where("previous")), ("releases/2026.12.1", "releases/2026.11.20"))
        self.assertEqual(self.where("core"), "current/core")
        with open(os.path.join(self.app, "core", "companion", "VERSION")) as f:
            self.assertEqual(f.read().strip(), "2026.12.1")
        self.assertTrue(os.path.isfile(os.path.join(self.app, "core", "companion", "memory.py")), "the new core")
        self.assertTrue(os.access(os.path.join(self.app, "bin", "stage"), os.X_OK))
        self.assertTrue(os.path.isfile(os.path.join(self.app, "share", "vrma", "idle.vrma")))
        self.assertTrue(os.path.isfile(os.path.join(self.etc, "etc", "systemd", "system", "companion-update.path")))
        self.assertTrue(os.path.isfile(os.path.join(self.app, "updater", "companion-update.py")))
        self.assertFalse(os.path.exists(bundle), "the update file is removed once installed")
        with open(self.calls) as f:
            calls = f.read()
        self.assertIn("daemon-reload", calls)
        self.assertIn("restart companion-core companion-stage", calls)
        self.assertFalse(os.path.exists(os.path.join(self.data, "updates", "request.json")))

        # Going back, on the owner's request.
        Health.version = "2026.11.20"
        code, status = self.run_installer({"do": "rollback"})
        self.assertEqual((code, status["state"]), (0, "installed"), status)
        self.assertEqual((self.where("current"), self.where("previous")), ("releases/2026.11.20", "releases/2026.12.1"))

    def test_a_version_that_does_not_start_is_undone(self):
        bundle = self.bundle("2026.12.1")
        Health.version = "2026.11.20"                  # the old version still answers: the new one never came up
        code, status = self.run_installer({"do": "install", "bundle": bundle})
        self.assertEqual((code, status["state"]), (1, "rolled back"), status)
        self.assertIn("went back to 2026.11.20", status["message"])
        self.assertEqual(self.where("current"), "releases/2026.11.20")
        with open(os.path.join(self.app, "core", "companion", "VERSION")) as f:
            self.assertEqual(f.read().strip(), "2026.11.20")

    def test_an_update_cut_short_by_the_power_is_finished_or_undone_at_start(self):
        bundle = self.bundle("2026.12.1")
        Health.version = "2026.12.1"
        self.run_installer({"do": "install", "bundle": bundle})
        status_path = os.path.join(self.data, "updates", "status.json")
        old_release = os.path.realpath(os.path.join(self.app, "releases", "2026.11.20"))

        def power_cut(**status):
            with open(status_path, "w") as f:
                json.dump(dict({"state": "installing", "version": "2026.12.1", "previous": "2026.11.20",
                                "previous_release": old_release}, **status), f)

        def boot():
            env = dict(os.environ, COMPANION_APP=self.app, COMPANION_DATA=self.data, COMPANION_ETC=self.etc,
                       COMPANION_SYSTEMCTL=self.systemctl, COMPANION_HEALTH_WAIT="3", COMPANION_STAGE_WATCH="0",
                       COMPANION_HEALTH="http://127.0.0.1:%d/api/health" % self.server.server_address[1])
            subprocess.run([sys.executable, INSTALLER, "--boot"], env=env, capture_output=True, timeout=120)
            with open(status_path) as f:
                return json.load(f)
        power_cut()                                  # switched to the new version, then the power went
        self.assertEqual(boot()["state"], "installed", "it answers: the update is finished")
        power_cut()
        Health.version = "2026.11.20"                # switched, but the new version does not answer
        self.assertEqual(boot()["state"], "rolled back")
        self.assertEqual(self.where("current"), "releases/2026.11.20")
        power_cut()                                  # the power went before the switch
        status = boot()
        self.assertEqual(status["state"], "failed")
        self.assertIn("cut short", status["message"])
        os.remove(status_path)
        self.assertEqual(subprocess.run([sys.executable, INSTALLER, "--boot"], capture_output=True,
                                        env=dict(os.environ, COMPANION_APP=self.app, COMPANION_DATA=self.data)).returncode, 0,
                         "nothing to do on an ordinary start")

    def test_the_installer_checks_the_signature_itself(self):
        bundle = self.bundle("2026.12.1")
        _, stranger = make_key(self.dir.name, "stranger")
        with open(stranger, "rb") as src, open(os.path.join(self.app, "share", "update-key.pem"), "wb") as dst:
            dst.write(src.read())
        code, status = self.run_installer({"do": "install", "bundle": bundle})
        self.assertEqual((code, status["state"]), (1, "failed"))
        self.assertIn("not signed", status["message"])
        self.assertFalse(os.path.islink(os.path.join(self.app, "current")), "nothing was changed")
        elsewhere = os.path.join(self.dir.name, "companion-2026.12.1.update")
        os.replace(bundle, elsewhere)
        code, status = self.run_installer({"do": "install", "bundle": elsewhere})
        self.assertIn("not where updates are kept", status["message"])


if __name__ == "__main__":
    unittest.main()
