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
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

from flatsplit import convex_hull_mask, pad_square

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
# The neck under the face: its width when no neck was found (share of face
# width), and how much wider than the neck it is at the chin.
NECK_SHARE = 0.36
NECK_WIDEN = 1.25


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


def hair_over_eyes(rgb, masks, labels):
    """Fringe hair the model also marked as eye goes back to the hair.

    On small faces the eye labels are rough boxes that take in strands of
    fringe lying over the eyes. Those strands belong to the hair: left with
    the eye, they would vanish when it blinks and leave the box's edge
    visible. A pixel marked both eye and hair goes to the hair when it has
    the hair's colour.
    """
    eye_i, hair_i = PARTS.index("eyes"), PARTS.index("hair")
    hair_only = labels == hair_i
    both = masks[eye_i] & masks[hair_i] & (labels == eye_i)
    if not both.any() or hair_only.sum() < 20:
        return labels
    colour = np.median(rgb[hair_only].astype(np.float32), axis=0)
    near = np.abs(rgb.astype(np.float32) - colour).max(axis=-1) < 40
    out = labels.copy()
    out[both & near] = hair_i
    return out


def drop_strays(mask):
    """Remove specks that are far smaller than the part they claim to belong to."""
    labelled, count = ndimage.label(mask)
    if count <= 1:
        return mask
    sizes = ndimage.sum(mask, labelled, range(1, count + 1))
    keep = np.nonzero(sizes >= STRAY_SHARE * sizes.max())[0] + 1
    return np.isin(labelled, keep)


def soft_fill(rgb, known, wanted, radius):
    """Colour hidden pixels from the visible ones next to them, smoothly.

    Copying the nearest visible pixel draws streaks and drags dark outlines
    inwards, which shows when a part moves and uncovers the fill. So the fill
    is taken from slightly inside the visible area, then blurred.
    """
    out = rgb.copy()
    if not known.any() or not wanted.any():
        return out
    core = ndimage.binary_erosion(known, iterations=2)
    if core.sum() < 0.3 * known.sum():
        core = known
    idx = ndimage.distance_transform_edt(~core, return_distances=False, return_indices=True)
    filled = rgb[idx[0], idx[1]].astype(np.float32)
    area = (wanted | core).astype(np.float32)
    sigma = max(1.5, radius / 3.0)
    weight = ndimage.gaussian_filter(area, sigma)
    for c in range(3):
        blurred = ndimage.gaussian_filter(filled[..., c] * area, sigma)
        out[..., c][wanted] = np.clip(blurred[wanted] / np.maximum(weight[wanted], 1e-6), 0, 255).astype(np.uint8)
    return out


def shadow_colour(rgb, mask, darken=0.92):
    """A part's typical colour without its outline, a little darker, for areas in shadow."""
    pixels = rgb[mask].astype(np.float32)
    if len(pixels) == 0:
        return np.array([200, 160, 140], np.float32)
    lum = pixels.mean(axis=1)
    lo, hi = np.percentile(lum, 30), np.percentile(lum, 90)
    middle = pixels[(lum >= lo) & (lum <= hi)]
    return np.median(middle if len(middle) else pixels, axis=0) * darken


