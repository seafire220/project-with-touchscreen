#!/usr/bin/env python3
"""Measure what a pose uncovers: holes, made-up filling, and how far the head's outline moves.

    reveal.py PUPPET.inp [--invented DIR] [--out DIR] [--scale 0.5]

Draws the puppet's parts in software, at the exact positions Inox2D computes
(live2d_export.Puppet.world), in a set of poses, and compares each with the
rest pose:

  uncovered      area inside the character at rest, away from its edge, that
                 shows nothing in the pose: empty space left behind (it also
                 counts the outline itself moving, as in a tilt)
  holes          background enclosed by the character in the pose: gaps
  filler shown   area where the part on top shows made-up filling instead of
                 the picture (the skin-coloured patches). make_character.py
                 saves which pixels were made up in the work folder's
                 invented/ directory; pass it with --invented
  head shift     how far the middle of the head's outline moves
  outline move   how far the head's outline moves, on average and at most

Areas are in the picture's pixels. With --out, one picture per pose is
written: each part in a flat colour, holes in red, filler in magenta.
"""
import argparse
import io
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

import live2d_export

EDGE_MARGIN = 4.0     # picture pixels: holes this close to the rest outline count as the outline moving

# Turn, nod and tilt at both ends; the body turn and lean; and a turn with the body following.
POSES = [
    ("turn left", {"ParamAngleX": -30.0}), ("turn right", {"ParamAngleX": 30.0}),
    ("nod up", {"ParamAngleY": 30.0}), ("nod down", {"ParamAngleY": -30.0}),
    ("tilt left", {"ParamAngleZ": -30.0}), ("tilt right", {"ParamAngleZ": 30.0}),
    ("turn and nod", {"ParamAngleX": 30.0, "ParamAngleY": 30.0}),
    ("body turn", {"ParamBodyAngleX": 10.0}), ("body lean", {"ParamBodyAngleY": 10.0}),
    ("turn with body", {"ParamAngleX": 30.0, "ParamBodyAngleX": 10.0}),
]


class Frame:
    """One drawn pose: which part shows at each pixel (-1 for none), and whether it shows made-up filling."""

    def __init__(self, top, filler):
        self.top = top
        self.filler = filler

    @property
    def covered(self):
        return self.top >= 0


