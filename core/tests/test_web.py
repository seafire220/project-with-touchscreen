"""Tests for the console API: login, keys, characters, memory and talking, with stand-in providers."""
import asyncio
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from companion import package  # noqa: E402
from companion.audio import Speaker  # noqa: E402
from companion.device import Device  # noqa: E402
from companion.memory import when  # noqa: E402
from companion.web import local_address, make_app  # noqa: E402
from fakes import FakeLLM, FakeStage, FakeTTS  # noqa: E402
from test_package import good_files, manifest  # noqa: E402

H = {"X-Companion": "1"}


def fakes(which, device):
    return {"llm": FakeLLM("[happy] Nice to meet you. I'm Aria."), "tts": FakeTTS()}.get(which)


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

    async def test_choosing_the_character_drawing_relinks_the_stage(self):
        from test_package import live2d_files
        await self.login()
        files = good_files()
        files.update(live2d_files())
        self.device.characters.install(package.build(files, manifest()))
        self.device.activate("aria")
        self.assertTrue(os.path.realpath(self.device.current_puppet).endswith("model.model3.json"))
        self.stage.commands.clear()
        r = await self.client.put("/api/settings", json={"character_format": "inochi2d"}, headers=H)
        self.assertEqual(r.status, 200)
        self.assertTrue(os.path.realpath(self.device.current_puppet).endswith("puppet.inp"))
        self.assertIn({"quit": True}, self.stage.commands, "the stage restarts with the other drawing")
        r = await self.client.put("/api/settings", json={"character_format": "png"}, headers=H)
        self.assertEqual(r.status, 400)
        r = await self.client.put("/api/settings", json=["not", "an", "object"], headers=H)
        self.assertEqual(r.status, 400)

    async def test_a_zipped_live2d_model_folder_can_be_uploaded(self):
        from test_package import model_folder_zip
        await self.login()
        r = await self.client.post("/api/characters?name=Aria", data=model_folder_zip(), headers=H)
        self.assertEqual(r.status, 200, await r.text())
        self.assertEqual((await r.json())["id"], "aria")
        self.assertTrue(os.path.realpath(self.device.current_puppet).endswith("model.model3.json"),
                        "the first character is shown at once, with its Live2D-format model")
        r = await self.client.post("/api/characters", data=b"PK\x05\x06" + b"\0" * 18, headers=H)
        self.assertEqual(r.status, 400)

    async def test_turning_off_gestures_by_mood_tells_the_stage(self):
        await self.login()
        r = await self.client.put("/api/settings", json={"conversation": {"random_gestures": False}}, headers=H)
        self.assertEqual(r.status, 200)
        self.assertIn({"random_gestures": False}, self.stage.commands)
        self.assertFalse((await r.json())["conversation"]["random_gestures"])

    async def test_feelings_can_be_matched_to_a_models_own_expressions(self):
        from test_package import model_folder_zip
        await self.login()
        r = await self.client.post("/api/characters?name=Aria", data=model_folder_zip(), headers=H)
        self.assertEqual(r.status, 200)
        r = await self.client.get("/api/characters/aria/emotions")
        data = await r.json()
        self.assertEqual(data["expressions"], ["Smile"])
        self.assertEqual(data["map"], {"happy": "Smile"}, "guessed from the expression's name")
        self.assertEqual(self.device.stage.emotion_map, {"happy": "Smile"}, "the active character's map is in use")
        r = await self.client.put("/api/characters/aria/emotions", json={"map": {"happy": "", "embarrassed": "Smile"}},
                                  headers=H)
        self.assertEqual((await r.json())["map"], {"embarrassed": "Smile"})
        self.assertEqual(self.device.stage.emotion_map, {"embarrassed": "Smile"})
        for bad in ({"map": {"bored": "Smile"}}, {"map": {"happy": "Nope"}}, {"map": "Smile"}):
            r = await self.client.put("/api/characters/aria/emotions", json=bad, headers=H)
            self.assertEqual(r.status, 400, bad)

    async def test_a_persona_can_be_written_from_a_few_questions(self):
        await self.login()
        self.device.characters.install(package.build(good_files(), manifest()))
        form = {"name": "Mika", "personality": "Cheerful and teasing.", "likes": "astronomy, baking",
                "speaking": "Casual and warm.", "greeting": "Oh! You're here!"}
        r = await self.client.put("/api/characters/aria/persona", json={"form": form}, headers=H)
        self.assertEqual(r.status, 200)
        written = (await r.json())["persona"]
        self.assertIn("You are Mika", written)
        self.assertEqual(self.device.characters.persona("aria"), written)
        r = await self.client.get("/api/characters/aria/persona")
        data = await r.json()
        self.assertEqual(data["form"]["likes"], "astronomy, baking", "the answers are kept for next time")
        for bad in ({"name": ""}, {"name": "Mika", "mood": "x"}, {"name": "Mika", "story": "x" * 5000}, "Mika"):
            r = await self.client.put("/api/characters/aria/persona", json={"form": bad}, headers=H)
            self.assertEqual(r.status, 400, bad)

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

    async def test_movement_settings_are_checked_saved_and_given_to_the_stage(self):
        await self.login()
        self.device.characters.install(package.build(good_files(), manifest()))
        self.device.activate("aria")
        self.stage.param_info = [{"name": "ParamArmLA", "min": [-10, 0], "max": [10, 0], "default": [0, 0]},
                                 {"name": "ParamArmL", "min": [0, 0], "max": [30, 0], "default": [0, 0]}]
        self.stage.controls = [{"control": "arm_left", "param": "ParamArmLA", "min": -10, "max": 10, "rest": 0}]
        self.stage.gestures = ["nod", "wave"]
        m = await (await self.client.get("/api/characters/aria/movement")).json()
        self.assertTrue(m["active"] and m["ready"])
        self.assertIn({"control": "arm_left_b", "label": "Left elbow"}, m["controls"])
        self.assertEqual(m["current"][0]["param"], "ParamArmLA")
        for body, status in (({"controls": {"arm_left": {"param": "Nope"}}}, 400),
                             ({"controls": {"tail": {"param": "ParamArmL"}}}, 400),
                             ({"controls": {"arm_left": {}}}, 400), ({"controls": []}, 400)):
            r = await self.client.put("/api/characters/aria/movement", json=body, headers=H)
            self.assertEqual(r.status, status, body)
        self.stage.commands.clear()
        r = await self.client.put("/api/characters/aria/movement", headers=H,
                                  json={"controls": {"arm_left": {"param": "ParamArmL", "invert": True}, "smile": None}})
        self.assertEqual(r.status, 200, await r.text())
        with open(self.device.movement_map) as f:
            self.assertEqual(json.load(f), {"arm_left": {"param": "ParamArmL", "invert": True}, "smile": None})
        self.assertIn({"quit": True}, self.stage.commands, "the stage starts again with the settings")
        self.assertNotIn("ParamArmL", json.dumps(self.device.characters.export("aria").hex()),
                         "settings stay on the device")
        r = await self.client.delete("/api/characters/aria/movement", headers=H)
        self.assertEqual(r.status, 200)
        with open(self.device.movement_map) as f:
            self.assertEqual(json.load(f), {})

    async def test_the_movement_preview_moves_only_real_parameters_within_range(self):
        await self.login()
        self.stage.param_info = [{"name": "ParamArmLA", "min": [-10, 0], "max": [10, 0], "default": [0, 0]}]
        self.stage.gestures = ["wave"]
        self.stage.commands.clear()
        r = await self.client.post("/api/stage/preview", json={"set": {"ParamArmLA": 25}, "ease": 0.3}, headers=H)
        self.assertEqual(r.status, 200)
        self.assertEqual(self.stage.commands[-1], {"set": {"ParamArmLA": 10.0}, "ease": 0.3}, "held within its range")
        for body in ({"set": {"Nope": 1}}, {"set": {"ParamArmLA": "high"}}, {"gesture": "backflip"}, {"spin": True}):
            r = await self.client.post("/api/stage/preview", json=body, headers=H)
            self.assertEqual(r.status, 400, body)
        await self.client.post("/api/stage/preview", json={"gesture": "wave"}, headers=H)
        await self.client.post("/api/stage/preview", json={"clear": True}, headers=H)
        self.assertEqual(self.stage.commands[-2:], [{"gesture": "wave"}, {"clear": True, "ease": 0.3}])

    async def test_summaries_of_earlier_conversations_can_be_read_changed_and_forgotten(self):
        await self.login()
        self.device.characters.install(package.build(good_files(), manifest()))
        memory = self.device.memory("aria")
        old = time.time() - 40 * 86400
        memory.add_episode(4, old, "We talked about tea.")
        memory.add_episode(9, time.time(), "We planned a picnic.")
        m = await (await self.client.get("/api/memory/aria")).json()
        self.assertEqual([(e["id"], e["when"]) for e in m["episodes"]], [(9, "today"), (4, when(old))], "newest first")
        self.assertEqual(m["episode_count"], 2)
        r = await self.client.put("/api/memory/aria/episodes/4", json={"summary": "We talked about green tea."}, headers=H)
        self.assertEqual(r.status, 200)
        for path, body, status in (("4", {"summary": "  "}, 400), ("4", ["no"], 400), ("77", {"summary": "x"}, 404),
                                   ("abc", {"summary": "x"}, 404)):
            r = await self.client.put("/api/memory/aria/episodes/" + path, json=body, headers=H)
            self.assertEqual(r.status, status, path)
        r = await self.client.delete("/api/memory/aria/episodes/9")
        self.assertEqual(r.status, 403, "changes need the X-Companion header")
        r = await self.client.delete("/api/memory/aria/episodes/9", headers=H)
        self.assertEqual(r.status, 200)
        r = await self.client.delete("/api/memory/aria/episodes/9", headers=H)
        self.assertEqual(r.status, 404)
        m = await (await self.client.get("/api/memory/aria")).json()
        self.assertEqual([e["summary"] for e in m["episodes"]], ["We talked about green tea."])
        exported = await (await self.client.get("/api/characters/aria/export")).read()
        self.assertNotIn(b"green tea", exported, "summaries never leave in a package")

    async def test_a_conversation_is_summed_up_once_it_goes_quiet_however_short(self):
        self.device.characters.install(package.build(good_files(), manifest()))
        llm = FakeLLM("- Likes tea\nEPISODE: They said hello and we talked about tea.")
        self.device.provider_factory = lambda which, device: {"llm": llm, "tts": FakeTTS()}.get(which)
        memory = self.device.memory("aria")
        memory.add_turn("hello, I love tea", "Tea is lovely!")
        await self.device._maybe_update_notes("aria")
        self.assertEqual(llm.calls, [], "one turn is not enough while the conversation goes on")
        watch = asyncio.ensure_future(self.device.memory_watch(quiet=0.0, every=0.01))
        try:
            for _ in range(300):
                await asyncio.sleep(0.01)
                if memory.episodes():
                    break
        finally:
            watch.cancel()
        self.assertEqual([e["summary"] for e in memory.episodes()], ["They said hello and we talked about tea."])
        self.assertEqual((memory.notes(), memory.turns_since_update, len(llm.calls)), ("- Likes tea\n", 0, 1))

    async def test_a_failed_memory_update_is_reported_and_retried_later(self):
        self.device.characters.install(package.build(good_files(), manifest()))
        self.device.provider_factory = lambda which, device: {"llm": FakeLLM(fail="start")}.get(which)
        self.device.memory("aria").add_turn("hello", "hi")
        self.device.subscribers.add(q := asyncio.Queue())
        await self.device._maybe_update_notes("aria", force=True)
        self.assertIn("memory notes were not updated", (await asyncio.wait_for(q.get(), 1))["message"])
        self.assertGreater(self.device.memory_retry, time.time() + 600)
        self.assertEqual(self.device.memory("aria").turns_since_update, 1, "kept for the next try")
        self.device.store.update_settings({"conversation": {"memory": False}})
        self.device.memory_retry = 0
        await self.device._maybe_update_notes("aria", force=True)
        self.assertTrue(q.empty(), "with memory off, nothing is asked")

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

    async def test_speech_recognition_is_built_once_and_reused(self):
        built = []
        from companion import providers
        original = providers.build_stt
        providers.build_stt = lambda settings, store, model_dir: built.append(1) or object()
        try:
            device = Device(self.dir.name, speaker=Speaker(command=None, realtime=False), stage=FakeStage())
            first, second = device.build("stt"), device.build("stt")
            self.assertIs(first, second)
            device.store.update_settings({"stt": {"provider": "groq"}})
            device.build("stt")
            self.assertEqual(len(built), 2, "rebuilt only when the settings change")
        finally:
            providers.build_stt = original

    async def test_speaking_over_the_character_interrupts_it_only_when_allowed(self):
        import array

        class Mic:
            def __init__(self, frames):
                self.list = frames

            async def frames(self):
                for f in self.list:
                    yield f
                    await asyncio.sleep(0)
                await asyncio.sleep(3600)

        quiet = array.array("h", [0] * 320).tobytes()
        voice = array.array("h", [9000, -9000] * 160).tobytes()
        for allowed in (False, True):
            device = Device(self.dir.name, speaker=Speaker(command=None, realtime=False), stage=FakeStage(),
                            microphone=Mic([quiet] * 20 + [voice] * 10))
            device.store.update_settings({"listening": {"voice_interrupt": allowed}})
            device.listening, device.state = True, "speaking"
            calls = []
            device.interrupt = lambda: calls.append(1)
            task = asyncio.ensure_future(device.listen_loop())
            await asyncio.sleep(0.3)
            task.cancel()
            self.assertEqual(bool(calls), allowed)

    def test_only_local_addresses_are_served(self):
        for ok in ("192.168.1.20", "10.0.0.5", "127.0.0.1", "fe80::1", "172.16.4.4"):
            self.assertTrue(local_address(ok), ok)
        for bad in ("8.8.8.8", "1.1.1.1", "2606:4700::1111", "", "nonsense"):
            self.assertFalse(local_address(bad), bad)


if __name__ == "__main__":
    unittest.main()
