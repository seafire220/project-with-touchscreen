"""Captions, the microphone off, the screen at night and family-safe mode (docs/28-user-guide.md)."""
import array
import asyncio
import datetime
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from companion import device as device_module, family, package  # noqa: E402
from companion.audio import Speaker  # noqa: E402
from companion.backlight import Backlight  # noqa: E402
from companion.conversation import Conversation, system_prompt  # noqa: E402
from companion.device import Device  # noqa: E402
from companion.memory import Memory  # noqa: E402
from companion.overlays import caption_pages  # noqa: E402
from companion.web import make_app  # noqa: E402
from fakes import FakeLLM, FakeStage, FakeTTS  # noqa: E402
from test_package import good_files, manifest  # noqa: E402

VOICE = array.array("h", [9000, -9000] * 160).tobytes()


def overlay_commands(stage, slot=None):
    return [c["overlay"] for c in stage.commands if isinstance(c, dict) and "overlay" in c
            and (slot is None or c["overlay"]["slot"] == slot)]


def screen_commands(stage):
    return [c["screen"] for c in stage.commands if isinstance(c, dict) and "screen" in c]


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.llm = FakeLLM("Welcome home! Your driving test went well, I hope?")
        self.stage = FakeStage()
        self.device = Device(self.dir.name, speaker=Speaker(command=None, realtime=False), stage=self.stage,
                             provider_factory=lambda which, d: {"llm": self.llm, "tts": FakeTTS()}.get(which))
        self.device.characters.install(package.build(good_files(), manifest()))
        self.restarted = []

        async def no_restart():
            self.restarted.append(1)
        self.device.setup_reset = no_restart

    async def asyncTearDown(self):
        self.dir.cleanup()


class CaptionTest(Base):
    async def test_what_it_says_is_written_on_the_screen_as_it_says_it(self):
        reply = await self.device.say("hello")
        self.assertIsNone(reply.error)
        self.assertEqual(overlay_commands(self.stage), [], "captions are off unless turned on")
        self.device.store.update_settings({"captions": {"on": True, "heard": True}})
        self.device.conversation = None
        await self.device.say("hello again")
        heard = overlay_commands(self.stage, "heard")
        self.assertEqual((heard[0]["anchor"], heard[0]["image"].startswith("heard-")), ("top", True))
        shown = [c for c in overlay_commands(self.stage, "caption") if c["image"]]
        self.assertEqual(len(shown), 2, "one picture for each of the two sentences")
        self.assertEqual(shown[0]["anchor"], "bottom")
        for c in shown:
            self.assertTrue(os.path.isfile(os.path.join(self.device.overlays.folder, c["image"])) or
                            c["image"] not in self.device.overlays._kept["caption"], "pictures go in the overlay folder")
        self.assertIn("caption", self.device.overlays._hide, "it goes a moment after the character stops")
        self.device.overlays.hide("caption")
        self.assertEqual(overlay_commands(self.stage, "caption")[-1], {"slot": "caption", "image": None})

    def test_a_long_sentence_is_shown_in_pages_of_three_lines(self):
        pages, shares = caption_pages("word " * 60, (720, 1280))
        self.assertGreater(len(pages), 1)
        self.assertAlmostEqual(sum(shares), 1.0)
        large, _ = caption_pages("word " * 60, (720, 1280), size="large")
        self.assertGreater(len(large), len(pages), "large captions hold fewer words")


