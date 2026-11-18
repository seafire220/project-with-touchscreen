#!/usr/bin/env python3
"""Draw a character in software, to preview how it moves before it goes to the device.

    preview.py PUPPET.inp OUT.gif [--size 360]

Uses the exact positions Inox2D computes (live2d_export.Puppet.world) and the
puppet's own textures, drawn back to front with transparency, so no graphics
card, Live2D software or the device's stage program is needed. Slower than
the stage (a few frames a second) and without its smoothing; good enough to
see whether the character blinks, talks, turns its head and moves its arms.

The animation walks through the character's abilities: a blink, talking, a
head turn each way and a nod, then a wave and hands on hips if its arms move.
"""
import argparse
import io
import sys

import numpy as np
from PIL import Image

import live2d_export
import refine

BACKGROUND = (24, 24, 30)
FPS = 10


class Renderer:
    def __init__(self, inp_bytes, size=360, view=None):
        self.puppet = live2d_export.Puppet(inp_bytes)
        rest = np.vstack([self.puppet.world(p, self.puppet.defaults()) for p in self.puppet.parts])
        lo, hi = rest.min(0), rest.max(0)
        if view is None:
            centre, span = (lo + hi) / 2, (hi - lo).max() * 1.15
            view = (centre[0] - span / 2, centre[1] - span / 2, centre[0] + span / 2, centre[1] + span / 2)
        self.view = view
        self.width = size
        self.height = max(1, int(round(size * (view[3] - view[1]) / (view[2] - view[0]))))
        self.scale = size / (view[2] - view[0])
        # Back to front, as Inox2D draws: larger zsort first; ties keep the tree's order.
        self.order = sorted(self.puppet.parts, key=lambda p: -p.abs_zsort())
        self.textures = {}
        for part in self.order:
            if part.texture in self.textures:
                continue
            _, data = self.puppet.textures[part.texture]
            with Image.open(io.BytesIO(data)) as im:
                im = im.convert("RGBA")
                # Shrink each texture to about the size it is drawn at, so outlines do not shimmer.
                span = max(1.0, float(np.ptp(part.verts, 0).max()))
                factor = min(1.0, 1.5 * span * self.scale / max(1, max(im.size) * float(np.ptp(part.uvs, 0).max())))
                if factor < 0.95:
                    im = im.resize((max(1, int(im.width * factor)), max(1, int(im.height * factor))), Image.LANCZOS)
                rgba = np.asarray(im).astype(np.float32) / 255.0
            rgba[..., :3] *= rgba[..., 3:4]                    # premultiplied, as the stage draws
            self.textures[part.texture] = rgba

    def render(self, values):
        values = dict(self.puppet.defaults(), **values)
        canvas = np.zeros((self.height, self.width, 4), np.float32)
        for part in self.order:
            opacity = self.puppet.opacity(part, values)
            if opacity < 0.004:
                continue
            pts = (self.puppet.world(part, values) - [self.view[0], self.view[1]]) * self.scale
            texture = self.textures[part.texture]
            for tri in np.asarray(part.indices, int).reshape(-1, 3):
                self._triangle(canvas, pts[tri], part.uvs[tri], texture, opacity)
        out = np.empty((self.height, self.width, 3), np.float32)
        out[:] = np.array(BACKGROUND, np.float32) / 255.0
        out = canvas[..., :3] + out * (1.0 - canvas[..., 3:4])
        return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")

    def _triangle(self, canvas, p, uv, texture, opacity):
        h, w = canvas.shape[:2]
        x0, x1 = max(int(np.floor(p[:, 0].min())), 0), min(int(np.ceil(p[:, 0].max())), w - 1)
        y0, y1 = max(int(np.floor(p[:, 1].min())), 0), min(int(np.ceil(p[:, 1].max())), h - 1)
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
        inside = (l0 >= -1e-4) & (l1 >= -1e-4) & (l2 >= -1e-4)
        if not inside.any():
            return
        th, tw = texture.shape[:2]
        u = (l0 * uv[0, 0] + l1 * uv[1, 0] + l2 * uv[2, 0])[inside] * tw - 0.5
        v = (l0 * uv[0, 1] + l1 * uv[1, 1] + l2 * uv[2, 1])[inside] * th - 0.5
        # Bilinear sampling.
        u0, v0 = np.floor(u).astype(int), np.floor(v).astype(int)
        fu, fv = (u - u0)[:, None], (v - v0)[:, None]
        u0c, u1c = np.clip(u0, 0, tw - 1), np.clip(u0 + 1, 0, tw - 1)
        v0c, v1c = np.clip(v0, 0, th - 1), np.clip(v0 + 1, 0, th - 1)
        colour = ((1 - fu) * (1 - fv) * texture[v0c, u0c] + fu * (1 - fv) * texture[v0c, u1c]
                  + (1 - fu) * fv * texture[v1c, u0c] + fu * fv * texture[v1c, u1c]) * opacity
        region = canvas[y0:y1 + 1, x0:x1 + 1]
        below = region[inside]
        region[inside] = colour + below * (1.0 - colour[:, 3:4])


