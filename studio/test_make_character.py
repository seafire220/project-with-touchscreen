"""End-to-end test: drawn figure and hand-made labels -> .char package. Needs the image2live2d rigger."""
import argparse
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

import numpy as np

import make_character
import refine
from companion import package
from test_partsplit import figure_with_arms, labels_for

HAVE_RIGGER = importlib.util.find_spec("image2live2d") is not None
STAGE = os.path.join(os.path.dirname(__file__), "..", "stage", "target", "release", "stage")
HAVE_STAGE = os.path.exists(STAGE) and shutil.which("xvfb-run") is not None


@unittest.skipUnless(HAVE_RIGGER, "the image2live2d rigger is not installed")
class MakeCharacterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        image = figure_with_arms()
        cls.image_path = os.path.join(cls.dir.name, "figure.png")
        image.save(cls.image_path)
        cls.labels_path = os.path.join(cls.dir.name, "figure.npz")
        np.savez_compressed(cls.labels_path, masks=labels_for(image))
        args = argparse.Namespace(labels=cls.labels_path, see_through=None, weights=None, device="cpu",
                                  persona=None, author="tester", live2d=True)
        cls.data, cls.report = make_character.make(cls.image_path, "Test Figure", args, cls.dir.name)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_the_package_opens_and_describes_the_character(self):
        p = package.open_package(io.BytesIO(self.data))
        self.assertEqual(p.id, "test-figure")
        self.assertEqual(p.manifest["name"], "Test Figure")
        self.assertTrue(p.manifest["capabilities"]["blink"])
        self.assertTrue(p.manifest["capabilities"]["speak"])
        self.assertIn("Greeting", p.persona)
        self.assertIn("preview.png", p.files)
        self.assertIn("steps", p.json("studio/report.json"))

    def test_the_puppet_has_the_refined_head_and_mouth(self):
        p = package.open_package(io.BytesIO(self.data))
        puppet, _ = refine.read_puppet(p.files["visual/puppet.inp"])
        params = {x["name"]: x for x in puppet["param"]}
        self.assertFalse(any(b["param_name"].startswith("transform.") and b["node"] == self._head(puppet)
                             for b in params["ParamAngleZ"]["bindings"]))
        self.assertEqual(params["ParamMouthOpenY"]["axis_points"][0], [0.0, refine.MOUTH_SHOWN, 1.0])

    def test_the_arms_turn_at_shoulder_and_elbow_with_rounded_ends(self):
        arms = self.report["refine"]["arms"]
        self.assertEqual(sorted(arms), ["l", "r"])
        self.assertTrue(all(arms[side]["elbow_radius"] > 2 for side in arms))
        p = package.open_package(io.BytesIO(self.data))
        puppet, _ = refine.read_puppet(p.files["visual/puppet.inp"])
        names = {n.get("name") for n in refine._nodes(puppet["nodes"])}
        self.assertTrue({"arm_l", "arm_r"} <= names)

    def test_a_preview_of_it_moving_is_drawn_without_the_stage(self):
        import preview
        from PIL import Image
        p = package.open_package(io.BytesIO(self.data))
        renderer = preview.Renderer(p.files["visual/puppet.inp"], size=96)
        rest = np.asarray(renderer.render({}))
        self.assertGreater((np.abs(rest.astype(int) - preview.BACKGROUND).sum(-1) > 30).mean(), 0.05, "the figure shows")
        keys = preview.tour([x.name for x in renderer.puppet.params])
        self.assertTrue(any("ParamArmRB" in v for _, v in keys), "the tour waves")
        gif = preview.gif(preview.frames(renderer, keys[:4], fps=4))
        self.assertTrue(gif.startswith(b"GIF89a"))
        self.assertGreater(Image.open(io.BytesIO(gif)).n_frames, 1)

    def test_the_live2d_format_version_matches_the_puppet(self):
        p = package.open_package(io.BytesIO(self.data))
        self.assertTrue(p.files["visual/live2d/model.moc3"].startswith(b"MOC3"))
        self.assertIn("visual/live2d/model.model3.json", p.files)
        check = p.json("studio/report.json")["live2d"]["check"]
        self.assertLess(check["max_px"], 4.0, check)
        self.assertEqual(check["max_opacity"], 0.0)

    @unittest.skipUnless(HAVE_STAGE, "the stage is not built, or Xvfb is missing")
    def test_the_stage_draws_both_formats_alike(self):
        folder = os.path.join(self.dir.name, "unpacked")
        with zipfile.ZipFile(io.BytesIO(self.data)) as z:
            z.extractall(folder)
        tool = os.path.join(os.path.dirname(__file__), "..", "stage", "tools", "compare_formats.py")
        run = subprocess.run([sys.executable, tool, STAGE, folder, os.path.join(self.dir.name, "compare.png")],
                             capture_output=True, text=True, timeout=1800)
        self.assertEqual(run.returncode, 0, run.stdout[-800:] + run.stderr[-800:])
        self.assertGreaterEqual(json.loads(run.stdout)["worst_overlap"], 0.98)

    def test_no_keys_or_memories_are_packed(self):
        names = set(package.open_package(io.BytesIO(self.data)).files)
        self.assertFalse(any("memor" in n or "secret" in n or "key" in n for n in names))

    @staticmethod
    def _head(puppet):
        def walk(n):
            if n.get("name") == "head":
                return n["uuid"]
            for c in n.get("children") or []:
                found = walk(c)
                if found is not None:
                    return found
        return walk(puppet["nodes"])


if __name__ == "__main__":
    unittest.main()