class FamilySafeTest(Base):
    def test_the_rules_come_before_the_character_and_end_the_instructions(self):
        plain = system_prompt("You are Rex, a pirate who swears a lot.", "They like boats.")
        safe = system_prompt("You are Rex, a pirate who swears a lot.", "They like boats.", family_safe=True)
        self.assertNotIn("Family-safe", plain)
        self.assertLess(safe.index("Rex"), safe.index("Family-safe mode is on"))
        self.assertTrue(safe.rstrip().endswith(family.REMINDER))

    def test_strong_swearing_is_taken_out_of_what_is_said(self):
        self.assertEqual(family.soften("Well, damn, that was a shitty day!"), "Well, that was a day!")
        self.assertEqual(family.soften("What the fuck."), "What the.")
        for clean in ("Scunthorpe and Essex are places.", "The class assessment went well.", "Cocktail sauce"):
            self.assertEqual(family.soften(clean), clean)

    async def test_replies_and_memory_are_given_the_rules(self):
        self.device.store.update_settings({"family_safe": {"on": True}})
        self.llm.reply = "Oh damn, that is a shitty thing to happen."
        reply = await self.device.say("my bike broke")
        self.assertIn("Family-safe mode is on", self.llm.calls[0][0])
        self.assertEqual(" ".join(reply.spoken), "Oh, that is a thing to happen.")
        asked = []

        class Recorder:
            async def stream(self, system, messages):
                asked.append(system)
                yield "ok"
        memory = Memory(os.path.join(self.dir.name, "m"))
        await memory.process(Recorder(), rules=family.MEMORY_RULE)
        await memory._ask(Recorder(), "summarise")
        self.assertTrue(asked[-1].endswith(family.MEMORY_RULE), "summaries, memories and the diary get the rule")
        await memory.process(Recorder())
        await memory._ask(Recorder(), "summarise")
        self.assertNotIn(family.MEMORY_RULE, asked[-1])

    async def test_turning_it_off_needs_the_password_again(self):
        client = TestClient(TestServer(make_app(self.device)))
        await client.start_server()
        try:
            h = {"X-Companion": "1"}
            await client.post("/api/setup", json={"password": "a good password"}, headers=h)
            r = await client.post("/api/family-safe", json={"on": True}, headers=h)
            self.assertEqual((r.status, await r.json()), (200, {"on": True}))
            r = await client.put("/api/settings", json={"family_safe": {"on": False}}, headers=h)
            self.assertEqual(r.status, 403, "not through the ordinary settings")
            r = await client.post("/api/family-safe", json={"on": False, "password": "a wrong one"}, headers=h)
            self.assertEqual(r.status, 401)
            self.assertTrue(self.device.store.settings()["family_safe"]["on"])
            r = await client.post("/api/family-safe", json={"on": False, "password": "a good password"}, headers=h)
            self.assertEqual(r.status, 200)
            self.assertFalse(self.device.store.settings()["family_safe"]["on"])
        finally:
            await client.close()


class Mic:
    def __init__(self):
        self.opened = 0
        self.closed = 0

    async def frames(self):
        self.opened += 1
        try:
            while True:
                yield VOICE
                await asyncio.sleep(0.005)
        finally:
            self.closed += 1


class MicrophoneTest(Base):
    async def test_holding_the_button_turns_the_microphone_off_and_on(self):
        self.device.button_up(0.4)
        self.assertTrue(self.device.listening, "a short press listens")
        self.device.button()
        self.device.button_up(3.0)
        self.assertTrue(self.device.muted)
        self.assertTrue(self.device.store.settings()["microphone"]["muted"], "kept across restarts")
        self.assertEqual(overlay_commands(self.stage, "mic-off")[-1]["anchor"], "top_right", "the sign shows")
        self.device.button_up(0.3)
        self.assertFalse(self.device.listening, "a press while it is off does not listen")
        self.assertEqual(overlay_commands(self.stage, "hint")[-1]["image"].split("-")[0], "hint")
        self.device.button_up(9.0)
        self.assertTrue(self.device.muted, "a hold of 7 to 12 seconds changes nothing")
        self.device.button_up(2.5)
        self.assertFalse(self.device.muted)
        self.assertEqual(overlay_commands(self.stage, "mic-off")[-1], {"slot": "mic-off", "image": None})
        self.device.button_up(device_module.RESET_HOLD + 1)
        await asyncio.sleep(0)
        self.assertEqual(self.restarted, [1], "12 seconds still resets the setup")

    async def test_while_held_the_screen_says_what_letting_go_will_do(self):
        old = (device_module.MUTE_HOLD, device_module.RESET_WARN, device_module.RESET_HOLD)
        device_module.MUTE_HOLD, device_module.RESET_WARN, device_module.RESET_HOLD = 0.05, 0.1, 0.15
        try:
            self.device.button_down()
            await asyncio.sleep(0.3)
            hints = overlay_commands(self.stage, "hint")
            self.assertEqual(len(hints), 3, "microphone, then a warning, then the reset")
            self.device.button_up(0.3)
        finally:
            device_module.MUTE_HOLD, device_module.RESET_WARN, device_module.RESET_HOLD = old

    async def test_a_mute_switch_wins_and_the_recording_program_stops(self):
        mic = Mic()
        self.device.microphone = mic
        task = asyncio.ensure_future(self.device.listen_loop())
        await asyncio.sleep(0.05)
        self.assertEqual(mic.opened, 1)
        self.device.set_switch(True)
        await asyncio.sleep(0.1)
        self.assertEqual(mic.closed, 1, "the microphone is closed, not just ignored")
        self.device.button_up(3.0)
        self.assertTrue(self.device.muted, "the switch wins over the button")
        self.device.set_switch(False)
        await asyncio.sleep(0.4)
        self.assertEqual(mic.opened, 2, "listening again once the switch is off")
        task.cancel()

    async def test_the_settings_page_turns_it_off_and_on(self):
        client = TestClient(TestServer(make_app(self.device)))
        await client.start_server()
        try:
            h = {"X-Companion": "1"}
            await client.post("/api/setup", json={"password": "a good password"}, headers=h)
            r = await client.post("/api/microphone", json={"muted": True}, headers=h)
            self.assertEqual(await r.json(), {"muted": True, "switch": None})
            self.assertTrue((await (await client.get("/api/status")).json())["muted"])
            self.device.set_switch(True)
            r = await client.post("/api/microphone", json={"muted": False}, headers=h)
            self.assertEqual(r.status, 400, "the switch is on")
        finally:
            await client.close()

    async def test_a_stage_that_starts_again_shows_the_sign_again(self):
        self.device.set_muted(True)
        self.stage.commands.clear()
        self.device._stage_event({"event": "ready", "width": 600, "height": 1024})
        self.assertEqual(overlay_commands(self.stage, "mic-off")[-1]["anchor"], "top_right")
        self.assertEqual(self.device.overlays.screen, (600, 1024))


