"""Tests for live2d_export.py on a small hand-built puppet. Needs the image2live2d rigger (for its .moc3 writer)."""
import importlib.util
import io
import json
import os
import struct
import tempfile
import unittest

import numpy as np
from PIL import Image

import refine

HAVE_RIGGER = importlib.util.find_spec("image2live2d") is not None
if HAVE_RIGGER:
    import live2d_export as L

UUID = iter(range(1, 10000))


def part(name, x0, y0, x1, y1, texture, step=10):
    """A Part: a grid of points over a box, with texture positions and triangles."""
    xs = np.arange(x0, x1 + 1e-9, step)
    ys = np.arange(y0, y1 + 1e-9, step)
    verts, uvs = [], []
    for y in ys:
        for x in xs:
            verts += [float(x), float(y)]
            uvs += [float((x - x0) / (x1 - x0)), float((y - y0) / (y1 - y0))]
    n = len(xs)
    indices = []
    for r in range(len(ys) - 1):
        for c in range(n - 1):
            a = r * n + c
            indices += [a, a + 1, a + n, a + 1, a + n + 1, a + n]
    return {"uuid": next(UUID), "name": name, "type": "Part", "enabled": True, "zsort": -float(name[:2]),
            "transform": {"trans": [0.0, 0.0, 0.0]}, "opacity": 1.0,
            "mesh": {"verts": verts, "uvs": uvs, "indices": indices, "origin": [0.0, 0.0]},
            "textures": [texture, 4294967295, 4294967295], "children": []}


def param(name, lo, hi, default, axis, bindings):
    return {"uuid": next(UUID), "name": name, "is_vec2": False, "min": [lo, 0.0], "max": [hi, 0.0],
            "defaults": [default, 0.0], "axis_points": [axis, [0.0]], "bindings": bindings}


def deform(node, per_key):
    return {"node": node["uuid"], "param_name": "deform", "values": [[v] for v in per_key],
            "isSet": [[True] for _ in per_key], "interpolate_mode": "Linear"}


def points(node):
    return np.array(node["mesh"]["verts"], float).reshape(-1, 2)


def puppet_bytes():
    """A body that rotates and breathes, a head whose parts move differently, and an eye that closes."""
    torso = part("10_torso", -80, 0, 80, 200, 0)
    arm = part("16_arm_l", -120, 10, -80, 150, 1)
    neck = part("14_neck", -15, -40, 15, 10, 2)
    face = part("24_face_base", -50, -100, 50, 0, 3)
    eye = part("50_eye_l", -35, -60, -15, -45, 4, step=5)
    closed = part("52_eye_closed_l", -35, -54, -15, -50, 5, step=2)
    mouth = part("60_mouth", -10, -25, 10, -15, 6, step=5)
    head = {"uuid": next(UUID), "name": "head", "type": "Node", "zsort": 0.0,
            "transform": {"trans": [0.0, -40.0, 0.0]}, "children": [face, eye, closed, mouth]}
    body = {"uuid": next(UUID), "name": "body", "type": "Node", "zsort": 0.0,
            "transform": {"trans": [0.0, 300.0, 0.0]}, "children": [torso, arm, neck, head]}
    root = {"uuid": next(UUID), "name": "Root", "type": "Node", "zsort": 0.0,
            "transform": {"trans": [0.0, 0.0, 0.0]}, "children": [body]}
    head_parts = [face, eye, closed, mouth]
    body_parts = [torso, arm, neck]

    def frame_points(node):
        return points(node) + (np.array([0.0, -40.0]) if node in head_parts else 0.0)

    def breath(node):        # one smooth field over every part: the chest rises, the head a little less
        p = frame_points(node)
        return [np.zeros_like(p).ravel().tolist(),
                np.stack([0.01 * p[:, 0], -4.0 + 0.004 * p[:, 1]], 1).ravel().tolist()]

    def turn(node, shift):   # each head part slides by its own amount: not one smooth field
        p = points(node)
        return [np.tile([-shift, 0.0], (len(p), 1)).ravel().tolist(), np.zeros(p.size).tolist(),
                np.tile([shift, 0.0], (len(p), 1)).ravel().tolist()]

    params = [
        param("ParamAngleX", -30.0, 30.0, 0.0, [0.0, 0.5, 1.0],
              [deform(face, turn(face, 6.0)), deform(eye, turn(eye, 9.0)), deform(closed, turn(closed, 9.0)),
               deform(mouth, turn(mouth, 7.5))]),
        param("ParamEyeLOpen", 0.0, 1.0, 1.0, [0.0, 1.0],
              [{"node": closed["uuid"], "param_name": "opacity", "values": [[1.0], [0.0]], "isSet": [[True], [True]],
                "interpolate_mode": "Linear"},
               {"node": eye["uuid"], "param_name": "opacity", "values": [[0.0], [1.0]], "isSet": [[True], [True]],
                "interpolate_mode": "Linear"}]),
        param("ParamBreath", 0.0, 1.0, 0.0, [0.0, 1.0], [deform(n, breath(n)) for n in body_parts + head_parts]),
        param("ParamBodyAngleZ", -10.0, 10.0, 0.0, [0.0, 0.5, 1.0],
              [{"node": body["uuid"], "param_name": "transform.r.z", "values": [[-0.1], [0.0], [0.1]],
                "isSet": [[True]] * 3, "interpolate_mode": "Linear"}]),
        param("ParamArmLA", -10.0, 10.0, 0.0, [0.0, 0.5, 1.0],
              [deform(arm, [(np.array([[-30.0, 0.0]]) * (points(arm)[:, 1:2] - 10) / 140).ravel().tolist(),
                            np.zeros(points(arm).size).tolist(),
                            (np.array([[30.0, 0.0]]) * (points(arm)[:, 1:2] - 10) / 140).ravel().tolist()])]),
    ]
    data = {"meta": {"name": "test", "version": "1.0-alpha"}, "physics": {"pixelsPerMeter": 1000.0, "gravity": 9.8},
            "nodes": root, "param": params, "automation": [], "animations": {}}
    textures = []
    for colour in range(7):
        out = io.BytesIO()
        Image.new("RGBA", (4, 4), (30 * colour, 100, 200, 255)).save(out, "PNG")
        textures.append(out.getvalue())
    rest = b"TEX_SECT" + struct.pack(">I", len(textures))
    for t in textures:
        rest += struct.pack(">I", len(t)) + b"\x00" + t
    return refine.write_puppet(data, rest)


