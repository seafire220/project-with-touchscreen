"""Tests for making gestures from video: landmarks to controls, and readings to a clip."""
import math
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import record_motion as rm  # noqa: E402
from companion import motions  # noqa: E402  (record_motion puts core on the path)


def face(turn=0.0, nod=0.0, tilt_degrees=0.0):
    """A face's landmarks, picture coordinates (y down), turned, nodded and tilted."""
    points = {rm.EYE_LEFT: (-30.0, 0.0), rm.EYE_RIGHT: (30.0, 0.0), rm.NOSE: (60.0 * turn, 30.0 + 20.0 * nod),
              rm.CHEEK_LEFT: (-45.0, 20.0), rm.CHEEK_RIGHT: (45.0, 20.0), rm.CHIN: (0.0, 90.0)}
    a = math.radians(tilt_degrees)
    return {k: (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)) for k, (x, y) in points.items()}


def body(left=("hang",), right=("hang",)):
    """Body landmarks with each arm hanging, waving, or with a hand on the hip."""
    pose = {"nose": (0.0, -60.0, 0.0), "shoulder_l": (-50.0, 0.0, 0.0), "shoulder_r": (50.0, 0.0, 0.0),
            "hip_l": (-35.0, 150.0, 0.0), "hip_r": (35.0, 150.0, 0.0)}
    for side, (shape,) in (("l", left), ("r", right)):
        out = -1 if side == "l" else 1
        sx = pose["shoulder_" + side][0]
        if shape == "hang":
            elbow, wrist = (sx, 70.0), (sx, 140.0)
        elif shape == "wave":
            elbow = (sx + out * 50.0, 50.0)                 # upper arm 45 degrees out
            wrist = (sx + out * 70.0, -20.0)                # forearm up and a little out
        else:                                               # a hand on the hip
            elbow = (sx + out * 45.0, 55.0)
            wrist = (sx - out * 10.0, 110.0)                # forearm back in to the hip
        pose["elbow_" + side] = elbow + (0.0,)
        pose["wrist_" + side] = wrist + (0.0,)
    return pose


class LandmarksTest(unittest.TestCase):
    def test_the_head_turns_nods_and_tilts_as_the_picture_shows(self):
        still = rm.head_controls(face())
        self.assertAlmostEqual(still["head_yaw"], 0.0, places=6)
        self.assertAlmostEqual(still["head_roll"], 0.0, places=6)
        self.assertGreater(rm.head_controls(face(turn=0.3))["head_yaw"], 0.5, "towards the picture's right")
        self.assertLess(rm.head_controls(face(nod=1.0))["head_pitch"], still["head_pitch"] - 0.5, "looking down")
        self.assertGreater(rm.head_controls(face(tilt_degrees=10))["head_roll"], 0.4, "clockwise")

    def test_arms_hang_wave_or_rest_a_hand_on_the_hip_on_either_side(self):
        rest = rm.body_controls(body())
        for side in ("left", "right"):
            self.assertAlmostEqual(rest["arm_" + side], 0.0, places=6)
            self.assertAlmostEqual(rest["arm_%s_b" % side], 0.0, places=6)
        wave = rm.body_controls(body(right=("wave",)))
        self.assertAlmostEqual(wave["arm_right"], 0.5, delta=0.05, msg="45 degrees out")
        self.assertGreater(wave["arm_right_b"], 0.7, "the forearm up, as in the library's wave (0.85)")
        self.assertAlmostEqual(wave["arm_left"], 0.0, places=6)
        hips = rm.body_controls(body(left=("hip",), right=("hip",)))
        for side in ("left", "right"):
            self.assertGreater(hips["arm_" + side], 0.3)
            self.assertLess(hips["arm_%s_b" % side], -0.5, "the forearm back in, as for a hand on the hip (-0.9)")
        mirrored = rm.body_controls(body(left=("wave",)))
        self.assertAlmostEqual(mirrored["arm_left"], wave["arm_right"], places=6)
        self.assertAlmostEqual(mirrored["arm_left_b"], wave["arm_right_b"], places=6)

    def test_tilting_the_whole_body_moves_neither_the_arms_nor_the_shoulders(self):
        upright = rm.body_controls(body(right=("wave",)))
        a = math.radians(10)
        tilted_pose = {k: (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a), z)
                       for k, (x, y, z) in body(right=("wave",)).items()}
        tilted = rm.body_controls(tilted_pose)
        for control in ("shoulders", "arm_left", "arm_right", "arm_right_b"):
            self.assertAlmostEqual(tilted[control], upright[control], places=6, msg=control)
        self.assertAlmostEqual(tilted["body_roll"], 1.0, places=6, msg="only the body's tilt changes")
        shrug = body()
        for k in ("shoulder_l", "shoulder_r", "elbow_l", "elbow_r", "wrist_l", "wrist_r"):
            shrug[k] = (shrug[k][0], shrug[k][1] - 15.0, 0.0)
        self.assertGreater(rm.body_controls(shrug)["shoulders"] - rm.body_controls(body())["shoulders"], 0.3, "a shrug")

    def test_the_face_reads_gaze_brows_smile_and_mouth(self):
        c = rm.face_controls({"eyeLookInRight": 0.6, "eyeLookOutLeft": 0.6, "mouthSmileLeft": 0.5,
                              "mouthSmileRight": 0.5, "jawOpen": 0.4, "browInnerUp": 0.5})
        self.assertGreater(c["gaze_x"], 0.5, "both eyes looking to the picture's right")
        self.assertGreater(c["smile"], 0.4)
        self.assertAlmostEqual(c["mouth_open"], 0.48)
        self.assertGreater(c["brows"], 0.4)


