"""Tests for partsplit, using a drawn figure and hand-made labels. No model is needed."""
import unittest

import numpy as np
from PIL import Image, ImageDraw

import partsplit
from test_flatsplit import BODY, HAIR, ORNAMENT, SKIN, figure

ARM = (30, 120, 60)


def figure_with_arms():
    """The flatsplit test figure plus a neck and two arms."""
    im = figure()
    d = ImageDraw.Draw(im)
    d.rectangle([110, 130, 130, 140], fill=SKIN + (255,))            # neck, between head and body
    d.rectangle([48, 140, 68, 250], fill=ARM + (255,))               # arm on the viewer's left
    d.rectangle([172, 140, 192, 250], fill=ARM + (255,))             # arm on the viewer's right
    return im


def labels_for(image):
    """Labels as the model would give them, derived here from the figure's known colours and layout."""
    px = np.asarray(image)
    rgb, solid = px[..., :3].astype(int), px[..., 3] > 128
    yy, xx = np.mgrid[:px.shape[0], :px.shape[1]]

    def near(colour, tolerance=6):
        return solid & (np.abs(rgb - np.array(colour)).max(axis=-1) <= tolerance)

    masks = np.zeros((len(partsplit.PARTS),) + solid.shape, bool)

    def put(name, mask):
        masks[partsplit.PARTS.index(name)] = mask

    eyes = solid & (np.abs(yy - 90) <= 7) & ((np.abs(xx - 104) <= 9) | (np.abs(xx - 136) <= 9)) & ~near(HAIR) & ~near(SKIN)
    mouth = solid & (np.abs(yy - 114) <= 1) & (np.abs(xx - 120) <= 7)
    neck = near(SKIN) & (yy >= 130) & (yy <= 140) & (np.abs(xx - 120) <= 10)
    put("hair", near(HAIR))
    put("headwear", near(ORNAMENT))
    put("eyes", eyes)
    put("mouth", mouth)
    put("neck", neck)
    put("face", near(SKIN) & ~neck)
    put("handwear", near(ARM))
    put("topwear", near(BODY))
    return masks


class PartSplitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = figure_with_arms()
        cls.masks = labels_for(cls.image)
        cls.layers, cls.report = partsplit.split(cls.image, cls.masks)
        cls.roles = dict(cls.layers)

    def test_all_expected_layers_are_cut(self):
        for role in ("torso", "neck", "arm_l", "arm_r", "face_base", "eye_white_l", "eye_white_r",
                     "pupil_l", "pupil_r", "mouth", "hair_front"):
            self.assertIn(role, self.roles)
        self.assertEqual(self.report["warnings"], [])
        self.assertEqual(self.report["unassigned_pixels"], 0)
        self.assertEqual(self.report["doubly_assigned_pixels"], 0)

    def test_layers_put_back_together_give_the_original(self):
        canvas = Image.new("RGBA", self.image.size, (0, 0, 0, 0))
        for role in sorted(self.roles, key=partsplit.ORDER.get):
            canvas.alpha_composite(Image.fromarray(self.roles[role], "RGBA"))
        original = np.asarray(self.image)
        solid = original[..., 3] > 128
        self.assertTrue(np.array_equal(np.asarray(canvas)[solid][:, :3], original[solid][:, :3]))

    def test_unlabelled_outlines_join_the_nearest_part(self):
        self.assertGreater(self.report["pixels_given_nearest_label"], 0)

    def test_arms_are_separated_by_side_and_the_body_continues_under_them(self):
        self.assertTrue(self.roles["arm_l"][200, 58, 3] > 0)
        self.assertTrue(self.roles["arm_r"][200, 182, 3] > 0)
        self.assertEqual(self.roles["arm_l"][200, 182, 3], 0)
        self.assertEqual(self.roles["torso"][200, 30, 3], 0, "nothing is invented outside the figure")
        self.assertTrue(self.roles["hair_front"][54, 120, 3] > 0, "the hair ornament travels with the hair")

    def test_the_neck_reaches_up_under_the_chin(self):
        neck = self.roles["neck"][..., 3] > 0
        self.assertTrue(neck[135, 120])
        self.assertTrue(neck[126, 120], "extended under the face")
        self.assertLess(np.abs(self.roles["neck"][126, 120, :3].astype(int) - np.array(SKIN)).max(), 12)

    def test_capabilities_describe_what_the_character_can_do(self):
        caps = self.report["capabilities"]
        self.assertTrue(caps["blink"] and caps["speak"] and caps["hair_sway"])
        self.assertTrue(caps["arm_left"] and caps["arm_right"])
        self.assertFalse(caps["legs"])

    def test_a_missing_mouth_is_reported_not_fatal(self):
        masks = self.masks.copy()
        mouth = partsplit.PARTS.index("mouth")
        masks[partsplit.PARTS.index("face")] |= masks[mouth]
        masks[mouth] = False
        layers, report = partsplit.split(self.image, masks)
        self.assertNotIn("mouth", dict(layers))
        self.assertFalse(report["capabilities"]["speak"])
        self.assertTrue(any("no mouth" in w for w in report["warnings"]))

    def test_a_hidden_eye_is_reported(self):
        masks = self.masks.copy()
        eyes = partsplit.PARTS.index("eyes")
        masks[eyes][:, 120:] = False
        layers, report = partsplit.split(self.image, masks)
        self.assertNotIn("pupil_r", dict(layers))
        self.assertIn("pupil_l", dict(layers))
        self.assertTrue(any("no right eye" in w for w in report["warnings"]))

    def test_arms_joined_across_the_body_stay_with_the_body(self):
        image = self.image.copy()
        ImageDraw.Draw(image).rectangle([48, 180, 192, 200], fill=ARM + (255,))   # forearms meeting in front
        layers, report = partsplit.split(image, labels_for(image))
        self.assertNotIn("arm_l", dict(layers))
        self.assertFalse(report["capabilities"]["arm_left"])
        self.assertTrue(any("arms are joined" in w for w in report["warnings"]))

    def test_a_picture_without_transparency_takes_its_outline_from_the_labels(self):
        solid = Image.new("RGBA", self.image.size, (150, 134, 134, 255))
        solid.alpha_composite(self.image)
        layers, report = partsplit.split(solid, self.masks)
        self.assertEqual(report["outline_from"], "labels")
        self.assertEqual(dict(layers)["torso"][5, 5, 3], 0, "the background is left out")

    def test_wrong_sized_or_faceless_labels_are_refused(self):
        with self.assertRaises(ValueError):
            partsplit.split(self.image, self.masks[:, :10, :10])
        masks = self.masks.copy()
        for name in ("face", "eyes", "mouth"):
            masks[partsplit.PARTS.index(name)] = False
        with self.assertRaises(ValueError):
            partsplit.split(self.image, masks)


if __name__ == "__main__":
    unittest.main()