@unittest.skipUnless(HAVE_RIGGER, "the image2live2d rigger is not installed")
class Live2DExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = puppet_bytes()
        cls.files, cls.report = L.export(cls.data, name="model")
        cls.model = L.Model(L.Puppet(cls.data))

    def test_it_plays_like_the_inochi2d_puppet(self):
        check = self.report["check"]
        self.assertLess(check["max_px"], 0.5, check)
        self.assertEqual(check["max_opacity"], 0.0)

    def test_shared_smooth_movements_go_on_warps_and_part_movements_stay_on_meshes(self):
        warps = {tuple(w["fields"]): w for w in self.report["warps"]}
        self.assertTrue(warps, "breathing and the body rotation need warp deformers")
        for w in self.report["warps"]:
            self.assertIn("ParamBreath", w["settings"])
            self.assertIn("ParamBodyAngleZ", w["settings"])
            self.assertNotIn("ParamAngleX", w["settings"])
        face = next(m for m in self.model.meshes if m["part"].name == "24_face_base")
        self.assertEqual([p.name for p in face["params"]], ["ParamAngleX"])
        arm = next(m for m in self.model.meshes if m["part"].name == "16_arm_l")
        self.assertEqual([p.name for p in arm["params"]], ["ParamArmLA"], "two parts are too few for a shared field")

    def test_the_model_file_is_well_formed(self):
        from image2live2d.backends.live2d.moc3_binary import read_moc3
        moc = self.files["model.moc3"]
        self.assertEqual(moc[:5], b"MOC3\x01")
        read = read_moc3(moc)
        self.assertEqual(set(read.sections["parameters"]["decimalPlaces"]), {3})
        self.assertEqual(len(read.sections["artMeshes"]["ids"]), 7)
        index = json.loads(self.files["model.model3.json"])
        refs = index["FileReferences"]
        self.assertEqual(refs["Moc"], "model.moc3")
        for path in refs["Textures"]:
            self.assertIn(path, self.files)
        self.assertEqual(index["Groups"][0], {"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen"]})

    def test_up_is_negative_y(self):
        # Live2D's sample models and the rigger's files play upright in Ayagami with the head at negative y.
        face = next(m for m in self.model.meshes if m["part"].name == "24_face_base")
        torso = next(m for m in self.model.meshes if m["part"].name == "10_torso")
        head_y = self.model.play(face, self.model.puppet.defaults())[0]
        self.assertLess(self.model.to_model(head_y)[:, 1].mean(), self.model.to_model(
            self.model.play(torso, self.model.puppet.defaults())[0])[:, 1].mean())

    def test_drawing_order_is_back_to_front(self):
        names = [m["part"].name for m in self.model.meshes]
        self.assertEqual(names[0], "10_torso")
        self.assertEqual(names[-1], "60_mouth")

    def test_keyforms_are_laid_out_first_setting_fastest(self):
        a = L.Param({"name": "A", "min": [0, 0], "max": [1, 0], "defaults": [0, 0], "axis_points": [[0, 1], [0]]}, 0)
        b = L.Param({"name": "B", "min": [0, 0], "max": [1, 0], "defaults": [0, 0],
                     "axis_points": [[0, 0.5, 1], [0]]}, 1)
        self.assertEqual(L.combos([a, b])[:4], [(0, 0), (1, 0), (0, 1), (1, 1)])

    def test_the_riggers_physics_and_motions_are_carried_over(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "sub"))
            with open(os.path.join(d, "x.model3.json"), "w") as f:
                json.dump({"FileReferences": {"Physics": "x.physics3.json",
                                              "Motions": {"Idle": [{"File": "x.idle.motion3.json"}] * 2}}}, f)
            for name in ("x.physics3.json", "x.idle.motion3.json"):
                with open(os.path.join(d, name), "w") as f:
                    f.write("{}")
            extras = L.read_extras(d)
            files, _ = L.export(self.data, name="model", extras=extras, check=False)
            refs = json.loads(files["model.model3.json"])["FileReferences"]
            self.assertEqual(refs["Physics"], "model.physics3.json")
            self.assertEqual(refs["Motions"], {"Idle": [{"File": "motions/idle.motion3.json"}]})
            with open(os.path.join(d, "x.model3.json"), "w") as f:
                json.dump({"FileReferences": {"Physics": "../outside.json"}}, f)
            with self.assertRaises(ValueError):
                L.read_extras(d)


if __name__ == "__main__":
    unittest.main()