class ScreenTest(Base):
    def at(self, hour):
        return datetime.datetime.now().replace(hour=hour, minute=30).timestamp()

    async def test_the_screen_sleeps_at_night_when_nobody_is_talking(self):
        self.assertEqual(self.device.screen_step(self.at(23)), "on", "off unless turned on")
        self.device.store.update_settings({"screen": {"sleep": True, "sleep_from": 22, "sleep_to": 7}})
        self.device.last_activity = self.at(23) - 10
        self.assertEqual(self.device.screen_step(self.at(23)), "on", "not straight after something happened")
        self.device.last_activity = self.at(23) - 600
        self.assertEqual(self.device.screen_step(self.at(23)), "off")
        self.assertEqual(screen_commands(self.stage), ["off"])
        self.device.button()
        self.assertEqual(screen_commands(self.stage), ["off", "on"], "the button lights it")
        self.device.listening = False
        self.device.set_state("idle")
        self.device.last_activity = self.at(3) - 600
        self.device.store.update_settings({"screen": {"how": "dim"}})
        self.assertEqual(self.device.screen_step(self.at(3)), "dim")
        self.assertEqual(self.device.screen_step(self.at(12)), "on", "lit in the day")

    async def test_an_alarm_or_speech_lights_it(self):
        self.device.store.update_settings({"screen": {"sleep": True, "sleep_from": 0, "sleep_to": 23}})
        self.device.last_activity = 0
        self.device.screen_step()
        self.assertEqual(self.device.screen_mode, "off")
        await self.device.say("hello")
        self.assertEqual(self.device.screen_mode, "on")

    def test_the_backlight_is_set_where_there_is_one(self):
        with tempfile.TemporaryDirectory() as root:
            panel = os.path.join(root, "11-0045")
            os.makedirs(panel)
            for name, value in (("brightness", "255"), ("max_brightness", "255"), ("bl_power", "0")):
                with open(os.path.join(panel, name), "w") as f:
                    f.write(value)
            def read(name):
                with open(os.path.join(panel, name)) as f:
                    return f.read()
            light = Backlight(root)
            self.assertTrue(light.available)
            light.set(0.5)
            self.assertEqual(read("brightness"), "128")
            light.set(0)
            self.assertEqual((read("brightness"), read("bl_power")), ("0", "4"))
            self.assertEqual(light.level(), 0.0)
            light.set(1.0)
            self.assertEqual(light.level(), 1.0)
        self.assertFalse(Backlight(os.path.join(root, "none")).available, "an HDMI screen has none")

    def test_the_settings_are_checked(self):
        for bad in ({"screen": {"how": "sleep"}}, {"screen": {"sleep_from": 24}}, {"screen": {"brightness": 5}},
                    {"captions": {"size": "huge"}}, {"microphone": {"muted": "yes"}}, {"wake_word": {"phrase": "hey 2pac"}},
                    {"wake_word": {"sensitivity": "max"}}, {"family_safe": {"on": 1}}):
            with self.assertRaises(ValueError, msg=str(bad)):
                self.device.store.update_settings(bad)


if __name__ == "__main__":
    unittest.main()
