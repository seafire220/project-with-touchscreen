"""Tests for flatsplit using a small drawn figure, so no artwork is stored here."""
import unittest

import numpy as np
from PIL import Image, ImageDraw

import flatsplit

SKIN = (255, 228, 214)
HAIR = (250, 230, 150)
HAIR_LINE = (220, 150, 20)
BODY = (40, 70, 160)
DARK = (25, 25, 40)
WHITE = (250, 250, 250)
IRIS = (60, 110, 200)
ORNAMENT = (235, 240, 245)

MARKS = {
    "skin": [120, 104],
    "hair": [[120, 46]],
    "eyes": {"l": [104, 90, 10, 8], "r": [136, 90, 10, 8]},
    "mouth": [120, 114, 9, 4],
}


def figure():
    """A front-facing figure: body, head, hair with two long locks, eyes, mouth, hair ornament."""
    im = Image.new("RGBA", (240, 360), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([70, 130, 170, 340], fill=BODY + (255,), outline=DARK + (255,), width=2)
    d.ellipse([70, 34, 170, 134], fill=HAIR + (255,), outline=HAIR_LINE + (255,), width=2)   # hair mass
    d.ellipse([82, 58, 158, 134], fill=SKIN + (255,), outline=DARK + (255,), width=2)        # face
    d.pieslice([70, 34, 170, 134], 180, 360, fill=HAIR + (255,), outline=HAIR_LINE + (255,), width=2)  # fringe
    for x in (74, 154):                                                                       # long locks
        d.rectangle([x, 84, x + 12, 250], fill=HAIR + (255,), outline=HAIR_LINE + (255,), width=2)
    d.polygon([(120, 44), (128, 54), (120, 64), (112, 54)], fill=ORNAMENT + (255,), outline=DARK + (255,))
    for cx in (104, 136):
        d.ellipse([cx - 8, 85, cx + 8, 97], fill=WHITE + (255,))
        d.ellipse([cx - 4, 86, cx + 4, 96], fill=IRIS + (255,))
        d.line([cx - 9, 85, cx + 9, 85], fill=DARK + (255,), width=2)
    d.line([113, 114, 127, 114], fill=DARK + (255,), width=2)
    return im


def by_role(layers):
    return {role: array for role, array in layers}


class FlatSplitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = figure()
        cls.layers, cls.report = flatsplit.split(cls.image, MARKS)
        cls.roles = by_role(cls.layers)
        cls.original = np.asarray(cls.image)

    def test_every_pixel_goes_to_exactly_one_part(self):
        self.assertEqual(self.report["unassigned_pixels"], 0)
        self.assertEqual(self.report["doubly_assigned_pixels"], 0)

    def test_expected_layers_exist(self):
        for role in ("torso", "face_base", "eye_white_l", "eye_white_r", "pupil_l", "pupil_r",
                     "eye_l", "eye_r", "mouth", "hair_front"):
            self.assertTrue(self.roles[role][..., 3].any(), role)

    def test_layers_put_back_together_give_the_original(self):
        canvas = Image.new("RGBA", self.image.size, (0, 0, 0, 0))
        for _, array in self.layers:
            canvas.alpha_composite(Image.fromarray(array, "RGBA"))
        rebuilt = np.asarray(canvas)
        solid = self.original[..., 3] > 128
        self.assertTrue(np.array_equal(rebuilt[solid][:, :3], self.original[solid][:, :3]))

    def test_hair_includes_the_long_locks_and_the_ornament(self):
        hair = self.roles["hair_front"][..., 3] > 0
        self.assertTrue(hair[200, 80], "left lock over the body")
        self.assertTrue(hair[200, 160], "right lock over the body")
        self.assertTrue(hair[54, 120], "ornament enclosed by the hair")
        self.assertFalse(hair[300, 120], "body is not hair")
        self.assertFalse(hair[104, 120], "face is not hair")

    def test_body_is_filled_in_under_the_locks(self):
        torso = self.roles["torso"]
        self.assertGreater(torso[200, 80, 3], 0, "body continues under the lock")
        self.assertLess(np.abs(torso[200, 80, :3].astype(int) - np.array(BODY)).max(), 40,
                        "the fill is body colour, not hair colour")

    def test_face_has_eyes_and_mouth_painted_over(self):
        face = self.roles["face_base"]
        for y, x in ((91, 104), (91, 136), (114, 120)):
            self.assertGreater(face[y, x, 3], 0)
            self.assertLess(np.abs(face[y, x, :3].astype(int) - np.array(SKIN)).max(), 12, (y, x))

    def test_eye_parts_are_told_apart(self):
        self.assertTrue(self.roles["pupil_l"][91, 104, 3] > 0)
        self.assertTrue(self.roles["eye_white_l"][91, 98, 3] > 0)
        self.assertTrue(self.roles["eye_l"][85, 104, 3] > 0)
        left = np.nonzero(self.roles["pupil_l"][..., 3])[1].mean()
        right = np.nonzero(self.roles["pupil_r"][..., 3])[1].mean()
        self.assertLess(left, right, "'l' is the eye on the viewer's left")

    def test_a_mark_off_the_character_is_refused(self):
        marks = dict(MARKS, skin=[5, 5])
        with self.assertRaises(ValueError):
            flatsplit.split(self.image, marks)

    def test_a_well_suited_picture_gives_no_warnings(self):
        self.assertEqual(self.report["warnings"], [])

    def test_a_tilted_face_is_warned_about(self):
        marks = dict(MARKS, eyes={"l": [104, 86, 10, 8], "r": [136, 96, 10, 8]})
        _, report = flatsplit.split(self.image, marks)
        self.assertTrue(any("tilted" in w for w in report["warnings"]), report["warnings"])

    def test_hair_matching_the_clothes_is_warned_about(self):
        # Repaint the body in the hair colour: the hair selection then runs into it.
        image = self.image.copy()
        pixels = np.asarray(image).copy()
        body = (np.abs(pixels[..., :3].astype(int) - np.array(BODY)).max(axis=-1) < 8) & (pixels[..., 3] > 0)
        pixels[body, :3] = HAIR
        _, report = flatsplit.split(Image.fromarray(pixels, "RGBA"), MARKS)
        self.assertTrue(any("same colour as the clothing" in w for w in report["warnings"]), report["warnings"])

    def test_a_picture_without_transparency_is_refused(self):
        solid = Image.new("RGBA", self.image.size, (150, 134, 134, 255))
        solid.alpha_composite(self.image)
        with self.assertRaises(ValueError):
            flatsplit.split(solid, MARKS)

    def test_a_plain_background_is_removed_and_the_split_then_works(self):
        import prepare
        solid = Image.new("RGBA", self.image.size, (150, 134, 134, 255))
        solid.alpha_composite(self.image)
        self.assertFalse(prepare.has_transparency(solid.convert("RGB")))
        cleared, notes = prepare.prepare(solid.convert("RGB"))
        self.assertTrue(prepare.has_transparency(cleared))
        self.assertIn("removed a plain background", notes[0])
        layers, report = flatsplit.split(cleared, MARKS)
        self.assertEqual(report["unassigned_pixels"], 0)
        # The character itself is untouched apart from its outermost edge pixels.
        from scipy import ndimage
        kept = np.asarray(cleared)[..., 3] > 0
        inside = ndimage.binary_erosion(kept, iterations=prepare.FRINGE)
        self.assertTrue(np.array_equal(np.asarray(cleared)[inside][:, :3], np.asarray(solid)[inside][:, :3]))
        self.assertGreater(kept.sum(), 0.9 * (np.asarray(self.image)[..., 3] > 0).sum())

    def test_a_busy_background_is_refused_not_guessed(self):
        import prepare
        rng = np.random.default_rng(0)
        noise = Image.fromarray(rng.integers(0, 255, (120, 90, 3), dtype=np.uint8), "RGB")
        with self.assertRaises(ValueError):
            prepare.prepare(noise)

    def test_layers_are_padded_to_a_square(self):
        padded = flatsplit.pad_square(self.roles["torso"])
        self.assertEqual(padded.shape[0], padded.shape[1])
        self.assertEqual(int((padded[..., 3] > 0).sum()), int((self.roles["torso"][..., 3] > 0).sum()))


if __name__ == "__main__":
    unittest.main()