class ClipTest(unittest.TestCase):
    def test_a_jittery_nod_becomes_a_clean_clip(self):
        rng = random.Random(3)
        fps, frames = 30.0, []
        for i in range(60):                       # two seconds: still, a nod, still
            t = i / fps
            nod = -0.5 * math.sin(math.pi * (t - 0.6) / 0.6) if 0.6 <= t <= 1.2 else 0.0
            frames.append({"head_pitch": 0.2 + nod + rng.gauss(0, 0.02), "head_yaw": rng.gauss(0, 0.01),
                           "blink": 1.0 if 40 <= i < 43 else 0.0})
        tracks = rm.clip_from_frames(frames, fps)
        self.assertEqual(list(tracks), ["head_pitch"], "the jitter is left out, and so are the blinks")
        keys = tracks["head_pitch"]
        self.assertEqual((keys[0][1], keys[-1][1]), (0.0, 0.0), "it starts and ends at rest")
        self.assertLess(min(v for _, v in keys), -0.35, "the nod is there, measured from the rest pose")
        self.assertLess(len(keys), 15, "cut down to the keys that matter")
        entry = rm.entry_for(tracks, "gesture", "nod slowly")
        self.assertEqual(entry["needs"], ["head_pitch"])
        motions.clean("slow_nod", entry)          # the device would take it

    def test_too_short_or_too_still_is_explained(self):
        with self.assertRaises(ValueError):
            rm.clip_from_frames([{"head_pitch": 0.0}] * 5, 30.0)
        with self.assertRaises(ValueError):
            rm.clip_from_frames([{"head_pitch": 0.01}] * 60, 30.0)

    @unittest.skipUnless(os.environ.get("COMPANION_TEST_PORTRAIT"), "set COMPANION_TEST_PORTRAIT to a photo of a face")
    def test_a_video_of_a_tilting_head_gives_a_tilt(self):
        import cv2
        import numpy as np
        photo = cv2.imread(os.environ["COMPANION_TEST_PORTRAIT"])
        h, w = photo.shape[:2]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tilt.mp4")
            out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 25.0, (w, h))
            for i in range(75):                   # three seconds: still, tilted clockwise, still
                angle = 12.0 * math.sin(math.pi * (i - 25) / 25) if 25 <= i < 50 else 0.0
                turn = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
                out.write(cv2.warpAffine(photo, turn, (w, h), borderMode=cv2.BORDER_REPLICATE))
            out.release()
            frames, fps = rm.frames_from_video(path, rm.models_folder(rm.DEFAULT_MODELS))
        self.assertGreater(sum(1 for f in frames if "head_roll" in f), 60, "the face is found")
        tracks = rm.clip_from_frames(frames, fps)
        peak = max(tracks["head_roll"], key=lambda k: abs(k[1]))
        self.assertGreater(peak[1], 0.4, "tilted clockwise in the video: a clockwise tilt (%s)" % peak)
        self.assertAlmostEqual(peak[0], 1.5, delta=0.3, msg="in the middle")
        self.assertLess(max(abs(v) for _, v in tracks.get("head_yaw", [[0, 0]])), 0.3, "and no turn")


if __name__ == "__main__":
    unittest.main()
