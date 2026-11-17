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
        for role in ("torso", "neck", "arm_l", "arm_r", "face_base", "eye_l", "eye_r",
                     "mouth", "hair_front"):
            self.assertIn(role, self.roles)
        self.assertEqual(self.report["warnings"], [])
        self.assertEqual(self.report["unassigned_pixels"], 0)
        self.assertEqual(self.report["doubly_assigned_pixels"], 0)

    def test_layers_put_back_together_give_the_original(self):
        canvas = Image.new("RGBA", self.image.size, (0, 0, 0, 0))
        for role in sorted(self.roles, key=partsplit.ORDER.get):
            if role in partsplit.HIDDEN_AT_REST:
                continue
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

    def test_hair_carries_on_behind_the_face_in_hair_colours(self):
        back = self.roles["hair_back"]
        self.assertTrue(back[100, 120, 3] > 0, "behind the middle of the face, so a turning face uncovers hair")
        shade = np.array(HAIR) * 0.8
        self.assertLess(np.abs(back[100, 120, :3].astype(int) - shade).max(), 12, "in the hair's shadow tone")
        self.assertEqual(back[135, 120, 3], 0, "not over the neck")

    def test_the_neck_continues_up_under_the_face_in_shadow(self):
        neck = self.roles["neck"][..., 3] > 0
        self.assertTrue(neck[135, 120])
        self.assertTrue(neck[126, 120], "extended under the chin")
        self.assertTrue(neck[100, 120], "and up to the eye line, so a turning head uncovers neck")
        self.assertFalse(neck[80, 120], "but not above the eyes")
        self.assertTrue(neck[100, 92], "as wide as the jaw at the eye line, where the cheeks hide it")
        self.assertFalse(neck[100, 75], "but no wider")
        self.assertFalse(neck[126, 103], "narrowing like a neck towards the chin, so no corners show")
        self.assertTrue(neck[126, 108], "still a little wider than the neck there")
        shadow = np.array(SKIN) * 0.92
        self.assertLess(np.abs(self.roles["neck"][110, 120, :3].astype(int) - shadow).max(), 6)

    def test_a_missing_neck_is_replaced_by_a_plain_one_under_the_face(self):
        masks = self.masks.copy()
        neck = partsplit.PARTS.index("neck")
        masks[partsplit.PARTS.index("face")] |= masks[neck]
        masks[neck] = False
        layers, report = partsplit.split(self.image, masks)
        made = dict(layers)["neck"][..., 3] > 0
        self.assertTrue(made[110, 120])
        self.assertFalse(made[150, 120], "it stays hidden under the face, not over the clothes")
        self.assertTrue(any("no neck" in w for w in report["warnings"]))

    def test_fringe_hair_marked_as_eye_goes_back_to_the_hair(self):
        masks = self.masks.copy()
        eyes, hair = partsplit.PARTS.index("eyes"), partsplit.PARTS.index("hair")
        masks[eyes][70:80, 96:112] = True            # a rough eye box reaching up into the fringe
        layers, _ = partsplit.split(self.image, masks)
        roles = dict(layers)
        self.assertTrue(roles["hair_front"][75, 104, 3] > 0, "the fringe stays hair")
        self.assertEqual(roles["eye_l"][75, 104, 3], 0)
        self.assertTrue(roles["eye_l"][91, 104, 3] > 0, "the eye itself stays an eye")

    def test_hidden_body_areas_are_filled_without_outline_streaks(self):
        torso = self.roles["torso"]
        arms = (self.roles["arm_l"][..., 3] > 0) | (self.roles["arm_r"][..., 3] > 0)
        hidden = (torso[..., 3] > 0) & arms
        self.assertTrue(hidden.any(), "the body continues a little under the arms")
        values = torso[hidden][:, :3].astype(int)
        self.assertLess(np.abs(values - np.array(BODY)).max(), 40, "fills take the body's colour, not its outline")

    def test_capabilities_describe_what_the_character_can_do(self):
        caps = self.report["capabilities"]
        self.assertTrue(caps["blink"] and caps["speak"] and caps["hair_sway"])
        self.assertTrue(caps["arm_left"] and caps["arm_right"])
        self.assertFalse(caps["legs"])

    def test_a_mouth_the_model_missed_is_found_by_its_colour(self):
        masks = self.masks.copy()
        mouth = partsplit.PARTS.index("mouth")
        masks[partsplit.PARTS.index("face")] |= masks[mouth]
        masks[mouth] = False
        layers, report = partsplit.split(self.image, masks)
        found = dict(layers)["mouth"][..., 3] > 0
        self.assertTrue(found[114, 120], "the drawn mouth line")
        self.assertTrue(report["capabilities"]["speak"])
        self.assertTrue(any("found by its colour" in w for w in report["warnings"]))

    def test_a_face_without_a_mouth_gets_a_small_one_to_talk_with(self):
        image = self.image.copy()
        ImageDraw.Draw(image).rectangle([100, 110, 140, 118], fill=SKIN + (255,))   # paint the mouth out
        masks = labels_for(image)
        mouth = partsplit.PARTS.index("mouth")
        masks[partsplit.PARTS.index("face")] |= masks[mouth]
        masks[mouth] = False
        layers, report = partsplit.split(image, masks)
        self.assertIn("mouth", dict(layers))
        self.assertIn("mouth_cavity", dict(layers))
        self.assertTrue(any("a small one was added" in w for w in report["warnings"]))

    def test_closed_eyes_and_an_open_mouth_are_drawn_but_hidden_at_rest(self):
        for role in ("eye_closed_l", "eye_closed_r", "mouth_cavity"):
            self.assertIn(role, self.roles)
            self.assertIn(role, partsplit.HIDDEN_AT_REST)
        closed = self.roles["eye_closed_l"][..., 3] > 0
        ys, xs = np.nonzero(closed)
        self.assertTrue(abs(xs.mean() - 104) < 4, "across the left eye")
        self.assertTrue(88 <= ys.mean() <= 98, "low in the eye, where the lid closes")
        cavity = self.roles["mouth_cavity"][..., 3] > 0
        self.assertTrue(cavity[118, 120], "the open mouth hangs from the mouth line")

    def test_a_hidden_eye_is_reported(self):
        masks = self.masks.copy()
        eyes = partsplit.PARTS.index("eyes")
        masks[eyes][:, 120:] = False
        layers, report = partsplit.split(self.image, masks)
        self.assertNotIn("eye_r", dict(layers))
        self.assertIn("eye_l", dict(layers))
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
