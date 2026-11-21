#!/usr/bin/env python3
"""Split a flat character illustration into named layers without repainting it.

Anime-style art is flat colours inside outlines, so the parts of a character
can be found by colour and position from a few points marked on the picture.
Every output pixel is either copied from the original or, where one part
hides another, filled with the neighbouring colour. Nothing is generated, so
ornaments and clothing cannot be lost or altered; the cost is that parts can
only move a little before the fill shows.

Input:  an image with a transparent background, and a marks file:

    {
      "skin":  [x, y],                  a point on the face skin
      "hair":  [[x, y], ...],           one or more points on the hair
      "eyes":  {"l": [cx, cy, rx, ry],  centre and half-size of each eye;
                "r": [cx, cy, rx, ry]}, "l" is the one on the viewer's left
      "mouth": [cx, cy, rx, ry]
    }

Output: a folder of full-canvas layers named `{order}_{role}.png`, the input
format of the image2live2d rigger.

Usage: flatsplit.py IMAGE MARKS.json OUT_DIR
"""
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

# How close a colour must be to a marked colour to count as the same paint.
SKIN_TOLERANCE = 30.0
HAIR_TOLERANCE = 34.0
# How far outlines are absorbed into the part they border, in pixels.
OUTLINE_REACH = 2
# How far a hidden part is extended under the part covering it, in pixels.
UNDERLAP = 14


def colour_distance(rgb, colour):
    return np.sqrt(((rgb.astype(np.float32) - np.asarray(colour, np.float32)) ** 2).sum(axis=-1))


def sample_colour(rgb, mask, point, radius=2):
    x, y = int(round(point[0])), int(round(point[1]))
    ys, xs = slice(max(0, y - radius), y + radius + 1), slice(max(0, x - radius), x + radius + 1)
    pixels = rgb[ys, xs][mask[ys, xs]]
    if len(pixels) == 0:
        raise ValueError("mark at (%d, %d) is not on the character" % (x, y))
    return np.median(pixels, axis=0)


def connected_to(mask, points):
    """Keep only the regions of `mask` that contain one of the points."""
    labels, _ = ndimage.label(mask)
    keep = np.zeros_like(mask)
    for x, y in points:
        x, y = int(round(x)), int(round(y))
        label = labels[y, x]
        if label == 0:
            # Allow a mark that landed on an outline right next to the region.
            window = labels[max(0, y - 3):y + 4, max(0, x - 3):x + 4]
            found = window[window > 0]
            if len(found) == 0:
                raise ValueError("mark at (%d, %d) does not touch a matching region" % (x, y))
            label = np.bincount(found).argmax()
        keep |= labels == label
    return keep


