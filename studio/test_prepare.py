"""Tests for prepare.py: plain backgrounds, characters in the background's colour, and pale fringes."""
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import prepare

WHITE = (250, 250, 250)


def shirt_picture():
    """A figure whose white shirt touches the white background on both sides."""
    im = Image.new("RGB", (120, 160), WHITE)
    d = ImageDraw.Draw(im)
    d.ellipse([40, 10, 80, 50], fill=(240, 200, 170), outline=(40, 30, 30))       # head
    d.rectangle([30, 55, 90, 130], fill=WHITE)                                    # white shirt, no outline
    d.line([30, 55, 90, 55], fill=(40, 30, 30))                                   # collar line only
    d.rectangle([45, 130, 75, 150], fill=(40, 40, 120))                           # trousers
    return im


def shirt_labels():
    masks = np.zeros((19, 160, 120), bool)
    yy, xx = np.mgrid[:160, :120]
    masks[2] = (xx - 60) ** 2 + (yy - 30) ** 2 <= 20 ** 2                         # face
    masks[11] = (xx >= 30) & (xx <= 90) & (yy >= 55) & (yy <= 130)                # topwear
    masks[13] = (xx >= 45) & (xx <= 75) & (yy >= 130) & (yy <= 150)               # bottomwear
    return masks


class PrepareTest(unittest.TestCase):
    def test_without_labels_a_white_shirt_is_lost_with_the_background(self):
        cleared, notes = prepare.prepare(shirt_picture())
        self.assertEqual(np.asarray(cleared)[90, 60, 3], 0)
        self.assertTrue(any("may be lost" in n for n in notes))

    def test_labels_keep_parts_in_the_background_colour(self):
        cleared, notes = prepare.prepare(shirt_picture(), shirt_labels())
        alpha = np.asarray(cleared)[..., 3]
        self.assertEqual(alpha[90, 60], 255, "the shirt stays")
        self.assertEqual(alpha[90, 10], 0, "the background beside it goes")
        self.assertEqual(alpha[155, 10], 0)
        self.assertFalse(any("may be lost" in n for n in notes))

    def test_a_pale_fringe_round_the_character_is_made_see_through(self):
        im = Image.new("RGB", (100, 100), WHITE)
        ImageDraw.Draw(im).ellipse([20, 20, 80, 80], fill=(30, 60, 160))
        im = im.filter(ImageFilter.GaussianBlur(1.2))          # soft, blended edge, like a JPEG
        cleared, _ = prepare.prepare(im)
        px = np.asarray(cleared)
        edge = (px[..., 3] > 0) & (px[..., 3] < 255)
        self.assertTrue(edge.any(), "blended edge pixels get part transparency")
        colours = px[edge][:, :3].astype(int)
        self.assertTrue((colours[:, 2] - colours[:, 0] > 60).mean() > 0.9, "and keep the character's blue, not white")
        self.assertEqual(px[50, 50, 3], 255)

    def test_labels_of_the_wrong_size_are_refused(self):
        with self.assertRaises(ValueError):
            prepare.prepare(shirt_picture(), shirt_labels()[:, :10, :10])


if __name__ == "__main__":
    unittest.main()