class Scene:
    def __init__(self, inp_bytes, invented_dir=None, scale=0.5):
        self.puppet = live2d_export.Puppet(inp_bytes)
        self.scale = float(scale)
        rest = np.vstack([self.puppet.world(p, self.puppet.defaults()) for p in self.puppet.parts])
        lo, hi = rest.min(0), rest.max(0)
        pad = 0.12 * (hi - lo) + 10.0
        self.origin = lo - pad
        self.width, self.height = (np.ceil((hi - lo + 2 * pad) * self.scale).astype(int) + 1).tolist()
        # Back to front, as Inox2D draws: larger zsort first; ties keep the tree's order.
        self.order = sorted(self.puppet.parts, key=lambda p: -p.abs_zsort())
        self.alpha = {}
        for part in self.order:
            if part.texture not in self.alpha:
                _, data = self.puppet.textures[part.texture]
                with Image.open(io.BytesIO(data)) as im:
                    self.alpha[part.texture] = np.asarray(im.convert("RGBA"))[..., 3].copy()
        self.invented = {}
        if invented_dir:
            for entry in os.listdir(invented_dir):
                if not entry.endswith(".png"):
                    continue
                stem = entry[:-4]
                with Image.open(os.path.join(invented_dir, entry)) as im:
                    mask = np.asarray(im.convert("RGBA"))[..., 3] > 0
                for part in self.order:
                    if part.name == stem or part.name.startswith(stem + "_"):
                        self.invented[part.uuid] = mask
        self.head = {i for i, p in enumerate(self.order) if any(a.name == "head" for a in p.ancestors())}
        self._rest = None

    def to_pixels(self, points):
        return (points - self.origin) * self.scale

    def render(self, values):
        top = np.full((self.height, self.width), -1, np.int32)
        filler = np.zeros((self.height, self.width), bool)
        for index, part in enumerate(self.order):
            if self.puppet.opacity(part, values) < 0.5:
                continue
            pts = self.to_pixels(self.puppet.world(part, values))
            alpha = self.alpha[part.texture]
            th, tw = alpha.shape
            made_up = self.invented.get(part.uuid)
            for a, b, c in np.asarray(part.indices, int).reshape(-1, 3):
                self._triangle(pts[[a, b, c]], part.uvs[[a, b, c]], alpha, tw, th, made_up, index, top, filler)
        return Frame(top, filler)

    def _triangle(self, p, uv, alpha, tw, th, made_up, index, top, filler):
        x0 = max(int(np.floor(p[:, 0].min())), 0)
        x1 = min(int(np.ceil(p[:, 0].max())), self.width - 1)
        y0 = max(int(np.floor(p[:, 1].min())), 0)
        y1 = min(int(np.ceil(p[:, 1].max())), self.height - 1)
        if x0 > x1 or y0 > y1:
            return
        (ax, ay), (bx, by), (cx, cy) = p
        denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(denom) < 1e-9:
            return
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        l0 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / denom
        l1 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / denom
        l2 = 1.0 - l0 - l1
        inside = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
        if not inside.any():
            return
        u = l0 * uv[0, 0] + l1 * uv[1, 0] + l2 * uv[2, 0]
        v = l0 * uv[0, 1] + l1 * uv[1, 1] + l2 * uv[2, 1]
        tx = np.clip((u * tw).astype(int), 0, tw - 1)
        ty = np.clip((v * th).astype(int), 0, th - 1)
        shown = inside & (alpha[ty, tx] > 127)
        region = top[y0:y1 + 1, x0:x1 + 1]
        region[shown] = index
        spot = filler[y0:y1 + 1, x0:x1 + 1]
        spot[shown] = made_up[ty, tx][shown] if made_up is not None else False

    def rest(self):
        if self._rest is None:
            self._rest = self.render(self.puppet.defaults())
        return self._rest

    def measure(self, values):
        rest, pose = self.rest(), self.render(dict(self.puppet.defaults(), **values))
        area = 1.0 / (self.scale * self.scale)
        margin = max(1, int(round(EDGE_MARGIN * self.scale)))
        inner = ndimage.binary_erosion(rest.covered, iterations=margin)
        uncovered = inner & ~pose.covered
        # Gaps: background the character encloses in the pose (between the head and neck, say).
        holes = ndimage.binary_fill_holes(pose.covered) & ~pose.covered
        holes &= ~(ndimage.binary_fill_holes(rest.covered) & ~rest.covered)    # gaps already there at rest
        filler = pose.filler & ~rest.filler
        out = {"uncovered": round(uncovered.sum() * area), "holes": round(holes.sum() * area),
               "filler shown": round(filler.sum() * area), "filler at rest": round(rest.filler.sum() * area)}
        holes = holes | uncovered
        head_rest, head_pose = np.isin(rest.top, list(self.head)), np.isin(pose.top, list(self.head))
        if head_rest.any() and head_pose.any():
            (ry, rx), (py, px) = ndimage.center_of_mass(head_rest), ndimage.center_of_mass(head_pose)
            out["head shift"] = [round((px - rx) / self.scale, 1), round((py - ry) / self.scale, 1)]
            edge_rest = head_rest & ~ndimage.binary_erosion(head_rest)
            edge_pose = head_pose & ~ndimage.binary_erosion(head_pose)
            distance = ndimage.distance_transform_edt(~edge_rest)[edge_pose] / self.scale
            out["outline move"] = {"mean": round(float(distance.mean()), 1), "max": round(float(distance.max()), 1)}
        return out, pose, holes, filler

    def picture(self, pose, holes, filler):
        rng = np.random.default_rng(3)
        colours = rng.integers(70, 230, size=(len(self.order) + 1, 3)).astype(np.uint8)
        colours[-1] = (24, 24, 30)
        out = colours[np.where(pose.top >= 0, pose.top, len(self.order))]
        out[filler] = (255, 0, 255)
        out[holes] = (255, 0, 0)
        return Image.fromarray(out, "RGB")


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("puppet")
    parser.add_argument("--invented", help="the work folder's invented/ directory from make_character.py --keep")
    parser.add_argument("--out", help="write a picture per pose here")
    parser.add_argument("--scale", type=float, default=0.5)
    args = parser.parse_args(argv)
    with open(args.puppet, "rb") as f:
        scene = Scene(f.read(), args.invented, args.scale)
    names = {p.name for p in scene.puppet.params}
    results = {}
    for name, values in POSES:
        if not set(values) <= names:
            continue
        result, pose, holes, filler = scene.measure(values)
        results[name] = result
        if args.out:
            os.makedirs(args.out, exist_ok=True)
            scene.picture(pose, holes, filler).save(os.path.join(args.out, name.replace(" ", "_") + ".png"))
    print(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
