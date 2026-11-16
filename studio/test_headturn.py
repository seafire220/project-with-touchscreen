"""Tests for headturn using a tiny hand-built puppet."""
import copy
import math
import unittest

import headturn


def grid(x0, y0, x1, y1, step):
    verts = []
    y = y0
    while y <= y1:
        x = x0
        while x <= x1:
            verts += [float(x), float(y)]
            x += step
        y += step
    return verts


def part(uuid, name, verts):
    return {"uuid": uuid, "name": name, "type": "Part", "transform": {"trans": [0.0, 0.0, 0.0]},
            "mesh": {"verts": verts}}


def puppet():
    # Face from x -40..40, y -80..0 (chin at y = 0); hair reaches far below the chin.
    face = part(10, "18_face_base", grid(-40, -80, 40, 0, 10))
    hair = part(11, "82_hair_front", grid(-60, -110, 60, 300, 20))
    head = {"uuid": 2, "name": "head", "type": "Node", "transform": {"trans": [0.0, 0.0, 0.0]}, "children": [face, hair]}
    root = {"uuid": 1, "name": "Root", "type": "Node", "transform": {"trans": [0.0, 0.0, 0.0]}, "children": [head]}

    def angle(name, uuid):
        return {"uuid": uuid, "name": name, "axis_points": [[0.0, 0.5, 1.0], [0.0]], "bindings": [
            {"node": 2, "param_name": "transform.r.y", "values": [[-0.5], [0.0], [0.5]], "isSet": [[True]] * 3,
             "interpolate_mode": "Linear"},
            {"node": 99, "param_name": "transform.t.x", "values": [[-60.0], [0.0], [60.0]], "isSet": [[True]] * 3,
             "interpolate_mode": "Linear"}]}

    blink = {"uuid": 30, "name": "ParamEyeLOpen", "axis_points": [[0.0, 1.0], [0.0]],
             "bindings": [{"node": 10, "param_name": "opacity", "values": [[0.0], [1.0]]}]}
    return {"nodes": root, "param": [angle("ParamAngleX", 20), angle("ParamAngleY", 21), angle("ParamAngleZ", 22), blink]}


def offsets(p, name, part_uuid, position):
    param = next(q for q in p["param"] if q["name"] == name)
    binding = next(b for b in param["bindings"] if b["node"] == part_uuid and b["param_name"] == "deform")
    return binding["values"][position][0]


def vertex_index(verts, x, y):
    for i in range(0, len(verts), 2):
        if verts[i] == x and verts[i + 1] == y:
            return i // 2
    raise AssertionError("no vertex at (%s, %s)" % (x, y))


class HeadTurnTest(unittest.TestCase):
    def setUp(self):
        self.p = puppet()
        self.before = copy.deepcopy(self.p)
        self.report = headturn.refine(self.p)
        self.face = self.p["nodes"]["children"][0]["children"][0]["mesh"]["verts"]
        self.hair = self.p["nodes"]["children"][0]["children"][1]["mesh"]["verts"]

    def test_the_rigid_turn_is_removed_and_other_bindings_kept(self):
        for name in headturn.ANGLE_PARAMS:
            param = next(q for q in self.p["param"] if q["name"] == name)
            self.assertFalse(any(b["node"] == 2 for b in param["bindings"]), name)
            self.assertTrue(any(b["node"] == 99 for b in param["bindings"]), "hair physics input is kept")
        self.assertEqual(self.p["param"][3], self.before["param"][3], "blink is untouched")
        self.assertEqual(self.report["removed"], 3)
        self.assertEqual(self.report["added"], 6)

    def test_every_head_part_gets_one_offset_per_vertex(self):
        for name in headturn.ANGLE_PARAMS:
            for uuid, verts in ((10, self.face), (11, self.hair)):
                for position in range(3):
                    self.assertEqual(len(offsets(self.p, name, uuid, position)), len(verts) // 2)

    def test_the_middle_position_moves_nothing(self):
        for name in headturn.ANGLE_PARAMS:
            for uuid in (10, 11):
                self.assertTrue(all(o == [0.0, 0.0] for o in offsets(self.p, name, uuid, 1)))

    def test_turning_slides_the_middle_of_the_face_and_leaves_the_chin(self):
        right = offsets(self.p, "ParamAngleX", 10, 2)
        middle = right[vertex_index(self.face, 0, -40)]
        chin = right[vertex_index(self.face, 0, 0)]
        self.assertGreater(middle[0], 8.0, "features slide sideways")
        self.assertLess(abs(chin[0]), 0.15 * middle[0], "the chin stays on the neck")
        left = offsets(self.p, "ParamAngleX", 10, 0)[vertex_index(self.face, 0, -40)]
        self.assertAlmostEqual(left[0], -middle[0], places=2)

    def test_the_far_side_of_the_face_narrows(self):
        right = offsets(self.p, "ParamAngleX", 10, 2)
        near_edge = right[vertex_index(self.face, 40, -40)][0]
        far_edge = right[vertex_index(self.face, -40, -40)][0]
        width_after = (40 + near_edge) - (-40 + far_edge)
        self.assertLess(width_after, 80.0)

    def test_hair_far_below_the_chin_does_not_move(self):
        for name in headturn.ANGLE_PARAMS:
            tip = offsets(self.p, name, 11, 2)[vertex_index(self.hair, 0, 290)]
            self.assertEqual(tip, [0.0, 0.0], name)

    def test_tilting_leans_the_crown_but_not_the_neck(self):
        lean = offsets(self.p, "ParamAngleZ", 11, 2)
        crown = lean[vertex_index(self.hair, 0, -110)]
        self.assertGreater(abs(crown[0]), 10.0)
        chin = offsets(self.p, "ParamAngleZ", 10, 2)[vertex_index(self.face, 0, 0)]
        self.assertLess(math.hypot(*chin), 0.5)

    def test_running_it_twice_gives_the_same_result(self):
        once = copy.deepcopy(self.p)
        headturn.refine(self.p)
        self.assertEqual(self.p, once)

    def test_file_round_trip_keeps_the_texture_section(self):
        data = headturn.write_puppet(self.before, b"TEX_SECT\x00\x00\x00\x00")
        loaded, rest = headturn.read_puppet(data)
        self.assertEqual(loaded, self.before)
        self.assertEqual(rest, b"TEX_SECT\x00\x00\x00\x00")
        with self.assertRaises(ValueError):
            headturn.read_puppet(b"not a puppet")

    def test_puppets_without_a_head_or_face_are_refused(self):
        no_head = puppet()
        no_head["nodes"]["children"][0]["name"] = "body"
        with self.assertRaises(ValueError):
            headturn.refine(no_head)
        no_face = puppet()
        no_face["nodes"]["children"][0]["children"][0]["name"] = "something"
        with self.assertRaises(ValueError):
            headturn.refine(no_face)


if __name__ == "__main__":
    unittest.main()
