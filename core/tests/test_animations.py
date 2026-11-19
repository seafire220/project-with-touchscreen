"""Full-body animation for 3D avatars: checking .vrma clips, keeping them per character with their
roles, the animation style, and the settings the stage reads."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from companion import animations, package  # noqa: E402
from companion.characters import Characters  # noqa: E402
from test_package import good_files, manifest  # noqa: E402
from vrm_sample import sample_vrm, sample_vrma  # noqa: E402

BUILTIN = os.path.join(os.path.dirname(__file__), "..", "..", "stage", "motions", "vrma")


class CheckTest(unittest.TestCase):
    def test_a_clip_is_checked_and_described(self):
        facts = animations.check(sample_vrma(1.5))
        self.assertEqual(facts["seconds"], 1.5)
        self.assertIn("hips", facts["bones"])
        self.assertEqual(facts["expressions"], ["happy"])
        self.assertEqual(animations.check(sample_vrma(2.0, with_max=False))["seconds"], 2.0, "times read from the data")

    def test_files_that_are_not_usable_clips_are_refused_with_a_reason(self):
        for data, why in ((sample_vrm(1), "not a VRM Animation"), (sample_vrma(extension=False), "not a VRM Animation"),
                          (sample_vrma(bones=("spine", "head")), "hips"), (sample_vrma(external=True), "separate file"),
                          (sample_vrma(seconds=300), "120 seconds"),
                          (sample_vrma(copyright="sk-ant-api03-" + "a" * 40), "API key"),
                          (b"not a file at all", "glTF")):
            with self.assertRaisesRegex(animations.AnimationError, why):
                animations.check(data)

    def test_the_built_in_clips_pass_the_check(self):
        names = sorted(f for f in os.listdir(BUILTIN) if f.endswith(".vrma"))
        self.assertGreaterEqual(len(names), 30)
        for name in names:
            with open(os.path.join(BUILTIN, name), "rb") as f:
                facts = animations.check(f.read())
            self.assertGreater(facts["seconds"], 0.5, name)
        for loop in ("idle", "idle_happy", "idle_sad", "idle_listen", "idle_think", "idle_talk", "idle_sleep"):
            self.assertIn(loop + ".vrma", names)


class KeepingTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.chars = Characters(self.dir.name)
        self.cid = self.chars.install(package.from_vrm(sample_vrm(1)))
        self.anims = animations.Animations(self.chars)

    def tearDown(self):
        self.dir.cleanup()

    def test_clips_are_kept_with_their_roles(self):
        a = self.anims
        self.assertEqual(a.add(self.cid, "idle_happy", sample_vrma(4.0), title="Happy idle")["kind"], "loop")
        self.assertEqual(a.add(self.cid, "wave", sample_vrma(2.0), gestures=["wave"])["kind"], "replaces")
        entry = a.add(self.cid, "little_dance", sample_vrma(3.0), words="do a  little dance")
        self.assertEqual((entry["kind"], entry["words"]), ("gesture", "do a little dance"))
        self.assertEqual(set(a.index(self.cid)), {"idle_happy", "wave", "little_dance"})
        self.assertTrue(os.path.isfile(a.path(self.cid, "wave")))
        self.assertEqual(a.words(self.cid), {"little_dance": "do a little dance"}, "only new gestures need words")
        for bad in ("idle_dance", "Bad-Name", "_try", ""):
            with self.assertRaises(animations.AnimationError, msg=bad):
                a.add(self.cid, bad, sample_vrma())
        with self.assertRaisesRegex(animations.AnimationError, "plain words"):
            a.add(self.cid, "jig", sample_vrma(), words="[happy] dance")
        self.assertTrue(a.remove(self.cid, "wave"))
        self.assertFalse(a.remove(self.cid, "wave"))
        self.assertFalse(os.path.exists(os.path.join(a.folder(self.cid), "wave.vrma")))
        described = a.describe(self.cid, gestures=["wave", "nod"])
        roles = [r["role"] for r in described["roles"]]
        self.assertEqual(roles[0], "idle")
        self.assertIn("wave", roles)
        self.assertIn("idle_happy", [x["role"] for x in described["added"]])

    def test_the_style_and_the_stage_settings(self):
        a = self.anims
        self.assertEqual(a.settings(self.cid), {"animation": "full", "quality": "auto", "shot": "upper"})
        settings = a.stage_settings(self.cid)
        self.assertEqual(settings["vrm_animation"], "full")
        self.assertEqual(settings["clip_folders"], [animations.BUILTIN, a.folder(self.cid)])
        a.set_settings(self.cid, {"animation": "light", "shot": "full"})
        self.assertEqual(a.stage_settings(self.cid)["vrm_animation"], "light")
        self.assertEqual(a.stage_settings(self.cid)["shot"], "full")
        a.add(self.cid, "jig", sample_vrma(), words="dance a jig")
        self.assertEqual(a.words(self.cid), {}, "in the light style its clips do not play")
        with self.assertRaises(animations.AnimationError):
            a.set_settings(self.cid, {"animation": "wobbly"})
        flat = self.chars.install(package.build(good_files(), manifest()))
        self.assertEqual(a.stage_settings(flat), {}, "a 2D character has no stage settings")

    def test_reinstalling_a_character_keeps_its_animations(self):
        self.anims.add(self.cid, "idle", sample_vrma(4.0))
        self.chars.set_device_settings(self.cid, {"vrm": {"animation": "light"}})
        self.chars.install(package.from_vrm(sample_vrm(1)), replace=True)
        self.assertIn("idle", self.anims.index(self.cid))
        self.assertEqual(self.anims.settings(self.cid)["animation"], "light")


class FailsafeTest(unittest.TestCase):
    """A 3D avatar the stage cannot cope with: drawn lightly, then a card."""

    def setUp(self):
        from companion.audio import Speaker
        from companion.device import Device
        from fakes import FakeStage
        self.dir = tempfile.TemporaryDirectory()
        self.stage = FakeStage()
        self.device = Device(self.dir.name, speaker=Speaker(command=None, realtime=False), stage=self.stage)
        self.cid = self.device.characters.install(package.from_vrm(sample_vrm(1)))
        self.device.activate(self.cid)
        self.device.stage_restarted = 0.0          # long ago

    def tearDown(self):
        self.dir.cleanup()

    def settings_file(self):
        with open(self.device.stage_settings) as f:
            return json.load(f)

    def test_a_crash_soon_after_starting_draws_it_lightly_then_shows_a_card(self):
        d = self.device
        self.assertEqual(self.settings_file()["quality"], "auto")
        d._stage_event({"event": "ready"})
        d._stage_event({"event": "lost"})
        self.assertEqual(d.animations.settings(self.cid)["quality"], "lite")
        self.assertEqual(self.settings_file()["quality"], "lite", "the stage reads it when it starts again")
        self.assertIn("vrm_failsafe", d.characters.device_settings(self.cid))
        self.assertTrue(os.path.realpath(d.current_puppet).endswith("model.vrm"), "still the avatar, drawn lightly")
        d._stage_event({"event": "ready"})
        d._stage_event({"event": "fatal", "message": "renderer could not start: out of memory"})
        self.assertEqual(os.path.realpath(d.current_puppet), os.path.realpath(d.card), "then a card")
        self.assertTrue(any("too much for this device" in e.get("message", "") for e in d.log))

    def test_an_expected_restart_or_a_long_run_is_not_a_failure(self):
        d = self.device
        d._stage_event({"event": "ready"})
        d.restart_stage()
        d._stage_event({"event": "lost"})
        d.stage_restarted = 0.0
        d.stage_ready_at -= 3600
        d._stage_event({"event": "lost"})
        self.assertEqual(d.animations.settings(self.cid)["quality"], "auto")
        # A 2D character is left to the service manager.
        flat = d.characters.install(package.build(good_files(), manifest()))
        d.activate(flat)
        d.stage_restarted = 0.0
        d._stage_event({"event": "ready"})
        self.assertFalse(d._stage_failed("gone"))

    def test_a_stage_that_never_starts_gets_a_light_try_first(self):
        d = self.device
        self.assertTrue(d._stage_failed("the screen program did not start"))
        self.assertEqual(d.animations.settings(self.cid)["quality"], "lite")
        self.assertTrue(d._stage_failed("the screen program did not start"))
        self.assertEqual(os.path.realpath(d.current_puppet), os.path.realpath(d.card))

    def test_slower_drawing_is_noted_for_the_settings_page(self):
        d = self.device
        d._stage_event({"event": "quality", "level": 1, "change": "outlines left out", "fps": 16.5})
        seen = d.animations.describe(self.cid)["quality_seen"]
        self.assertEqual((seen["level"], seen["change"]), (1, "outlines left out"))

    def test_a_heavy_avatar_starts_drawn_lightly(self):
        heavy = self.device.characters.install(package.from_vrm(sample_vrm(1, points=200_000, triangles=150_000), name="Big"))
        self.assertEqual(self.device.animations.settings(heavy)["quality"], "lite")
        self.assertEqual(self.device.animations.settings(self.cid)["quality"], "auto")


if __name__ == "__main__":
    unittest.main()
