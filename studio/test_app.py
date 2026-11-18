"""Tests for the Character Studio app: the page's API, made characters, and sending to a device.

Uses a stand-in part finder (the drawn test figure's labels) and a stand-in device; the rigger is real.
"""
import argparse
import importlib.util
import io
import json
import os
import tempfile
import unittest
import zipfile

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import app
from companion import package
from test_partsplit import figure_with_arms, labels_for

HAVE_RIGGER = importlib.util.find_spec("image2live2d") is not None
H = {"X-Studio": "1"}


def figure_png():
    out = io.BytesIO()
    figure_with_arms().save(out, "PNG")
    return out.getvalue()


def quick_preview(puppet):
    return b"GIF89a-stand-in"


class FakeDevice:
    """The device's login and upload, as the studio uses them."""

    def __init__(self, password="a good password"):
        self.password = password
        self.received = []
        self.app = web.Application(client_max_size=64 * 1024 * 1024)   # as the device: whole packages
        self.app.router.add_post("/api/login", self.login)
        self.app.router.add_post("/api/characters", self.upload)

    async def login(self, request):
        if request.headers.get("X-Companion") != "1":
            raise web.HTTPForbidden()
        body = await request.json()
        if body.get("password") != self.password:
            raise web.HTTPUnauthorized(text="wrong password")
        response = web.json_response({"ok": True})
        response.set_cookie("companion_session", "token-1")
        return response

    async def upload(self, request):
        if request.cookies.get("companion_session") != "token-1" or request.headers.get("X-Companion") != "1":
            raise web.HTTPUnauthorized(text="please log in")
        data = await request.read()
        self.received.append((request.query.get("replace"), data))
        return web.json_response({"id": package.open_package(io.BytesIO(data)).id})


@unittest.skipUnless(HAVE_RIGGER, "the image2live2d rigger is not installed")
class StudioTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.studio = app.Studio(cls.dir.name, label=lambda image: labels_for(image), draw_preview=quick_preview)
        cls.job = cls.studio.add_job(figure_png(), "figure.png", "Test Figure")
        cls.studio._build(cls.job)                    # the slow part, once
        cls.job.preview, cls.job.state = quick_preview(None), "done"

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    async def asyncSetUp(self):
        self.client = TestClient(TestServer(app.make_app(self.studio)))
        await self.client.start_server()
        self.studio.port = self.client.port

    async def asyncTearDown(self):
        await self.client.close()

    async def test_only_this_computer_and_the_page_itself_can_use_it(self):
        r = await self.client.get("/api/status", headers={"Host": "evil.example:%d" % self.client.port})
        self.assertEqual(r.status, 403, "another name for this computer (DNS rebinding) is refused")
        r = await self.client.post("/api/jobs?name=x", data=figure_png())
        self.assertEqual(r.status, 403, "changes need the X-Studio header")
        r = await self.client.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn("Character Studio", await r.text())

    async def test_a_made_character_is_described_and_can_be_saved(self):
        status = await (await self.client.get("/api/status")).json()
        self.assertTrue(status["finder"]["ready"])
        self.assertIn("personality", status["questions"])
        job = await (await self.client.get("/api/jobs/" + self.job.id)).json()
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["arms"], ["l", "r"])
        self.assertTrue(job["capabilities"]["blink"])
        self.assertIn("Parts found", job["steps"])
        r = await self.client.get("/api/jobs/%s/package" % self.job.id)
        self.assertIn("test-figure.char", r.headers["Content-Disposition"])
        p = package.open_package(io.BytesIO(await r.read()))
        self.assertIn("visual/live2d/model.moc3", p.files)
        self.assertEqual((await self.client.get("/api/jobs/%s/preview.gif" % self.job.id)).status, 200)
        self.assertEqual((await self.client.get("/api/jobs/nope")).status, 404)

    async def test_who_they_are_goes_into_the_package(self):
        form = {"name": "Mika", "personality": "Cheerful and teasing.", "likes": "astronomy", "greeting": "Hi there!"}
        r = await self.client.put("/api/jobs/%s/persona" % self.job.id, json={"form": form}, headers=H)
        self.assertEqual(r.status, 200, await r.text())
        p = package.open_package(io.BytesIO(self.job.data))
        self.assertEqual((p.id, p.manifest["name"]), ("mika", "Mika"))
        self.assertIn("Cheerful and teasing.", p.persona)
        self.assertIn("## Greeting", p.persona)
        r = await self.client.put("/api/jobs/%s/persona" % self.job.id, json={"form": {"name": ""}}, headers=H)
        self.assertEqual(r.status, 400)

    async def test_sending_logs_in_and_uploads_and_keeps_no_password(self):
        device = FakeDevice()
        server = TestServer(device.app)
        await server.start_server()
        try:
            address = "127.0.0.1:%d" % server.port
            r = await self.client.post("/api/jobs/%s/send" % self.job.id,
                                       json={"address": address, "password": "a good password"}, headers=H)
            self.assertEqual(r.status, 200, await r.text())
            self.assertEqual(device.received[0][0], "1", "a character sent again replaces the old one")
            r = await self.client.post("/api/jobs/%s/send" % self.job.id,
                                       json={"address": address, "password": "wrong"}, headers=H)
            self.assertEqual(r.status, 502)
            self.assertIn("did not accept that password", await r.text())
            r = await self.client.post("/api/jobs/%s/send" % self.job.id,
                                       json={"address": "http://evil/x?y", "password": "x"}, headers=H)
            self.assertIn("address looks wrong", await r.text())
            saved = json.dumps(self.studio.config())
            self.assertIn(address, saved, "the address is remembered")
            self.assertNotIn("good password", saved, "the password is not")
        finally:
            await server.close()

    async def test_an_arm_can_be_kept_still_and_the_character_made_again(self):
        r = await self.client.post("/api/jobs/%s/remake" % self.job.id, json={"still_arms": ["x"]}, headers=H)
        self.assertEqual(r.status, 400)
        r = await self.client.post("/api/jobs/%s/remake" % self.job.id, json={"still_arms": ["l"]}, headers=H)
        self.assertEqual(r.status, 200)
        await self.studio.run(self.job) if self.job.state != "done" else None
        for _ in range(600):
            job = await (await self.client.get("/api/jobs/" + self.job.id)).json()
            if job["state"] in ("done", "failed"):
                break
            await __import__("asyncio").sleep(0.1)
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(job["arms"], ["r"])
        self.assertTrue(any("as asked" in w for w in job["warnings"]))


class SetupTest(unittest.IsolatedAsyncioTestCase):
    async def test_without_the_model_the_page_asks_for_it_first(self):
        with tempfile.TemporaryDirectory() as d:
            studio = app.Studio(d)
            client = TestClient(TestServer(app.make_app(studio)))
            await client.start_server()
            studio.port = client.port
            try:
                status = await (await client.get("/api/status")).json()
                self.assertFalse(status["finder"]["ready"])
                self.assertIn("model weights", status["finder"]["missing"])
                r = await client.post("/api/jobs?name=x", data=figure_png(), headers=H)
                self.assertEqual(r.status, 409)
            finally:
                await client.close()


if __name__ == "__main__":
    unittest.main()