def neck_column(face, hair, neck, eye_line, face_width):
    """Where the neck continues up under the face, so a moving head uncovers neck, not a hole.

    Shaped like a neck going up into the head: as wide as the jaw at the eye
    line, where the cheeks hide it, narrowing to a little wider than the
    neck at the chin, where a turning or rising head uncovers it. A square
    column as wide as the jaw showed its corners beside the neck as a block.
    It runs from the eye line down and only where the face or hair hides it.
    """
    h, w = face.shape
    face_rows = np.nonzero(face.any(axis=1))[0]
    chin = face_rows[-1]
    face_height = chin - face_rows[0] + 1
    lower = face[max(chin - int(0.45 * face_height), 0):chin + 1]
    xs = np.nonzero(lower.any(axis=0))[0]
    jaw_half = (xs[-1] - xs[0]) / 2.0
    centre = (xs[0] + xs[-1]) / 2.0
    neck_half = NECK_SHARE * face_width / 2.0
    if neck.any():
        rows = np.nonzero(neck.any(axis=1))[0]
        top = rows[0] + max(1, (rows[-1] - rows[0]) // 4)
        nx = np.nonzero(neck[rows[0]:top + 1].any(axis=0))[0]
        centre, neck_half = (nx[0] + nx[-1]) / 2.0, (nx[-1] - nx[0]) / 2.0
    yy, xx = np.mgrid[0:h, 0:w]
    t = np.clip((yy - eye_line) / max(chin - eye_line, 1), 0.0, 1.0)
    t = t * t * (3.0 - 2.0 * t)
    half = jaw_half + (NECK_WIDEN * neck_half - jaw_half) * t
    column = (np.abs(xx - centre) <= half) & (yy >= eye_line)
    return column & (face | hair)


def feature_rim(rgb, feature, skin, reach, skin_colour):
    """Drawn pixels just outside a feature's label, which belong with the feature.

    The model's eye and mouth labels often stop a pixel or two short of the
    drawing: dark lashes, or a light lower-lid line. Left on the face, those
    pixels show as a ghost of the open eye when the eye closes. Anything near
    the feature that is clearly not plain skin goes with the feature.
    """
    if not feature.any():
        return np.zeros_like(feature)
    ring = ndimage.binary_dilation(feature, iterations=reach) & skin & ~feature
    differs = np.abs(rgb.astype(np.int32) - np.asarray(skin_colour, np.int32)).max(axis=-1) > 45
    return ring & differs


def upper_lash(dark, limit):
    """Top row and thickness of the upper lash line in each column of an eye."""
    columns, tops, widths = [], [], []
    for x in np.nonzero(dark.any(axis=0))[0]:
        ys = np.nonzero(dark[:, x])[0]
        top, end = ys[0], ys[0]
        for y in ys[1:]:
            if y - end > 2 or y - top >= limit:
                break
            end = y
        columns.append(x)
        tops.append(top)
        widths.append(end - top + 1)
    return np.array(columns), np.array(tops, float), np.array(widths, float)


def closed_eye(rgb, region, dark):
    """A closed eye: a smooth lid line in the eye's own lash colour and weight.

    It spans the eye's lash line, sits where the lid meets the lower lash,
    curves gently upwards at the corners and tapers at both ends. Returns an
    RGBA layer, empty if the eye has no lash line to measure.
    """
    from PIL import ImageDraw

    h, w = region.shape
    out = np.zeros((h, w, 4), np.uint8)
    if dark.sum() < 6:
        return out
    rows = np.nonzero(region.any(axis=1))[0]
    top, height = rows[0], rows[-1] - rows[0] + 1
    xs = np.nonzero(dark)[1]
    left, right = np.percentile(xs, 3), np.percentile(xs, 97)
    width = right - left
    if width < 3:
        return out
    _, _, runs = upper_lash(dark, max(2, int(0.3 * height)))
    weight = float(np.clip(np.median(runs), 1.2, max(1.2, 0.16 * height)))
    pixels = rgb[dark].astype(np.float32)
    lum = pixels.mean(axis=1)
    colour = tuple(int(c) for c in pixels[lum <= np.percentile(lum, 25)].mean(axis=0))

    s = 4
    pad = int(weight) + 3
    x0, y0 = int(left) - pad, int(top + 0.62 * height - 0.15 * width) - pad
    big = Image.new("L", ((int(width) + 2 * pad) * s, (int(0.3 * width) + 2 * pad + 2) * s), 0)
    pen = ImageDraw.Draw(big)
    steps = 32
    upper, lower = [], []
    for i in range(steps + 1):
        t = -1 + 2 * i / steps
        x = (left - x0 + width * i / steps) * s
        y = (top + 0.62 * height - y0 + 0.12 * width * (1 - t * t) - 0.06 * width) * s
        half = 0.5 * weight * s * (1 - 0.65 * t ** 4)
        upper.append((x, y - half))
        lower.append((x, y + half))
    pen.polygon(upper + lower[::-1], fill=255)
    alpha = np.asarray(big.resize((big.width // s, big.height // s), Image.BOX))
    ys = slice(max(y0, 0), min(y0 + alpha.shape[0], h))
    xs_ = slice(max(x0, 0), min(x0 + alpha.shape[1], w))
    patch = alpha[ys.start - y0:ys.stop - y0, xs_.start - x0:xs_.stop - x0]
    out[ys, xs_, 0], out[ys, xs_, 1], out[ys, xs_, 2] = colour
    out[ys, xs_, 3] = patch
    out[out[..., 3] == 0] = 0
    return out


def open_mouth(shape, centre_x, line_y, width, lip_colour):
    """An open, talking mouth in the character's lip colour, hidden until the mouth opens.

    A dark interior with a flat top edge and a round bottom, a band of upper
    teeth and a tongue, outlined in the lip colour. Returns an RGBA layer.
    """
    import colorsys
    from PIL import ImageDraw

    s = 4
    width = max(width, 4.0)
    height = 0.7 * width
    pad = 3
    big_w, big_h = int((width + 2 * pad) * s), int((height + 2 * pad) * s)
    r, g, b = [c / 255.0 for c in lip_colour]
    hue, sat, val = colorsys.rgb_to_hsv(r, g, b)
    if sat < 0.35 or 0.08 < hue < 0.85:
        hue = 0.985                    # a brown, grey or black line: a plain red mouth inside
    tone = lambda h_, sv: tuple(int(255 * c) for c in colorsys.hsv_to_rgb(h_, *sv))
    cavity, tongue, teeth = tone(hue, (0.7, 0.38)), tone(0.97, (0.45, 0.85)), (252, 250, 248)
    outline = tuple(int(c) for c in lip_colour)

    def edge(u):
        top = 0.15 * height * (2 * u - 1) ** 2
        bottom = 0.15 * height + 0.85 * height * math.sqrt(max(0.0, 1 - (2 * u - 1) ** 2))
        return top, bottom

    steps = 40
    upper = [(pad + width * i / steps, pad + edge(i / steps)[0]) for i in range(steps + 1)]
    lower = [(pad + width * i / steps, pad + edge(i / steps)[1]) for i in range(steps, -1, -1)]
    outline_pts = [(x * s, y * s) for x, y in upper + lower]
    shape_mask = Image.new("L", (big_w, big_h), 0)
    ImageDraw.Draw(shape_mask).polygon(outline_pts, fill=255)
    art = Image.new("RGBA", (big_w, big_h), cavity + (255,))
    pen = ImageDraw.Draw(art)
    tongue_box = [(pad + 0.2 * width) * s, (pad + 0.62 * height) * s, (pad + 0.8 * width) * s, (pad + 1.25 * height) * s]
    pen.ellipse(tongue_box, fill=tongue + (255,))
    teeth_pts = [(x * s, y * s) for x, y in upper if pad + 0.12 * width <= x <= pad + 0.88 * width]
    teeth_pts += [(x, y + 0.17 * height * s) for x, y in reversed(teeth_pts)]
    if len(teeth_pts) >= 3:
        pen.polygon(teeth_pts, fill=teeth + (255,))
    art.putalpha(shape_mask)
    stroke = max(1, int(round(0.07 * width * s)))
    ImageDraw.Draw(art).line(outline_pts + [outline_pts[0]], fill=outline + (255,), width=stroke, joint="curve")
    small = np.asarray(art.resize((big_w // s, big_h // s), Image.BOX))
    out = np.zeros(shape + (4,), np.uint8)
    x0 = int(round(centre_x - width / 2.0 - pad))
    y0 = int(round(line_y - pad))
    ys = slice(max(y0, 0), min(y0 + small.shape[0], shape[0]))
    xs = slice(max(x0, 0), min(x0 + small.shape[1], shape[1]))
    out[ys, xs] = small[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
    return out


def find_mouth(rgb, face_skin, eye_centres, chin, skin_value):
    """Look for a mouth line the model missed: dark pixels where a mouth belongs."""
    (lx, ly), (rx, ry) = eye_centres
    span = abs(rx - lx)
    eye_y = (ly + ry) / 2.0
    expected = eye_y + 0.64 * (chin - eye_y)
    h, w = face_skin.shape
    yy, xx = np.mgrid[0:h, 0:w]
    window = (np.abs(xx - (lx + rx) / 2.0) <= 0.45 * span) & (np.abs(yy - expected) <= 0.16 * (chin - eye_y))
    dark = window & face_skin & (rgb.max(axis=-1) < 0.72 * skin_value)
    if dark.sum() >= 3:
        labelled, count = ndimage.label(dark)
        sizes = ndimage.sum(dark, labelled, range(1, count + 1))
        return labelled == (int(np.argmax(sizes)) + 1), expected
    return np.zeros_like(face_skin), expected


def eye_parts(rgb, eye):
    """Divide one eye into white, iris and lash line by brightness (used to measure the lash)."""
    value = rgb.max(axis=-1).astype(np.int32)
    chroma = value - rgb.min(axis=-1).astype(np.int32)
    white = eye & (rgb.min(axis=-1) > 185) & (chroma < 45)
    lash = eye & ~white & (value < 105)
    return {"eye_white": white, "pupil": eye & ~white & ~lash, "eye": lash}


def split(image, masks, invented=None):
    """Cut the picture into layers. Returns (layers, report).

    If `invented` is a dict, it is filled with role -> mask of the pixels this
    function made up (filled in under other parts) rather than copied from
    the picture. reveal.py uses them to measure how much made-up filling a
    pose uncovers. The closed eyes and open mouth are left out: showing them
    is intended.
    """
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
    labels = hair_over_eyes(rgb, masks, labels)
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

    # Take in the dark outline just outside the eye and mouth labels.
    skin_value = float(np.median(rgb[part("face")].max(axis=-1))) if part("face").any() else 230.0
    plain_colour = np.median(rgb[part("face")], axis=0) if part("face").any() else np.median(rgb[face], axis=0)
    face_size = np.nonzero(face.any(axis=0))[0]
    reach = max(2, int(round(0.025 * (face_size[-1] - face_size[0] + 1))))
    eye_rim = feature_rim(rgb, eyes, face_skin, reach, plain_colour)
    mouth = mouth | feature_rim(rgb, mouth, face_skin, reach, plain_colour)

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
            near = ndimage.binary_dilation(sides[side], iterations=reach + 1)
            rim = eye_rim & near
            # One solid layer per eye: split into white, iris and lash, a small
            # eye becomes scattered pixels that the rigger's meshes partly drop.
            # The lash line is still measured, to draw the closed eye from.
            eye_layers[side] = {"all": sides[side] | rim, "lash": eye_parts(rgb, sides[side])["eye"] | rim}
        else:
            warn("no %s eye was found (profile view, or hidden by hair); it will not blink" % name)
    chin = int(np.nonzero(face.any(axis=1))[0][-1])
    drawn_mouth = False
    if not mouth.any() and len(eye_layers) == 2:
        centres = [tuple(np.argwhere(sides[side]).mean(axis=0)[::-1]) for side in ("l", "r")]
        found, expected = find_mouth(rgb, face_skin, centres, chin, skin_value)
        if found.any():
            mouth = found
            warn("the mouth was found by its colour, not by the model; check that it moves in the right place")
        else:
            span = abs(centres[1][0] - centres[0][0])
            yy, xx = np.mgrid[0:h, 0:w]
            half = max(1.5, 0.22 * span)
            mouth = (np.abs(xx - (centres[0][0] + centres[1][0]) / 2.0) <= half) & (np.abs(yy - expected) <= 0.5) & face
            drawn_mouth = True
            warn("no mouth was found; a small one was added so the character can talk")
    elif not mouth.any():
        warn("no mouth was found (hidden, or the face is turned away); it will not move with speech")

    # --- face base: eyes and mouth painted over in skin colour, and extended
    # under the hair across the span of the face
    plain_skin = part("face")
    skin_colour = np.median(rgb[plain_skin], axis=0) if plain_skin.any() else np.median(rgb[face], axis=0)
    face_span = convex_hull_mask(face) & body
    face_base_mask = face | (face_span & hair)
    face_rgb = rgb.copy()
    # Painted over from the skin around them, so the face under a closed eye
    # or an open mouth keeps its own shading.
    # Only the drawn pixels of each feature are painted over: plain skin inside
    # the model's blocky labels is kept, so no outline of the label shows
    # round an open eye when the picture is magnified.
    differs = np.abs(rgb.astype(np.int32) - plain_colour.astype(np.int32)).max(axis=-1) > 35

    def drawn(region):
        return ndimage.binary_dilation(region & differs, iterations=1) & region

    hidden = drawn(eyes | eye_rim) | drawn(mouth)
    face_rgb = soft_fill(rgb, face & ~hidden & ~hair, hidden | (face_base_mask & ~face), 2 * reach)

    # --- neck, continued up under the face so a turning or tilting head
    # uncovers neck rather than a hole or a smear
    neck = part("neck")
    if not neck.any():
        warn("no neck was found; a plain one is added under the face")
    face_rows = np.nonzero(face.any(axis=1))[0]
    eye_rows = np.nonzero(eyes.any(axis=1))[0]
    eye_line = int(eye_rows.mean()) if len(eye_rows) else int(face_rows[0] + 0.5 * (face_rows[-1] - face_rows[0]))
    face_width = int(face_x[-1] - face_x[0] + 1)
    under = neck_column(face, hair, neck, eye_line, face_width)
    if neck.any():
        under |= face & ndimage.binary_dilation(neck, iterations=underlap)
    under &= ~neck
    neck_rgb = rgb.copy()
    colour = shadow_colour(rgb, neck) if neck.any() else shadow_colour(rgb, plain_skin if plain_skin.any() else face, 0.82)
    neck_rgb[under] = colour.astype(np.uint8)
    neck_mask = neck | under

    # --- hair behind the head, as Live2D artists draw it: under everything the face and the hair round
    # it cover, down to the cheeks, in the hair's colours. Hidden at rest; a turning face uncovers hair
    # there, as on a real head, rather than the background.
    cheek_line = int(eye_line + 0.5 * (chin - eye_line))
    above = np.zeros_like(body)
    above[:cheek_line] = True
    head_hair = hair & above
    back_mask = (face | head_hair) & above if head_hair.any() else np.zeros_like(body)
    # Long hair hangs beside the jaw: it carries on down behind the jaw's sides to just below the chin,
    # beside the neck, so a jaw moving off it uncovers hair. Short hair leaves the background there.
    below_chin = int(chin + 0.12 * (chin - eye_line))
    lower = np.zeros_like(body)
    lower[cheek_line:below_chin] = True
    if head_hair.any() and (hair & lower & ~face).sum() > 0.02 * hair.sum():
        back_mask |= (face | hair) & lower & ~ndimage.binary_dilation(neck_mask, iterations=2)
    # In the hair's shadow tone, as back hair is drawn: blurring the visible hair into it averaged
    # highlights and outlines into a flat grey or a pale patch.
    back_rgb = rgb.copy()
    if back_mask.any():
        back_rgb[back_mask & ~head_hair] = shadow_colour(rgb, head_hair, 0.8).astype(np.uint8)

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
    rest_rgb = soft_fill(rgb, rest, covered, underlap)
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
              ("hair_back", layer(back_mask, back_rgb)),
              ("face_base", layer(face_base_mask, face_rgb))]
    for side in ("l", "r"):
        if side in eye_layers:
            layers.append(("eye_" + side, layer(eye_layers[side]["all"])))
    for side in ("l", "r"):
        if side in eye_layers:
            closed = closed_eye(rgb, eye_layers[side]["all"], eye_layers[side]["lash"])
            if closed[..., 3].any():
                layers.append(("eye_closed_" + side, closed))
            else:
                warn("the %s eye has no clear lash line; its blink will be a plain squash" % ("left" if side == "l" else "right"))

    # --- the mouth line, and an open mouth hidden until the character speaks
    mouth_rgb = rgb.copy()
    if mouth.any():
        if drawn_mouth:
            mouth_rgb[mouth] = (shadow_colour(rgb, plain_skin if plain_skin.any() else face, 0.55)
                                * np.array([1.0, 0.8, 0.8])).astype(np.uint8)
        ys, xs = np.nonzero(mouth)
        lip = mouth_rgb[mouth].astype(np.float32)
        lum = lip.mean(axis=1)
        lip_colour = lip[lum <= np.percentile(lum, 35)].mean(axis=0)
        width = float(np.clip(xs.max() - xs.min() + 1, 0.13 * face_width, 0.28 * face_width))
        layers.append(("mouth_cavity", open_mouth((h, w), (xs.min() + xs.max()) / 2.0, ys.mean(), width, lip_colour)))
    layers += [("mouth", layer(mouth, mouth_rgb)), ("hair_front", layer(hair))]
    layers = [(role, array) for role, array in layers if array[..., 3].any()]
    if invented is not None:
        invented["torso"] = covered & ~rest
        invented["neck"] = under & ~neck
        invented["face_base"] = (hidden | (face_base_mask & ~face)) & face_base_mask

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


# Layers drawn for poses the picture does not show; the rig keeps them hidden at rest.
HIDDEN_AT_REST = ("eye_closed_l", "eye_closed_r", "mouth_cavity")

ORDER = {"eye_closed_l": 52, "eye_closed_r": 53, "mouth_cavity": 58,
         "torso": 10, "neck": 14, "arm_l": 16, "arm_r": 17, "hair_back": 20, "face_base": 24,
         "eye_white_l": 30, "eye_white_r": 31,
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
