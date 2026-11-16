#!/usr/bin/env python3
"""Cut a character picture into named layers using body-part labels from a model.

The labels come from the See-through body-part model (Apache-2.0), which
marks 19 parts of an anime character: hair, headwear, face, eyes, eyewear,
ears, earwear, nose, mouth, neck, neckwear, topwear, handwear, bottomwear,
legwear, footwear, tail, wings and objects. That model only labels; it does
not repaint. This tool then cuts the original picture along those labels, so
every output pixel is either copied from the original or, where one part
hides another, filled with the neighbouring colour.

It replaces flatsplit.py's approach of finding parts by colour from marked
points, which failed on shaded hair and on hair matching the clothing.

Input:  the picture, and a `.npz` file holding `masks`, a 19 x height x width
        boolean array in the order above (written by parts_model.py).
Output: a folder of full-canvas layers named `{order}_{role}.png` for the
        image2live2d rigger, and a report of which parts were found.

Usage: partsplit.py IMAGE MASKS.npz OUT_DIR
"""
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

from flatsplit import convex_hull_mask, fill_from_neighbours, pad_square

PARTS = ["hair", "headwear", "face", "eyes", "eyewear", "ears", "earwear", "nose", "mouth", "neck",
         "neckwear", "topwear", "handwear", "bottomwear", "legwear", "footwear", "tail", "wings", "objects"]

# Where two labels claim the same pixel, the earlier one here wins. Small
# features come first so that broad areas do not swallow them.
PRIORITY = ["eyes", "mouth", "nose", "eyewear", "headwear", "hair", "earwear", "ears", "face", "neck",
            "handwear", "neckwear", "topwear", "bottomwear", "legwear", "footwear", "tail", "wings", "objects"]

# How far a hidden part is extended under the part covering it, in pixels,
# as a share of the character's height.
UNDERLAP_SHARE = 0.016
# Labelled areas smaller than this share of their part are treated as stray.
STRAY_SHARE = 0.03


def silhouette(alpha, masks):
    """The character's outline: the picture's transparency if it has any, otherwise the labels' extent."""
    if (alpha < 128).mean() > 0.02:
        return alpha > 128, "transparency"
    union = masks.any(axis=0)
    union = ndimage.binary_fill_holes(ndimage.binary_closing(union, iterations=3))
    return union, "labels"


def label_map(masks, body):
    """One label per character pixel: by priority where labels overlap, nearest label where there is none."""
    order = [PARTS.index(name) for name in PRIORITY]
    labels = np.full(body.shape, -1, np.int16)
    for index in reversed(order):
        labels[masks[index] & body] = index
    unlabelled = body & (labels < 0)
    if unlabelled.any() and (labels >= 0).any():
        idx = ndimage.distance_transform_edt(labels < 0, return_distances=False, return_indices=True)
        labels[unlabelled] = labels[idx[0][unlabelled], idx[1][unlabelled]]
    labels[~body] = -1
    return labels, int(unlabelled.sum())


def drop_strays(mask):
    """Remove specks that are far smaller than the part they claim to belong to."""
    labelled, count = ndimage.label(mask)
    if count <= 1:
        return mask
    sizes = ndimage.sum(mask, labelled, range(1, count + 1))
    keep = np.nonzero(sizes >= STRAY_SHARE * sizes.max())[0] + 1
    return np.isin(labelled, keep)


def eye_parts(rgb, eye):
    """Divide one eye into white, iris and lash line by brightness."""
    value = rgb.max(axis=-1).astype(np.int32)
    chroma = value - rgb.min(axis=-1).astype(np.int32)
    white = eye & (rgb.min(axis=-1) > 185) & (chroma < 45)
    lash = eye & ~white & (value < 105)
    return {"eye_white": white, "pupil": eye & ~white & ~lash, "eye": lash}


