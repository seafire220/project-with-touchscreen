"""Tests for refine.py on a small hand-built puppet. No artwork is needed."""
import copy
import math
import unittest

import refine

UUID = iter(range(1, 1000))


def part(name, x0, y0, x1, y1, step=4):
    """A Part whose mesh is a grid of points over a box, positioned by its own offset."""
    verts = []
    y = y0
    while y <= y1:
        x = x0
        while x <= x1:
            verts += [x, y]
            x += step
        y += step
    return {"uuid": next(UUID), "name": name, "type": "Part", "transform": {"trans": [0.0, 0.0, 0.0]},
            "mesh": {"verts": verts}, "children": []}


def puppet():
    """A head (face, eyes, mouth, hair) on a neck and body. y grows downwards; the chin is at y=0."""
    head = {"uuid": next(UUID), "name": "head", "type": "Node", "transform": {"trans": [0.0, -100.0, 0.0]},
            "children": [
                part("24_face_base", -50, -100, 50, 0),
                part("30_eye_white_l", -35, -55, -15, -45, 2), part("40_pupil_l", -32, -56, -18, -44, 2),
                part("50_eye_l", -36, -58, -14, -44, 2), part("52_eye_closed_l", -36, -50, -14, -46, 2),
                part("30_eye_white_r", 15, -55, 35, -45, 2), part("40_pupil_r", 18, -56, 32, -44, 2),
                part("50_eye_r", 14, -58, 36, -44, 2),
                part("58_mouth_cavity", -8, -18, 8, -8, 2), part("60_mouth", -8, -19, 8, -17, 1),
                part("80_hair_front", -70, -150, 70, -60),
            ]}
    body = {"uuid": next(UUID), "name": "body", "type": "Node", "transform": {"trans": [0.0, 0.0, 0.0]},
            "children": [part("10_torso", -80, -80, 80, 200), part("14_neck", -15, -110, 15, -60), head]}
    nodes = {"uuid": next(UUID), "name": "Root", "type": "Node", "transform": {"trans": [0.0, 0.0, 0.0]},
             "children": [body]}
    params = []
    for name in refine.ANGLE_PARAMS:
        params.append({"name": name, "axis_points": [[0.0, 0.5, 1.0], [0.0]], "bindings": [
            {"node": head["uuid"], "param_name": "transform.r.z", "values": [[0.1], [0.0], [-0.1]],
             "isSet": [[True]] * 3, "interpolate_mode": "Linear"}]})
    mouth = {"name": refine.MOUTH_PARAM, "axis_points": [[0.0, 1.0], [0.0]], "bindings": []}
    params.append(mouth)
    return {"nodes": nodes, "param": params}


def binding(p, param, role, kind="deform"):
    names = {}

    def walk(n):
        names[n["uuid"]] = n["name"]
        for c in n.get("children") or []:
            walk(c)
    walk(p["nodes"])
    prm = next(x for x in p["param"] if x["name"] == param)
    found = [b for b in prm["bindings"] if refine.role_of(names[b["node"]]) == role and b["param_name"] == kind]
    return found[0] if found else None


def mesh_points(p, role):
    for item in refine.walk_parts(p["nodes"]):
        if item["role"] == role:
            return refine.points(item)
    raise KeyError(role)