def flat_paint(rgb, body, colours=48, min_thickness=2.5):
    """Mark pixels that belong to flat areas of paint, as opposed to outlines.

    A pixel is flat paint when it is part of a same-colour area that is, at
    its thickest, wider than an outline. Colours are reduced to a small
    palette first so that slight variation does not break areas up.
    """
    image = Image.fromarray(rgb, "RGB").quantize(colors=colours, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    index = np.asarray(image)
    fill = np.zeros_like(body)
    for colour in np.unique(index[body]):
        mask = body & (index == colour)
        if mask.sum() < 12:
            continue
        thick = ndimage.distance_transform_edt(mask) >= min_thickness
        if not thick.any():
            continue
        labels, _ = ndimage.label(mask)
        keep = np.unique(labels[thick])
        fill |= np.isin(labels, keep[keep > 0])
    return fill


def ellipse(shape, spec):
    cx, cy, rx, ry = spec
    yy, xx = np.mgrid[:shape[0], :shape[1]]
    return ((xx - cx) / max(rx, 1e-6)) ** 2 + ((yy - cy) / max(ry, 1e-6)) ** 2 <= 1.0


def fill_from_neighbours(rgb, known, wanted):
    """Colour the `wanted` pixels from the nearest `known` pixel."""
    out = rgb.copy()
    if not known.any():
        return out
    idx = ndimage.distance_transform_edt(~known, return_distances=False, return_indices=True)
    out[wanted] = rgb[idx[0][wanted], idx[1][wanted]]
    return out


def convex_hull_mask(mask):
    """Filled convex hull of a mask, by row/column interpolation of its extremes."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 3:
        return mask.copy()
    points = np.stack([xs, ys], axis=1).astype(np.float64)
    points = points[np.lexsort((points[:, 1], points[:, 0]))]

    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]

    def half(pts):
        hull = []
        for p in pts:
            while len(hull) >= 2 and cross(hull[-1] - hull[-2], p - hull[-2]) <= 0:
                hull.pop()
            hull.append(p)
        return hull

    lower, upper = half(points), half(points[::-1])
    hull = np.array(lower[:-1] + upper[:-1])
    from PIL import ImageDraw
    img = Image.new("L", (mask.shape[1], mask.shape[0]), 0)
    ImageDraw.Draw(img).polygon([tuple(p) for p in hull], fill=255)
    return np.asarray(img) > 0


def split(image, marks):
    rgba = np.asarray(image.convert("RGBA"))
    rgb, alpha = rgba[..., :3], rgba[..., 3]
    body = alpha > 128
    h, w = body.shape
    report = {}
    if body.mean() > 0.98:
        raise ValueError("the picture has no transparent background; run prepare.py on it first")

    # --- which pixels are flat paint and which are outlines or fine detail
    fill = flat_paint(rgb, body)
    lines = body & ~fill
    report["outline_share"] = round(float(lines.sum()) / max(int(body.sum()), 1), 3)

    # --- hair: paint matching the marked hair colours, plus the outlines along
    # it, kept only where joined to a mark. Outlines go to the hair because the
    # hair is drawn on top of what it borders.
    hair_points = marks["hair"]
    hair_paint = np.zeros_like(body)
    for point in hair_points:
        hair_paint |= body & (colour_distance(rgb, sample_colour(rgb, body, point)) < HAIR_TOLERANCE)
    # The marked eye and mouth areas belong to the face: an eyelash touching
    # the fringe must not be taken as a hair outline.
    marked = ellipse(body.shape, marks["mouth"])
    for side in ("l", "r"):
        marked |= ellipse(body.shape, marks["eyes"][side])
    marked &= body
    hair = hair_paint | (lines & ndimage.binary_dilation(hair_paint, iterations=OUTLINE_REACH) & ~marked)
    hair = connected_to(hair, hair_points)

    # --- face skin: the skin-coloured region under the mark. The face is the
    # area that skin spans (its convex hull), so eyes that touch the fringe
    # are still inside it; hair lying across it stays hair.
    skin_colour = sample_colour(rgb, body, marks["skin"])
    skin_like = body & (colour_distance(rgb, skin_colour) < SKIN_TOLERANCE)
    skin = connected_to(skin_like, [marks["skin"]])
    face_span = (convex_hull_mask(skin) | marked) & body
    face = face_span & ~hair

    # Hair also takes anything it fully encloses together with the face
    # (ornaments worn in the hair), but never the face itself.
    hair = (ndimage.binary_fill_holes(hair | face) & body) & ~face
    hair = connected_to(hair, hair_points)

    # --- eyes and mouth, inside the face only
    features = face & ~skin_like
    eye_parts = {}
    for side in ("l", "r"):
        zone = ellipse(body.shape, marks["eyes"][side]) & features
        value = rgb.max(axis=-1).astype(np.int32)
        chroma = value - rgb.min(axis=-1).astype(np.int32)
        white = zone & (rgb.min(axis=-1) > 190) & (chroma < 40)
        lash = zone & ~white & (value < 110)
        pupil = zone & ~white & ~lash
        eye_parts[side] = {"eye_white": white, "pupil": pupil, "eye": lash}
        report["eye_%s_pixels" % side] = {k: int(v.sum()) for k, v in eye_parts[side].items()}
    mouth = ellipse(body.shape, marks["mouth"]) & features
    report["mouth_pixels"] = int(mouth.sum())

    removed_from_face = mouth.copy()
    for parts in eye_parts.values():
        for part in parts.values():
            removed_from_face |= part

    # --- face base: the face with eyes and mouth painted over in skin colour,
    # extended under the hair so moving hair uncovers skin, not a hole

    # --- everything else is the body. Scraps cut off from it (bits of outline
    # left around the head) go to the part they touch, so they move with it.
    rest = body & ~hair & ~face
    labels, count = ndimage.label(rest)
    if count > 1:
        sizes = ndimage.sum(rest, labels, range(1, count + 1))
        main = int(np.argmax(sizes)) + 1
        near_hair = ndimage.binary_dilation(hair, iterations=OUTLINE_REACH + 1)
        near_face = ndimage.binary_dilation(face, iterations=OUTLINE_REACH + 1)
        moved = 0
        for label in range(1, count + 1):
            if label == main or sizes[label - 1] > 0.002 * body.sum():
                continue
            scrap = labels == label
            if (scrap & near_hair).any():
                hair |= scrap
            elif (scrap & near_face).any():
                face |= scrap
            else:
                continue
            moved += int(sizes[label - 1])
        rest = body & ~hair & ~face
        report["scrap_pixels_reassigned"] = moved
    face_base_mask = face | (face_span & hair)
    face_rgb = rgb.copy()
    face_rgb[removed_from_face | (face_base_mask & ~face)] = skin_colour.astype(np.uint8)

    covered = (hair | face) & ndimage.binary_dilation(rest, iterations=UNDERLAP)
    rest_rgb = fill_from_neighbours(rgb, rest, covered)
    rest_mask = rest | covered

    def layer(mask, colours=rgb):
        out = np.zeros((h, w, 4), np.uint8)
        out[..., :3] = colours
        out[..., 3] = np.where(mask, np.maximum(alpha, 255 * (mask & ~body)), 0)
        out[~mask] = 0
        return out

    layers = [
        ("torso", layer(rest_mask, rest_rgb)),
        ("face_base", layer(face_base_mask, face_rgb)),
        ("eye_white_l", layer(eye_parts["l"]["eye_white"])),
        ("eye_white_r", layer(eye_parts["r"]["eye_white"])),
        ("pupil_l", layer(eye_parts["l"]["pupil"])),
        ("pupil_r", layer(eye_parts["r"]["pupil"])),
        ("eye_l", layer(eye_parts["l"]["eye"])),
        ("eye_r", layer(eye_parts["r"]["eye"])),
        ("mouth", layer(mouth)),
        ("hair_front", layer(hair)),
    ]
    for name, mask in (("hair", hair), ("face", face), ("body", rest)):
        report[name + "_pixels"] = int(mask.sum())
    # Every original pixel must land in exactly one layer's original area.
    assigned = hair.astype(np.int32) + face.astype(np.int32) + rest.astype(np.int32)
    report["unassigned_pixels"] = int((body & (assigned == 0)).sum())
    report["doubly_assigned_pixels"] = int((assigned > 1).sum())
    report["warnings"] = suitability_warnings(marks, body, hair, face, eye_parts, mouth)
    return layers, report


def suitability_warnings(marks, body, hair, face, eye_parts, mouth):
    """Plain-language reasons this picture is likely to give a poor puppet.

    The split always produces layers; these say when not to trust them.
    """
    warnings = []
    character = max(int(body.sum()), 1)
    face_size = max(int(face.sum()), 1)
    if hair.sum() > 0.45 * character:
        warnings.append("the hair selection covers most of the character; the hair is probably "
                        "the same colour as the clothing, so the body would move with the head")
    elif hair.sum() < 0.6 * face_size:
        warnings.append("very little hair was found; shaded or textured hair is not one colour, "
                        "so the hair will not move separately")
    left, right = marks["eyes"]["l"], marks["eyes"]["r"]
    dx, dy = right[0] - left[0], right[1] - left[1]
    tilt = abs(np.degrees(np.arctan2(dy, dx))) if dx else 90.0
    if tilt > 8:
        warnings.append("the face is tilted by about %d degrees; blink and mouth animation "
                        "assume an upright, front-facing face and will be misplaced" % round(tilt))
    if np.hypot(dx, dy) < 30:
        warnings.append("the face is very small (eyes %d pixels apart); details will be coarse"
                        % round(np.hypot(dx, dy)))
    for side, name in (("l", "left"), ("r", "right")):
        parts = eye_parts[side]
        total = sum(int(v.sum()) for v in parts.values())
        if total == 0:
            warnings.append("nothing was found in the %s eye mark" % name)
        elif parts["eye_white"].sum() < 0.05 * total:
            warnings.append("no white was found in the %s eye (narrow, shaded or closed eye); "
                            "the blink will look wrong" % name)
        elif parts["eye"].sum() > 0.6 * total:
            warnings.append("most of the %s eye was read as eyelash; the closed eye will be too heavy" % name)
    eye_area = np.pi * marks["mouth"][2] * marks["mouth"][3]
    if mouth.sum() > 0.45 * eye_area:
        warnings.append("the mouth looks open in the artwork; it will not close when the character is silent")
    return warnings


def pad_square(array):
    """Centre a layer on a square transparent canvas; the rigger expects square art."""
    h, w = array.shape[:2]
    side = max(h, w)
    out = np.zeros((side, side, 4), np.uint8)
    y, x = (side - h) // 2, (side - w) // 2
    out[y:y + h, x:x + w] = array
    return out


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    image = Image.open(argv[1])
    with open(argv[2], encoding="utf-8") as f:
        marks = json.load(f)
    try:
        layers, report = split(image, marks)
    except ValueError as error:
        print("cannot split this picture: %s" % error, file=sys.stderr)
        return 1
    os.makedirs(argv[3], exist_ok=True)
    for old in os.listdir(argv[3]):
        if old.endswith(".png"):
            os.remove(os.path.join(argv[3], old))
    order = 10
    for role, array in layers:
        if array[..., 3].any():
            Image.fromarray(pad_square(array), "RGBA").save(os.path.join(argv[3], "%02d_%s.png" % (order, role)))
        else:
            report.setdefault("empty_layers", []).append(role)
        order += 8
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