def split(image, masks):
    rgba = np.asarray(image.convert("RGBA"))
    rgb, alpha = rgba[..., :3], rgba[..., 3]
    if masks.shape != (len(PARTS),) + alpha.shape:
        raise ValueError("the labels do not match the picture's size")
    body, outline_source = silhouette(alpha, masks)
    if not body.any():
        raise ValueError("no character was found in the picture")
    h, w = body.shape
    rows = np.nonzero(body.any(axis=1))[0]
    height = int(rows[-1] - rows[0] + 1)
    underlap = max(4, int(round(UNDERLAP_SHARE * height)))
    labels, relabelled = label_map(masks, body)
    report = {"outline_from": outline_source, "pixels_given_nearest_label": relabelled, "warnings": []}
    warn = report["warnings"].append

    def part(*names):
        out = np.zeros_like(body)
        for name in names:
            out |= labels == PARTS.index(name)
        return out

    # --- head parts
    hair = part("hair", "headwear")
    face_skin = part("face", "nose", "ears", "earwear", "eyewear")
    eyes = drop_strays(part("eyes")) if part("eyes").any() else part("eyes")
    mouth = drop_strays(part("mouth")) if part("mouth").any() else part("mouth")
    face = face_skin | part("eyes") | part("mouth")
    if not face.any():
        raise ValueError("no face was found; the picture may not show a character from the front")
    if not hair.any():
        warn("no hair was found; the head will move as one piece")

    # Left and right eye, by which side of the face's middle they sit on.
    face_x = np.nonzero(face.any(axis=0))[0]
    middle = (face_x[0] + face_x[-1]) / 2.0
    eye_labels, eye_count = ndimage.label(eyes)
    sides = {"l": np.zeros_like(body), "r": np.zeros_like(body)}
    for index in range(1, eye_count + 1):
        blob = eye_labels == index
        centre = np.nonzero(blob)[1].mean()
        sides["l" if centre < middle else "r"] |= blob
    eye_layers = {}
    for side, name in (("l", "left"), ("r", "right")):
        if sides[side].any():
            eye_layers[side] = eye_parts(rgb, sides[side])
        else:
            warn("no %s eye was found (profile view, or hidden by hair); it will not blink" % name)
    if not mouth.any():
        warn("no mouth was found (hidden, or too small); it will not move with speech")

    # --- face base: eyes and mouth painted over in skin colour, and extended
    # under the hair across the span of the face
    plain_skin = part("face")
    skin_colour = np.median(rgb[plain_skin], axis=0) if plain_skin.any() else np.median(rgb[face], axis=0)
    face_span = convex_hull_mask(face) & body
    face_base_mask = face | (face_span & hair)
    face_rgb = rgb.copy()
    face_rgb[eyes | mouth | (face_base_mask & ~face)] = skin_colour.astype(np.uint8)

    # --- neck, extended up under the chin so a moving head never uncovers a gap
    neck = part("neck")
    neck_rgb = rgb.copy()
    neck_mask = neck.copy()
    if neck.any():
        under = face & ndimage.binary_dilation(neck, iterations=underlap)
        neck_rgb = fill_from_neighbours(rgb, neck, under)
        neck_mask = neck | under
    else:
        warn("no neck was found; the head is cut directly against the body")

    # --- arms: each separate area on its own side of the body
    arms = part("handwear")
    body_x = np.nonzero(body.any(axis=0))[0]
    centre_line = (body_x[0] + body_x[-1]) / 2.0
    arm_sides = {"l": np.zeros_like(body), "r": np.zeros_like(body)}
    merged = np.zeros_like(body)
    arm_labels, arm_count = ndimage.label(arms)
    for index in range(1, arm_count + 1):
        blob = arm_labels == index
        if blob.sum() < STRAY_SHARE * arms.sum():
            merged |= blob
            continue
        xs = np.nonzero(blob.any(axis=0))[0]
        if xs[0] < centre_line < xs[-1] and min(centre_line - xs[0], xs[-1] - centre_line) > 0.15 * (xs[-1] - xs[0]):
            merged |= blob            # crosses the body: both arms joined, or an arm across the chest
        else:
            arm_sides["l" if np.nonzero(blob)[1].mean() < centre_line else "r"] |= blob
    if merged.sum() > 0.3 * max(int(arms.sum()), 1):
        warn("the arms are joined or lie across the body; they stay part of the body and will not move separately")
    elif not arms.any():
        warn("no arms were found; arm gestures are unavailable")

    # --- everything else is the body, extended a little under what covers it
    rest = body & ~hair & ~face & ~neck & ~arm_sides["l"] & ~arm_sides["r"]
    covering = body & ~rest
    covered = covering & ndimage.binary_dilation(rest, iterations=underlap)
    rest_rgb = fill_from_neighbours(rgb, rest, covered)
    rest_mask = rest | covered

    def layer(mask, colours=rgb):
        out = np.zeros((h, w, 4), np.uint8)
        out[..., :3] = colours
        out[..., 3] = np.where(mask, np.where(body, np.maximum(alpha, 1), 255), 0)
        if outline_source == "labels":
            out[..., 3] = np.where(mask, 255, 0)
        out[~mask] = 0
        return out

    layers = [("torso", layer(rest_mask, rest_rgb)), ("neck", layer(neck_mask, neck_rgb)),
              ("arm_l", layer(arm_sides["l"])), ("arm_r", layer(arm_sides["r"])),
              ("face_base", layer(face_base_mask, face_rgb))]
    for role in ("eye_white", "pupil", "eye"):
        for side in ("l", "r"):
            if side in eye_layers:
                layers.append(("%s_%s" % (role, side), layer(eye_layers[side][role])))
    layers += [("mouth", layer(mouth)), ("hair_front", layer(hair))]
    layers = [(role, array) for role, array in layers if array[..., 3].any()]

    found = sorted({PARTS[i] for i in np.unique(labels) if i >= 0})
    report["parts_found"] = found
    report["layers"] = [role for role, _ in layers]
    # What the character can do, for the animation system to read.
    report["capabilities"] = {
        "blink": bool(eye_layers),
        "speak": bool(mouth.any()),
        "head_turn": True,
        "hair_sway": bool(hair.any()),
        "arm_left": bool(arm_sides["l"].any()),
        "arm_right": bool(arm_sides["r"].any()),
        "legs": "legwear" in found or "footwear" in found,
    }
    assigned = (hair.astype(np.int32) + face.astype(np.int32) + neck.astype(np.int32)
                + arm_sides["l"].astype(np.int32) + arm_sides["r"].astype(np.int32) + rest.astype(np.int32))
    report["unassigned_pixels"] = int((body & (assigned == 0)).sum())
    report["doubly_assigned_pixels"] = int((assigned > 1).sum())
    return layers, report


ORDER = {"torso": 10, "neck": 14, "arm_l": 16, "arm_r": 17, "face_base": 24, "eye_white_l": 30, "eye_white_r": 31,
         "pupil_l": 40, "pupil_r": 41, "eye_l": 50, "eye_r": 51, "mouth": 60, "hair_front": 80}


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    image = Image.open(argv[1])
    masks = np.load(argv[2])["masks"]
    try:
        layers, report = split(image, masks)
    except ValueError as error:
        print("cannot split this picture: %s" % error, file=sys.stderr)
        return 1
    os.makedirs(argv[3], exist_ok=True)
    for old in os.listdir(argv[3]):
        if old.endswith(".png"):
            os.remove(os.path.join(argv[3], old))
    for role, array in layers:
        Image.fromarray(pad_square(array), "RGBA").save(os.path.join(argv[3], "%02d_%s.png" % (ORDER[role], role)))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