class RefineTest(unittest.TestCase):
    def setUp(self):
        self.original = puppet()
        self.p = copy.deepcopy(self.original)
        self.report = refine.refine(self.p)

    def offsets(self, param, role, position):
        b = binding(self.p, param, role)
        index = {-1: 0, 0: 1, 1: 2}[position]
        return b["values"][index][0]

    def test_the_rigid_head_rotation_is_replaced(self):
        for name in refine.ANGLE_PARAMS:
            prm = next(x for x in self.p["param"] if x["name"] == name)
            self.assertFalse(any(b["param_name"].startswith("transform.") for b in prm["bindings"]))
            self.assertIsNotNone(binding(self.p, name, "face_base"))

    def test_eyes_and_mouth_keep_their_shape_when_the_head_turns_or_nods(self):
        for name in ("ParamAngleX", "ParamAngleY"):
            for role in ("eye_l", "eye_white_l", "pupil_l", "eye_closed_l", "eye_r", "mouth", "mouth_cavity"):
                moves = {tuple(o) for o in self.offsets(name, role, 1)}
                self.assertEqual(len(moves), 1, "%s %s moves as one piece" % (name, role))

    def test_each_eye_moves_as_one_group(self):
        moves = {tuple(self.offsets("ParamAngleX", role, 1)[0]) for role in ("eye_l", "eye_white_l", "pupil_l", "eye_closed_l")}
        self.assertEqual(len(moves), 1)

    def test_a_turn_slides_the_middle_of_the_face_more_than_its_edge_and_not_the_hair_outline(self):
        pts = mesh_points(self.p, "face_base")
        moves = self.offsets("ParamAngleX", "face_base", 1)
        middle = max(m[0] for m, (x, y) in zip(moves, pts))
        edge = [m[0] for m, (x, y) in zip(moves, pts) if abs(x) >= 49 and abs(y + 150) < 3]
        self.assertGreater(middle, 0.1 * 100 * 0.9, "the middle slides about a tenth of the face width")
        self.assertTrue(all(e < 0.6 * middle for e in edge))
        hair_pts = mesh_points(self.p, "hair_front")
        hair_moves = self.offsets("ParamAngleX", "hair_front", 1)
        rim = [abs(m[0]) for m, (x, y) in zip(hair_moves, hair_pts) if abs(x) >= 69]
        self.assertTrue(all(r < 1e-6 for r in rim), "the outline of the head stays put")

    def test_turning_the_other_way_mirrors_and_rest_is_untouched(self):
        right = self.offsets("ParamAngleX", "mouth", 1)[0]
        left = self.offsets("ParamAngleX", "mouth", -1)[0]
        self.assertAlmostEqual(right[0], -left[0], places=3)
        self.assertEqual(self.offsets("ParamAngleX", "face_base", 0)[0], [0.0, 0.0])

    def test_a_nod_moves_the_features_up_or_down(self):
        down = self.offsets("ParamAngleY", "eye_l", -1)[0]
        up = self.offsets("ParamAngleY", "eye_l", 1)[0]
        self.assertGreater(down[1], 0)
        self.assertLess(up[1], 0)

    def test_a_tilt_turns_the_whole_head_as_one_piece_and_bends_the_neck(self):
        pts = {role: mesh_points(self.p, role) for role in ("face_base", "eye_l", "hair_front", "neck")}
        moved = {}
        for role, plist in pts.items():
            moves = self.offsets("ParamAngleZ", role, 1)
            moved[role] = [(x + dx, y + dy) for (x, y), (dx, dy) in zip(plist, moves)]
        a0, b0 = pts["eye_l"][0], pts["face_base"][-1]
        a1, b1 = moved["eye_l"][0], moved["face_base"][-1]
        self.assertAlmostEqual(math.dist(a0, b0), math.dist(a1, b1), places=1)
        self.assertGreater(abs(moved["eye_l"][0][0] - pts["eye_l"][0][0]), 3, "the head visibly leans")
        neck_moves = self.offsets("ParamAngleZ", "neck", 1)
        bottom = [abs(dx) + abs(dy) for (x, y), (dx, dy) in zip(pts["neck"], neck_moves) if y >= -61]
        self.assertTrue(all(b < 0.5 for b in bottom), "the bottom of the neck stays on the body")

    def test_the_mouth_line_fades_as_the_open_mouth_grows_from_it(self):
        prm = next(x for x in self.p["param"] if x["name"] == refine.MOUTH_PARAM)
        self.assertEqual(prm["axis_points"][0], [0.0, refine.MOUTH_SHOWN, 1.0])
        line = binding(self.p, refine.MOUTH_PARAM, "mouth", "opacity")["values"]
        self.assertEqual([v[0] for v in line], [1.0, refine.LINE_AT_SHOWN, 0.0])
        cavity = binding(self.p, refine.MOUTH_PARAM, "mouth_cavity", "opacity")["values"]
        self.assertEqual([v[0] for v in cavity], [0.0, 1.0, 1.0])
        shut = binding(self.p, refine.MOUTH_PARAM, "mouth_cavity")["values"][0][0]
        pts = mesh_points(self.p, "mouth_cavity")
        top = min(y for _, y in pts)
        self.assertTrue(all(abs(y + dy - top) < 1e-6 for (_, y), (_, dy) in zip(pts, shut)), "shut: flat on the line")

    def test_puppets_without_a_head_or_face_are_refused(self):
        p = puppet()
        p["nodes"]["children"][0]["children"][2]["name"] = "something"
        with self.assertRaises(ValueError):
            refine.refine(p)
        p = puppet()
        head = p["nodes"]["children"][0]["children"][2]
        head["children"] = [c for c in head["children"] if "face_base" not in c["name"]]
        with self.assertRaises(ValueError):
            refine.refine(p)

    def test_the_file_round_trips_with_its_textures(self):
        data = refine.write_puppet(self.original, b"TEX_SECT\x00\x00\x00\x00")
        back, rest = refine.read_puppet(data)
        self.assertEqual(rest, b"TEX_SECT\x00\x00\x00\x00")
        self.assertEqual(back["param"][0]["name"], "ParamAngleX")


if __name__ == "__main__":
    unittest.main()
