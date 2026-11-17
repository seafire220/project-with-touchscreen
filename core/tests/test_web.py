"""Tests for the console API: login, keys, characters, memory and talking, with stand-in providers."""
import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from companion import package  # noqa: E402
from companion.audio import Speaker  # noqa: E402
from companion.device import Device  # noqa: E402
from companion.web import local_address, make_app  # noqa: E402
from fakes import FakeLLM, FakeStage, FakeTTS  # noqa: E402
from test_package import good_files, manifest  # noqa: E402

H = {"X-Companion": "1"}


def fakes(which, device):
    return {"llm": FakeLLM("[happy] Nice to meet you. I'm Aria."), "tts": FakeTTS(), "stt": None}[which]


class WebTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.stage = FakeStage()
        self.device = Device(self.dir.name, speaker=Speaker(command=None, realtime=False), stage=self.stage,
                             provider_factory=fakes)
        self.client = TestClient(TestServer(make_app(self.device)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.dir.cleanup()

    async def login(self):
        r = await self.client.post("/api/setup", json={"password": "a good password"}, headers=H)
        self.assertEqual(r.status, 200)

    async def test_first_use_sets_a_password_once(self):
        r = await self.client.get("/api/hello")
        self.assertTrue((await r.json())["needs_setup"])
        await self.login()
        r = await self.client.post("/api/setup", json={"password": "another password"}, headers=H)
        self.assertEqual(r.status, 409)

    async def test_the_api_needs_a_login_and_the_header(self):
        r = await self.client.get("/api/status")
        self.assertEqual(r.status, 401)
        await self.login()
        r = await self.client.get("/api/status")
        self.assertEqual(r.status, 200)
        r = await self.client.put("/api/settings", json={"volume": 0.5})
        self.assertEqual(r.status, 403, "changes need the X-Companion header")

    async def test_wrong_passwords_are_slowed_and_then_locked_out(self):
        await self.login()
        await self.client.post("/api/logout", headers=H)
        codes = []
        for _ in range(6):
            r = await self.client.post("/api/login", json={"password": "nope"}, headers=H)
            codes.append(r.status)
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(codes[5], 429)

    async def test_keys_are_write_only(self):
        await self.login()
        r = await self.client.put("/api/keys/openai", json={"value": "sk-secret-value-123456"}, headers=H)
        self.assertEqual(await r.json(), {**{k: False for k in (await r.json())}, "openai": True})
        for path in ("/api/keys", "/api/settings", "/api/status"):
            text = await (await self.client.get(path)).text()
            self.assertNotIn("sk-secret", text, path)
        r = await self.client.put("/api/keys/../../etc", json={"value": "x"}, headers=H)
        self.assertIn(r.status, (400, 404))

    async def test_a_character_is_uploaded_edited_talked_to_and_removed(self):
        await self.login()
        data = package.build(good_files(), manifest())
        r = await self.client.post("/api/characters", data=data, headers=H)
        self.assertEqual((await r.json())["id"], "aria")
        self.assertEqual(os.path.realpath(self.device.current_puppet),
                         os.path.realpath(self.device.characters.file("aria", "visual/puppet.inp")))
        r = await self.client.post("/api/characters", data=b"not a package", headers=H)
        self.assertEqual(r.status, 400)
        r = await self.client.put("/api/characters/aria/persona", json={"persona": "# Aria\n\nYou are Aria.\n"}, headers=H)
        self.assertEqual(r.status, 200)

        events = []
        self.device.subscribers.add(q := asyncio.Queue())
        r = await self.client.post("/api/say", json={"text": "hello"}, headers=H)
        self.assertEqual(r.status, 200)
        while True:
            event = await asyncio.wait_for(q.get(), 5)
            events.append(event)
            if event["kind"] == "replied":
                break
        self.assertEqual(events[-1]["text"], "Nice to meet you. I'm Aria.")
        self.assertIn({"express": "happy"}, self.stage.commands)

        memory = await (await self.client.get("/api/memory/aria")).json()
        self.assertEqual(memory["history"][-1]["user"], "hello")
        await self.client.put("/api/memory/aria", json={"notes": "- Says hello a lot\n"}, headers=H)
        self.assertIn("hello a lot", (await (await self.client.get("/api/memory/aria")).json())["notes"])
        exported = await (await self.client.get("/api/characters/aria/export")).read()
        self.assertNotIn(b"hello a lot", exported, "memories never leave in a package")
        r = await self.client.delete("/api/memory/aria", headers=H)
        self.assertEqual((await (await self.client.get("/api/memory/aria")).json())["history"], [])
        r = await self.client.delete("/api/characters/aria", headers=H)
        self.assertEqual((await (await self.client.get("/api/characters")).json())["characters"], [])

    async def test_the_button_toggles_listening(self):
        await self.login()
        r = await self.client.post("/api/button", headers=H)
        self.assertTrue((await r.json())["listening"])
        self.assertEqual(self.stage.states()[-1], "listening")
        r = await self.client.post("/api/button", headers=H)
        self.assertFalse((await r.json())["listening"])

    async def test_timers_are_set_and_rung(self):
        self.device.action({"kind": "timer", "seconds": 0.05, "label": "tea"})
        self.assertIn("tea", self.device.timers)
        with open(os.path.join(self.dir.name, "timers.json")) as f:
            self.assertEqual(json.load(f)[0]["label"], "tea")
        await asyncio.sleep(0.3)
        self.assertNotIn("tea", self.device.timers)
        self.assertTrue(any(e["kind"] == "timer" and e.get("did") == "rang" for e in self.device.log))

    def test_only_local_addresses_are_served(self):
        for ok in ("192.168.1.20", "10.0.0.5", "127.0.0.1", "fe80::1", "172.16.4.4"):
            self.assertTrue(local_address(ok), ok)
        for bad in ("8.8.8.8", "1.1.1.1", "2606:4700::1111", "", "nonsense"):
            self.assertFalse(local_address(bad), bad)


if __name__ == "__main__":
    unittest.main()
