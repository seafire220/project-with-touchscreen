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
                part("80_hair_front", -70, -150, 70, -60), part("20_hair_back", -60, -150, 60, -110),
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
    # As the rigger makes it: the body turn shifts every head part sideways by the same amount.
    shift = [{"node": n["uuid"], "param_name": "deform",
              "values": [[[[-40.0, 0.0]] * (len(n["mesh"]["verts"]) // 2)], [[[0.0, 0.0]] * (len(n["mesh"]["verts"]) // 2)],
                         [[[40.0, 0.0]] * (len(n["mesh"]["verts"]) // 2)]],
              "isSet": [[True]] * 3, "interpolate_mode": "Linear"} for n in head["children"]]
    params.append({"name": "ParamBodyAngleX", "axis_points": [[0.0, 0.5, 1.0], [0.0]], "bindings": shift})
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


def binding_list(p, param):
    return next(x for x in p["param"] if x["name"] == param)["bindings"]


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

    def moved_width(self, role, position):
        pts = mesh_points(self.p, role)
        moves = self.offsets("ParamAngleX", role, position)
        xs = [x + dx for (x, _), (dx, _) in zip(pts, moves)]
        return max(xs) - min(xs)

    def test_a_turn_narrows_the_far_eye_and_widens_the_near_eye(self):
        rest = self.moved_width("eye_l", 0)
        # Turning right (+): the right side of the face turns away.
        self.assertLess(self.moved_width("eye_r", 1), rest)
        self.assertGreater(self.moved_width("eye_l", 1), rest)
        self.assertLess(self.moved_width("eye_l", -1), rest)
        self.assertGreater(self.moved_width("eye_r", -1), rest)
        self.assertGreater(self.moved_width("eye_r", 1), 0.6 * rest, "narrower, not squashed flat")

    def test_the_pieces_of_an_eye_move_together(self):
        # The eye and its closed eye share one grid, so where they overlap they move alike.
        shared = {}
        for role in ("eye_l", "eye_closed_l"):
            for pt, move in zip(mesh_points(self.p, role), self.offsets("ParamAngleX", role, 1)):
                shared.setdefault((round(pt[0], 3), round(pt[1], 3)), []).append(tuple(move))
        both = [moves for moves in shared.values() if len(moves) == 2]
        self.assertTrue(both)
        self.assertTrue(all(abs(a[0] - b[0]) < 1e-3 and abs(a[1] - b[1]) < 1e-3 for a, b in both))

    def test_a_turn_moves_the_middle_of_the_face_most_and_holds_the_head_outline(self):
        pts = mesh_points(self.p, "face_base")
        moves = self.offsets("ParamAngleX", "face_base", 1)
        middle = max(m[0] for m in moves)
        near = [m[0] for m, (x, y) in zip(moves, pts) if x <= -49 and abs(y + 150) < 3]
        far = [m[0] for m, (x, y) in zip(moves, pts) if x >= 49 and abs(y + 150) < 3]
        self.assertGreater(middle, 0.1 * 100 * 0.9, "the middle moves about a tenth of the face width or more")
        self.assertTrue(all(f < n for f, n in zip(far, near)), "the side turning away moves least: it narrows")
        self.assertTrue(all(n < middle for n in near))
        hair_pts = mesh_points(self.p, "hair_front")
        hair_moves = self.offsets("ParamAngleX", "hair_front", 1)
        rim = [abs(m[0]) for m, (x, y) in zip(hair_moves, hair_pts) if abs(x) >= 69]
        self.assertTrue(all(r < 1e-6 for r in rim), "the outline of the head stays put")

    def test_hair_behind_the_head_moves_the_other_way(self):
        pts = mesh_points(self.p, "hair_back")
        moves = self.offsets("ParamAngleX", "hair_back", 1)
        middle = [dx for (x, _), (dx, _) in zip(pts, moves) if abs(x) < 10]
        self.assertTrue(all(dx <= 1e-9 for dx in middle), "none moves with the face")
        self.assertLess(min(middle), -1.0, "it moves the other way (points on the outline are held)")

    def test_turning_the_other_way_mirrors_and_rest_is_untouched(self):
        def mean_dx(position):
            moves = self.offsets("ParamAngleX", "mouth", position)
            return sum(dx for dx, _ in moves) / len(moves)
        self.assertAlmostEqual(mean_dx(1), -mean_dx(-1), places=2)
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

    def test_a_body_turn_carries_the_head_and_neck_together_a_little(self):
        self.assertEqual(self.report["body"], ["ParamBodyAngleX"])
        head = self.offsets("ParamBodyAngleX", "face_base", 1)
        neck = self.offsets("ParamBodyAngleX", "neck", 1)
        shift = head[0][0]
        self.assertTrue(all(m == head[0] for m in head + neck), "head and neck move as one")
        self.assertTrue(0 < shift < 0.1 * 80, "a few pixels, not the rigger's 40")
        torso = self.offsets("ParamBodyAngleX", "torso", 1)
        self.assertGreater(max(dx for dx, _ in torso), shift, "the chest moves more than the spine")
        self.assertEqual(self.offsets("ParamBodyAngleX", "face_base", 0)[0], [0.0, 0.0])
        again = copy.deepcopy(self.p)
        parts = refine.walk_parts(again["nodes"])
        refine.refine_body(again, parts, refine.head_geometry(parts))
        self.assertEqual(len(binding_list(again, "ParamBodyAngleX")), len(binding_list(self.p, "ParamBodyAngleX")),
                         "running it twice adds nothing")

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