def tour(params):
    """(seconds, settings) key poses walking through what the character can do; the frames blend between them."""
    has = set(params)
    keys = [(0.0, {}), (0.5, {})]
    t = 0.5

    def add(dt, values):
        nonlocal t
        t += dt
        keys.append((t, values))
    if {"ParamEyeLOpen", "ParamEyeROpen"} <= has:
        add(0.15, {"ParamEyeLOpen": 0.0, "ParamEyeROpen": 0.0})
        add(0.15, {})
    if "ParamMouthOpenY" in has:
        for level in (0.8, 0.2, 0.6, 0.0):
            add(0.2, {"ParamMouthOpenY": level})
    if "ParamAngleX" in has:
        add(0.6, {"ParamAngleX": -25.0, "ParamBodyAngleX": -4.0})
        add(0.4, {"ParamAngleX": -25.0, "ParamBodyAngleX": -4.0})
        add(0.9, {"ParamAngleX": 25.0, "ParamBodyAngleX": 4.0})
        add(0.4, {"ParamAngleX": 25.0, "ParamBodyAngleX": 4.0})
        add(0.6, {})
    if "ParamAngleY" in has:
        add(0.4, {"ParamAngleY": -15.0})
        add(0.4, {"ParamAngleY": 10.0})
        add(0.4, {})
    if {"ParamArmRA", "ParamArmRB"} <= has:
        wave = {"ParamArmRA": refine.POSE_A["wave"], "ParamArmRB": refine.POSE_B["wave"]}
        add(0.6, wave)
        for bend in (7.0, 9.5, 7.0, 8.5):
            add(0.3, dict(wave, ParamArmRB=bend))
        add(0.6, {})
    arms = [s for s in "LR" if {"ParamArm%sA" % s, "ParamArm%sB" % s} <= has]
    if arms:
        hips = {}
        for s in arms:
            hips.update({"ParamArm%sA" % s: refine.POSE_A["hip"], "ParamArm%sB" % s: refine.POSE_B["hip"]})
        add(0.7, hips)
        add(0.8, hips)
        add(0.7, {})
    add(0.4, {})
    return keys


def frames(renderer, keys, fps=FPS):
    """Render the tour: settings blend smoothly from one key pose to the next."""
    names = sorted({n for _, v in keys for n in v})
    out = []
    t, end = 0.0, keys[-1][0]
    while t <= end + 1e-9:
        i = max(k for k in range(len(keys)) if keys[k][0] <= t + 1e-9)
        j = min(i + 1, len(keys) - 1)
        (t0, a), (t1, b) = keys[i], keys[j]
        s = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
        s = s * s * (3 - 2 * s)
        values = {}
        for n in names:
            default = renderer.puppet.by_name[n].default if n in renderer.puppet.by_name else 0.0
            values[n] = (1 - s) * a.get(n, default) + s * b.get(n, default)
        out.append(renderer.render(values))
        t += 1.0 / fps
    return out


def gif(images, fps=FPS):
    data = io.BytesIO()
    palette = [im.quantize(colors=160, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for im in images]
    palette[0].save(data, "GIF", save_all=True, append_images=palette[1:], duration=int(1000 / fps), loop=0,
                    optimize=True)
    return data.getvalue()


def preview_gif(inp_bytes, size=360, fps=FPS):
    """The tour as an animated GIF."""
    renderer = Renderer(inp_bytes, size)
    return gif(frames(renderer, tour([p.name for p in renderer.puppet.params]), fps), fps)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("puppet")
    parser.add_argument("out")
    parser.add_argument("--size", type=int, default=360)
    args = parser.parse_args(argv)
    with open(args.puppet, "rb") as f:
        data = f.read()
    with open(args.out, "wb") as f:
        f.write(preview_gif(data, args.size))
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
