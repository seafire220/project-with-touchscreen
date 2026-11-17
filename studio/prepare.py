#!/usr/bin/env python3
"""Make a picture suitable for splitting: currently, remove a flat background.

A character picture must have a transparent background before it is split
into layers. Many pictures instead sit on a plain colour. This removes such a
background by working inwards from the edges of the picture through pixels
that match the edge colour.

Given the body-part labels from parts_model.py, every pixel the model says
belongs to the character is kept, even when it is the background's colour:
a white shirt on a white background, for instance. Where the character's
edge was blended with the background (the pale fringe round a JPEG), the
background's colour is taken back out of those pixels.

It handles plain backgrounds only. A scene, gradient or pattern behind the
character needs a background-removal model, which is not included yet; the
tool says so rather than guessing.

Usage: prepare.py IMAGE OUT.png [--labels MASKS.npz]
"""
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

# How close to the edge colour a pixel must be to count as background.
BACKGROUND_TOLERANCE = 30.0
# Share of the picture's edge that must be one colour to call it plain.
PLAIN_EDGE_SHARE = 0.9
# Width of the character's edge, in pixels, that is checked for blending.
FRINGE = 3
# Below this colour difference between the character and the background, an
# edge pixel's blend cannot be measured, and it is kept as it is.
CONTRAST = 40.0


def has_transparency(image):
    """True when a meaningful part of the picture is already transparent."""
    if image.mode not in ("RGBA", "LA", "PA") and "transparency" not in image.info:
        return False
    alpha = np.asarray(image.convert("RGBA"))[..., 3]
    return (alpha < 128).mean() > 0.02


def character_from_labels(masks):
    """The area the body-part labels cover, with small gaps and holes closed."""
    union = masks.any(axis=0)
    return ndimage.binary_fill_holes(ndimage.binary_closing(union, iterations=2))


def remove_flat_background(image, tolerance=BACKGROUND_TOLERANCE, keep=None):
    """Return an RGBA copy with the plain background made transparent, and the share removed.

    `keep`, if given, marks pixels that are the character whatever their colour.
    """
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgb = rgba[..., :3].astype(np.float32)
    edge = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    colour = np.median(edge, axis=0)
    edge_match = (np.sqrt(((edge - colour) ** 2).sum(axis=1)) < tolerance).mean()
    if edge_match < PLAIN_EDGE_SHARE:
        raise ValueError(
            "the background is not a plain colour (only %d%% of the picture's edge matches); "
            "it needs a background-removal model" % round(edge_match * 100))
    distance = np.sqrt(((rgb - colour) ** 2).sum(axis=-1))
    like_background = distance < tolerance
    if keep is not None:
        if keep.shape != like_background.shape:
            raise ValueError("the labels do not match the picture's size")
        like_background &= ~keep
    labels, _ = ndimage.label(like_background)
    touching = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    background = np.isin(labels, touching[touching > 0])
    if background.mean() > 0.97:
        raise ValueError("nothing but background was found")
    rgba[background] = 0

    # The character's edge: a blended pixel is part character colour (taken
    # from the nearest solid pixel inside) and part background. Work out how
    # much of each, make it that transparent, and take the background out.
    fringe = ndimage.binary_dilation(background, iterations=FRINGE) & ~background
    solid = ~background & ~fringe
    if fringe.any() and solid.any():
        idx = ndimage.distance_transform_edt(~solid, return_distances=False, return_indices=True)
        inner = rgb[idx[0][fringe], idx[1][fringe]]
        towards = inner - colour
        spread = (towards ** 2).sum(axis=1)
        share = ((rgb[fringe] - colour) * towards).sum(axis=1) / np.maximum(spread, 1e-6)
        share = np.where(spread > CONTRAST ** 2, np.clip(share, 0.0, 1.0), 1.0)
        share = np.where(share < 0.1, 0.0, share)
        safe = np.maximum(share, 1e-3)[:, None]
        pure = np.clip((rgb[fringe] - (1.0 - safe) * colour) / safe, 0, 255)
        rgba[fringe, :3] = np.where(share[:, None] > 0, pure, 0).astype(np.uint8)
        rgba[fringe, 3] = np.round(share * 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA"), float(background.mean())


def prepare(image, masks=None):
    """Return (RGBA image, notes) ready for splitting."""
    if has_transparency(image):
        return image.convert("RGBA"), ["already has a transparent background"]
    keep = character_from_labels(masks) if masks is not None else None
    result, share = remove_flat_background(image, keep=keep)
    notes = ["removed a plain background (%d%% of the picture)" % round(share * 100)]
    if keep is None:
        notes.append("no labels were given, so parts of the character in the background's colour may be lost")
    return result, notes


def main(argv):
    args = list(argv[1:])
    masks = None
    if "--labels" in args:
        i = args.index("--labels")
        if i + 1 >= len(args):
            print(__doc__)
            return 2
        masks = np.load(args[i + 1])["masks"]
        del args[i:i + 2]
    if len(args) != 2:
        print(__doc__)
        return 2
    try:
        result, notes = prepare(Image.open(args[0]), masks)
    except ValueError as error:
        print("cannot prepare this picture: %s" % error)
        return 1
    result.save(args[1])
    for note in notes:
        print(note)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
