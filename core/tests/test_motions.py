"""Tests for gestures changed or added on the device: checked like the stage's own library."""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from companion import motions  # noqa: E402

GOOD = {"kind": "gesture", "needs": ["head_roll"], "words": "do a little dance",
        "tracks": {"head_roll": [[0, 0], [0.3, 0.4], [0.6, -0.4], [0.9, 0]], "smile": [[0, 0], [0.4, 0.5], [0.9, 0]]}}


class MotionsTest(unittest.TestCase):
    def test_the_core_knows_the_stages_controls(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "stage", "src", "motion.rs")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        keys = re.search(r"pub const KEYS: \[&str; \d+\] = \[(.*?)\];", source, re.S).group(1)
        self.assertEqual(tuple(re.findall(r'"(\w+)"', keys)), motions.CONTROLS)
        channels = re.search(r"pub const CHANNELS: \[&str; \d+\] =\s*\[(.*?)\];", source, re.S).group(1)
        self.assertEqual(tuple(re.findall(r'"(\w+)"', channels)), motions.CHANNELS)

    def test_a_good_gesture_is_kept_and_mistakes_are_explained(self):
        clean = motions.clean("little_dance", GOOD)
        self.assertEqual(clean["tracks"]["head_roll"][1], [0.3, 0.4])
        self.assertEqual(clean["words"], "do a little dance")
        bad = [
            ("Little Dance", GOOD, "lower-case"),
            ("dance", dict(GOOD, kind="party"), "kind"),
            ("dance", dict(GOOD, needs=["tail"]), "needs"),
            ("dance", dict(GOOD, tracks={"tail": [[0, 0], [1, 0]]}), "no control called tail"),
            ("dance", dict(GOOD, tracks={"head_roll": [[0, 0], [1, 0.4]]}), "start and end at 0"),
            ("dance", dict(GOOD, tracks={"head_roll": [[0, 0], [0.5, 0.3], [0.4, 0]]}), "forward in time"),
            ("dance", dict(GOOD, tracks={"head_roll": [[0, 0], [0.5, 3], [1, 0]]}), "-1.5 and 1.5"),
            ("dance", dict(GOOD, tracks={"head_roll": [[0, 0], [0.5, "x"], [1, 0]]}), "[seconds, value]"),
            ("dance", dict(GOOD, words="[wave] now"), "plain words"),
            ("dance", dict(GOOD, holds=["tail"]), "holds"),
        ]
        for name, entry, why in bad:
            with self.assertRaises(ValueError, msg=why) as caught:
                motions.clean(name, entry)
            self.assertIn(why, str(caught.exception))

    def test_custom_gestures_are_kept_in_one_file(self):
        with tempfile.TemporaryDirectory() as d:
            store = motions.CustomMotions(os.path.join(d, "config", "custom-motions.json"))
            store.set("little_dance", GOOD)
            store.set("yawn", {"kind": "idle", "needs": ["mouth_open"], "tracks": {"mouth_open": [[0, 0], [1, 0.9], [2, 0]]}})
            self.assertEqual(sorted(store.all()), ["little_dance", "yawn"])
            self.assertEqual(store.words(), {"little_dance": "do a little dance"}, "only gestures are asked for")
            self.assertTrue(store.remove("yawn"))
            self.assertFalse(store.remove("yawn"))
            self.assertEqual(list(store.all()), ["little_dance"])


if __name__ == "__main__":
    unittest.main()
