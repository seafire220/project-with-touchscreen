#!/usr/bin/env python3
"""Make a picture suitable for splitting: currently, remove a flat background.

A character picture must have a transparent background before it is split
into layers. Many pictures instead sit on a plain colour. This removes such a
background by working inwards from the edges of the picture through pixels
that match the edge colour. It never touches the character's own pixels.

It handles plain backgrounds only. A scene, gradient or pattern behind the
character needs a background-removal model, which is not included yet; the
tool says so rather than guessing.

Usage: prepare.py IMAGE OUT.png
"""
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

# How close to the edge colour a pixel must be to count as background.
BACKGROUND_TOLERANCE = 30.0
# Share of the picture's edge that must be one colour to call it plain.
PLAIN_EDGE_SHARE = 0.9


def has_transparency(image):
    """True when a meaningful part of the picture is already transparent."""
    if image.mode not in ("RGBA", "LA", "PA") and "transparency" not in image.info:
        return False
    alpha = np.asarray(image.convert("RGBA"))[..., 3]
    return (alpha < 128).mean() > 0.02


def remove_flat_background(image, tolerance=BACKGROUND_TOLERANCE):
    """Return an RGBA copy with the plain background made transparent."""
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgb = rgba[..., :3].astype(np.float32)
    edge = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    colour = np.median(edge, axis=0)
    edge_match = (np.sqrt(((edge - colour) ** 2).sum(axis=1)) < tolerance).mean()
    if edge_match < PLAIN_EDGE_SHARE:
        raise ValueError(
            "the background is not a plain colour (only %d%% of the picture's edge matches); "
            "it needs a background-removal model" % round(edge_match * 100))
    like_background = np.sqrt(((rgb - colour) ** 2).sum(axis=-1)) < tolerance
    labels, _ = ndimage.label(like_background)
    touching = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    background = np.isin(labels, touching[touching > 0])
    # Take one more pixel, where the character's edge is blended with the background.
    background = ndimage.binary_dilation(background, iterations=1)
    if background.mean() > 0.97:
        raise ValueError("nothing but background was found")
    rgba[background] = 0
    return Image.fromarray(rgba, "RGBA"), float(background.mean())


def prepare(image):
    """Return (RGBA image, notes) ready for flatsplit."""
    if has_transparency(image):
        return image.convert("RGBA"), ["already has a transparent background"]
    result, share = remove_flat_background(image)
    return result, ["removed a plain background (%d%% of the picture)" % round(share * 100)]


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    try:
        result, notes = prepare(Image.open(argv[1]))
    except ValueError as error:
        print("cannot prepare this picture: %s" % error)
        return 1
    result.save(argv[2])
    for note in notes:
        print(note)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
