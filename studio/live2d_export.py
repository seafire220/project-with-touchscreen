#!/usr/bin/env python3
"""Turn a studio puppet (.inp) into a Live2D-format model: .moc3, .model3.json and textures.

    live2d_export.py PUPPET.inp OUT_DIR [--name NAME] [--extras DIR]

The studio's Inochi2D puppet is the master copy of a character: its meshes,
textures and every movement, including the head movement from refine.py.
This converts it, movement for movement, into the format that Live2D's
runtimes and Ayagami read, so the same character plays in either kind of
engine.

How the movement maps
---------------------

* Each part becomes an art mesh. Its own movements (eyes, mouth, head turn,
  nod and tilt, arms) become keyforms: one copy of the mesh for every
  combination of its settings' key values. Players blend between them the
  same piecewise-linear way Inochi2D blends its offsets, so the result is
  the same, not an approximation.
* Some movements shift many parts as one smooth field (breathing, and how
  the body turn carries the head). Those, and the rotations of the body
  node, go on one warp deformer per group of parts. Without that a face
  part would need a keyform for every combination of every setting
  (thousands).
* After building, every vertex is compared with Inochi2D's own result at
  random settings; the report gives the largest difference in pixels.

The .moc3 file is written by image2live2d's from-scratch writer (Apache-2.0).
No Live2D software, SDK or sample file is used. See
docs/19-live2d-format-licensing.md before distributing files in this format.

--extras DIR copies the physics, motion files and expression files that the
rigger wrote with its --live2d option; their parameter names are the same
as the puppet's.
"""
import argparse
import io
import json
import os
import random
import shutil
import struct
import sys

import numpy as np
from PIL import Image

import refine

TEXTURE_SECTION = b"TEX_SECT"
WARP_CELLS = 12             # cells across and down a warp deformer's grid, at least
WARP_CELL_SIZE = 40.0       # pixels: big warps get more cells, so each is about this size
MAX_WARP_CELLS = 48
WARP_MARGIN = 0.12          # the grid reaches this share of its parts' size beyond them
FIELD_TOLERANCE = 0.05      # pixels: a movement is one smooth field if a polynomial fits it this closely
FIELD_MIN_PARTS = 3         # ... and it moves at least this many parts
FIELD_SHIFT_TOLERANCE = 3.0 # pixels: ... and applying it where a part's own movements have taken its points
                            # (a warp does) instead of where they were drawn (Inochi2D does) changes this little
                            # (in the rare poses that combine both at full strength; invisible on the screen)
MAX_FIELD_DEGREE = 4
ATLAS_MAX = 4096            # pixels: the largest texture page written
ATLAS_PAD = 8               # pixels kept around the area a mesh samples, so mipmaps do not bleed
TRANSFORMS = ("transform.t.x", "transform.t.y", "transform.r.x", "transform.r.y", "transform.r.z",
              "transform.s.x", "transform.s.y")
# Live2D's standard groups, filled when the puppet has these settings.
GROUPS = {"EyeBlink": ("ParamEyeLOpen", "ParamEyeROpen"), "LipSync": ("ParamMouthOpenY",)}


# --------------------------------------------------------------------------------------------------
# Reading the puppet
# --------------------------------------------------------------------------------------------------

def read_textures(rest):
    """The texture section after the puppet's JSON: [(encoding, bytes)]. 0 = PNG, 1 = TGA."""
    if rest[:8] != TEXTURE_SECTION:
        raise ValueError("the puppet has no texture section")
    count = struct.unpack(">I", rest[8:12])[0]
    pos, out = 12, []
    for _ in range(count):
        length = struct.unpack(">I", rest[pos:pos + 4])[0]
        out.append((rest[pos + 4], rest[pos + 5:pos + 5 + length]))
        pos += 5 + length
    return out


class Param:
    """One setting: its range, its key values and Inox2D's piecewise-linear rule between them."""

    def __init__(self, raw, index):
        if raw.get("is_vec2"):
            raise ValueError("two-axis settings are not supported: %s" % raw.get("name"))
        self.index = index
        self.name = raw["name"]
        self.lo, self.hi = float(raw["min"][0]), float(raw["max"][0])
        self.default = float(raw["defaults"][0])
        self.axis = [float(a) for a in raw["axis_points"][0]]
        self.keys = [self.lo + a * (self.hi - self.lo) for a in self.axis]
        if any(b <= a for a, b in zip(self.axis, self.axis[1:])):
            raise ValueError("setting %s: key values must increase" % self.name)

    def segment(self, value):
        """(i, t): the value lies t of the way from key i to key i + 1."""
        if len(self.axis) == 1:
            return 0, 0.0
        span = self.hi - self.lo
        norm = 0.0 if span == 0 else (min(max(value, self.lo), self.hi) - self.lo) / span
        for i in range(len(self.axis) - 1):
            if norm <= self.axis[i + 1] or i == len(self.axis) - 2:
                a, b = self.axis[i], self.axis[i + 1]
                return i, min(max((norm - a) / (b - a), 0.0), 1.0)

    def at(self, values, value):
        """A binding's value (scalar or array) at this setting's value."""
        i, t = self.segment(value)
        if len(self.axis) == 1:
            return np.asarray(values[0], float)
        return (1.0 - t) * np.asarray(values[i], float) + t * np.asarray(values[i + 1], float)


class Node:
    def __init__(self, raw, parent):
        self.raw = raw
        self.uuid = raw["uuid"]
        self.name = raw.get("name", "")
        self.type = raw.get("type", "Node")
        transform = raw.get("transform", {})
        trans = list(transform.get("trans", [0.0, 0.0, 0.0])) + [0.0, 0.0, 0.0]
        self.trans = np.array(trans[:3], float)
        self.rot = np.array((list(transform.get("rot", [0.0, 0.0, 0.0])) + [0.0] * 3)[:3], float)
        self.scale = np.array((list(transform.get("scale", [1.0, 1.0])) + [1.0, 1.0])[:2], float)
        self.zsort = float(raw.get("zsort", 0.0))
        self.parent = parent
        self.children = []
        self.transforms = []    # (param, kind, values)
        self.deforms = []       # (param, values: per key, an (n, 2) array)
        self.opacities = []     # (param, values: per key, a factor)
        mesh = raw.get("mesh") or {}
        self.verts = np.array(mesh.get("verts", []), float).reshape(-1, 2)
        self.uvs = np.array(mesh.get("uvs", []), float).reshape(-1, 2)
        self.indices = list(mesh.get("indices", []))
        textures = raw.get("textures") or [None]
        self.texture = textures[0]
        self.opacity = float(raw.get("opacity", 1.0))

    @property
    def drawn(self):
        return self.type == "Part" and len(self.verts) > 0

    def ancestors(self):
        out, node = [], self.parent
        while node is not None:
            out.append(node)
            node = node.parent
        return out[::-1]

    def abs_zsort(self):
        return self.zsort + sum(a.zsort for a in self.ancestors())

    def matrix(self, values):
        """This node's transform (Inox2D's order: translate, rotate X then Y then Z, scale) at the settings."""
        trans, rot, scale = self.trans.copy(), self.rot.copy(), self.scale.copy()
        for param, kind, vals in self.transforms:
            v = float(param.at(vals, values.get(param.name, param.default)))
            axis = "xyz".index(kind[-1])
            if kind.startswith("transform.t"):
                trans[axis] += v
            elif kind.startswith("transform.r"):
                rot[axis] += v
            else:
                scale[axis] *= v
        return translate(trans) @ rotate_x(rot[0]) @ rotate_y(rot[1]) @ rotate_z(rot[2]) @ scaling(scale)


def translate(t):
    m = np.eye(4)
    m[:3, 3] = t
    return m


def rotate_x(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]], float)


def rotate_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], float)


def rotate_z(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], float)


def scaling(s):
    return np.diag([s[0], s[1], 1.0, 1.0])


def apply(matrix, points):
    """A 4x4 transform applied to 2D points (z = 0)."""
    return points @ matrix[:2, :2].T + matrix[:2, 3]


class Puppet:
    def __init__(self, inp_bytes):
        data, rest = refine.read_puppet(inp_bytes)
        self.name = data.get("meta", {}).get("name") or "character"
        self.textures = read_textures(rest)
        self.params = [Param(raw, i) for i, raw in enumerate(data.get("param", []))]
        self.by_name = {p.name: p for p in self.params}
        self.nodes = {}
        self.root = self._build(data["nodes"], None)
        for raw, param in zip(data.get("param", []), self.params):
            for binding in raw.get("bindings", []):
                node = self.nodes.get(binding["node"])
                kind = binding["param_name"]
                if node is None:
                    continue
                values = [row[0] for row in binding["values"]]
                if kind == "deform":
                    if not node.drawn:
                        continue
                    node.deforms.append((param, [np.asarray(v, float).reshape(-1, 2) for v in values]))
                elif kind == "opacity":
                    node.opacities.append((param, [float(v) for v in values]))
                elif kind in TRANSFORMS:
                    node.transforms.append((param, kind, [float(v) for v in values]))
                elif kind == "zSort":
                    raise ValueError("settings that change the drawing order are not supported (%s)" % param.name)
                # Other kinds (physics settings and the like) do not move what is drawn.
        self.parts = [n for n in self.nodes.values() if n.drawn and self._shown(n)]
        if not self.parts:
            raise ValueError("the puppet has no drawn parts")
        for part in self.parts:
            if part.transforms:
                raise ValueError("part %s moves by its own transform; only parent nodes may" % part.name)
            if len(part.uvs) != len(part.verts):
                raise ValueError("part %s has %d points but %d texture positions"
                                 % (part.name, len(part.verts), len(part.uvs)))

    def _build(self, raw, parent):
        node = Node(raw, parent)
        self.nodes[node.uuid] = node
        for child in raw.get("children") or []:
            node.children.append(self._build(child, node))
        return node

    @staticmethod
    def _shown(node):
        return node.raw.get("enabled", True) and all(a.raw.get("enabled", True) for a in node.ancestors())

    def defaults(self):
        return {p.name: p.default for p in self.params}

    def world(self, part, values):
        """Inox2D's own result: a part's points on the canvas at the given settings."""
        points = part.verts.copy()
        for param, vals in part.deforms:
            points = points + param.at(vals, values.get(param.name, param.default))
        matrix = np.eye(4)
        for node in part.ancestors() + [part]:
            matrix = matrix @ node.matrix(values)
        return apply(matrix, points)

    def opacity(self, part, values):
        factor = part.opacity
        for param, vals in part.opacities:
            factor *= float(param.at(vals, values.get(param.name, param.default)))
        return factor


# --------------------------------------------------------------------------------------------------
# Planning: which movements go on warp deformers, which stay in each mesh
# --------------------------------------------------------------------------------------------------

def frame_of(part):
    """The deepest node above the part that moves by a transform (or the root)."""
    frame = part.ancestors()[0]
    for node in part.ancestors():
        if node.transforms:
            frame = node
    return frame


def in_frame(part, frame):
    """The part's rest points in its frame node's own coordinates."""
    offset = np.zeros(2)
    node = part
    while node is not frame:
        offset += node.trans[:2]
        node = node.parent
    return part.verts + offset


def poly_terms(points, centre, size, degree):
    x = (points[:, 0] - centre[0]) / size
    y = (points[:, 1] - centre[1]) / size
    return np.stack([x ** i * y ** k for i in range(degree + 1) for k in range(degree + 1 - i)], 1)


class Field:
    """A movement that shifts several parts as one smooth function of position.

    Fitted with one polynomial per key when one fits closely. Otherwise, if the parts agree wherever they
    overlap (one movement, not several), the field is sampled from the parts' own points: smooth but
    not polynomial movements, such as a body turn fitted to the body's outline, still go on a warp.
    """

    def __init__(self, param, parts, frame):
        self.param = param
        points = np.vstack([in_frame(p, frame) for p in parts])
        moves = [next(vals for q, vals in p.deforms if q is param) for p in parts]
        offsets = [np.vstack([m[k] for m in moves]) for k in range(len(param.keys))]
        self.centre = points.mean(0)
        self.size = max(float(np.ptp(points, 0).max()), 1.0)
        self.fit = None
        for degree in range(MAX_FIELD_DEGREE + 1):
            terms = poly_terms(points, self.centre, self.size, degree)
            coeffs = [np.linalg.lstsq(terms, o, rcond=None)[0] for o in offsets]
            error = max(float(np.abs(terms @ c - o).max()) for c, o in zip(coeffs, offsets))
            if error <= FIELD_TOLERANCE:
                self.fit, self.degree, self.error = coeffs, degree, error
                break
        if self.fit is None:
            self._sample(points, offsets)

    def _sample(self, points, offsets):
        from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
        from scipy.spatial import cKDTree
        # Points of different parts within half a pixel of each other must move alike, or this is not one
        # movement but several.
        keyed = np.hstack(offsets)
        tree = cKDTree(points)
        for i, j in tree.query_pairs(0.5):
            if np.abs(keyed[i] - keyed[j]).max() > FIELD_TOLERANCE:
                return
        _, first = np.unique(np.round(points, 1), axis=0, return_index=True)
        pts, vals = points[first], keyed[first]
        try:
            linear = LinearNDInterpolator(pts, vals)
        except Exception:
            return
        nearest = NearestNDInterpolator(pts, vals)

        def sampled(at):
            out = linear(at)
            missing = np.isnan(out).any(axis=1)
            if missing.any():
                out[missing] = nearest(at[missing])
            return out
        self.sampled = sampled
        self.fit = [None] * len(offsets)
        self.degree = None
        self.error = 0.0

    def offset(self, points, key):
        if self.degree is None:
            return self.sampled(np.asarray(points, float))[:, 2 * key:2 * key + 2]
        return poly_terms(points, self.centre, self.size, self.degree) @ self.fit[key]

    def steepness(self, points):
        """How much the offset changes per pixel moved, at worst, near these points."""
        return float(self.steepness_at(points).max())

    def steepness_at(self, points):
        """How much the offset changes per pixel moved, at each point."""
        worst = np.zeros(len(points))
        for key in range(len(self.fit)):
            for step in ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)):
                change = self.offset(points + step, key) - self.offset(points, key)
                worst = np.maximum(worst, np.abs(change).max(axis=1))
        return worst


def plan(puppet):
    """Group the parts. Each group shares a frame node and a set of field movements -> one warp.

    A movement shared by several parts as one field goes on a warp they share, so the body's settings
    stay off the meshes' keyforms, which would otherwise multiply.
    """
    by_frame = {}
    for part in puppet.parts:
        by_frame.setdefault(frame_of(part).uuid, []).append(part)
    shared = {}
    for frame_id, parts in by_frame.items():
        frame = puppet.nodes[frame_id]
        for param in puppet.params:
            moved = [p for p in parts if any(q is param for q, _ in p.deforms)]
            if len(moved) < FIELD_MIN_PARTS:
                continue
            field = Field(param, moved, frame)
            if field.fit is not None:
                shared[(frame_id, param.name)] = field
    # A warp applies a field where the part's own movements have taken its points; Inochi2D applies it
    # where they were drawn. For each part, keep only the fields for which that makes no difference (to
    # within FIELD_SHIFT_TOLERANCE); the others become the part's own keyforms. Breathing stays on the
    # warp for a face but not for an arm that swings far; a head tilt (a rigid rotation, so a perfect
    # field) would turn an eye's closing movement with it, so a closing eye keeps the tilt itself.
    groups = {}
    for part in puppet.parts:
        frame = frame_of(part)
        drawn = in_frame(part, frame)
        mine = []
        for q, _ in part.deforms:
            field = shared.get((frame.uuid, q.name))
            if field is not None:
                mine.append(field)
        while mine:
            kept = {f.param.name for f in mine}
            # How far each point's own movements take it, at most: a field is judged where it acts.
            reach = np.zeros(len(drawn))
            for q, vals in part.deforms:
                if q.name not in kept:
                    reach += np.max([np.abs(v).max(axis=1) for v in vals], axis=0)
            errors = {f: float((f.steepness_at(drawn) * reach).max()) for f in mine}
            worst = max(mine, key=errors.get)
            if errors[worst] <= FIELD_SHIFT_TOLERANCE:
                break
            mine.remove(worst)
        mine.sort(key=lambda f: f.param.index)
        own_fields = [f for f in mine if shared.get((frame.uuid, f.param.name)) is not f]
        key = (frame.uuid, tuple(f.param.name for f in mine), part.uuid if own_fields else None)
        groups.setdefault(key, (frame.uuid, mine, []))[2].append(part)
    return shared, groups


def combos(params):
    """Every combination of the settings' key indices, the first setting changing fastest."""
    counts = [len(p.keys) for p in params]
    total = int(np.prod(counts))
    out = []
    for index in range(total):
        rest, combo = index, []
        for n in counts:
            combo.append(rest % n)
            rest //= n
        out.append(tuple(combo))
    return out


# --------------------------------------------------------------------------------------------------
# Building the model
# --------------------------------------------------------------------------------------------------

class Model:
    """The Live2D-format model as plain data, plus a player that evaluates it like Ayagami does."""

    def __init__(self, puppet):
        self.puppet = puppet
        fields, groups = plan(puppet)
        self.fields = fields
        world = np.vstack([puppet.world(p, puppet.defaults()) for p in puppet.parts])
        lo, hi = world.min(0), world.max(0)
        pad = 0.05 * (hi - lo)
        self.canvas_lo, self.canvas_hi = lo - pad, hi + pad
        self.centre = (self.canvas_lo + self.canvas_hi) / 2
        self.ppu = float((self.canvas_hi - self.canvas_lo).max() / 2)
        self.warps, self.meshes = [], []
        for frame_id, group_fields, parts in groups.values():
            self._group(puppet.nodes[frame_id], group_fields, parts)
        order = sorted(range(len(self.meshes)), key=lambda i: -self.meshes[i]["part"].abs_zsort())
        self.meshes = [self.meshes[i] for i in order]      # back to front, ties in tree order (stable)

    def to_model(self, points):
        """Canvas pixels -> model units (about +-1). Both have y growing downwards on screen: Live2D's own
        sample models and the rigger's files play upright in Ayagami with the head at negative y."""
        return (points - self.centre) / self.ppu

    def to_canvas(self, units):
        return units * self.ppu + self.centre

    def _group(self, frame, fields, parts):
        puppet = self.puppet
        chain = frame.ancestors() + [frame]
        moved_by_chain = {param.name for node in chain for param, _, _ in node.transforms}
        warp_params = sorted({puppet.by_name[n] for n in moved_by_chain} | {f.param for f in fields},
                             key=lambda p: p.index)
        field_names = {f.param.name for f in fields}
        meshes = []
        for part in parts:
            own = sorted({q for q, _ in part.deforms if q.name not in field_names} | {q for q, _ in part.opacities},
                         key=lambda p: p.index)
            base = in_frame(part, frame)
            forms, opacities = [], []
            for combo in combos(own):
                points = base.copy()
                factor = part.opacity
                values = {p.name: p.keys[k] for p, k in zip(own, combo)}
                for param, vals in part.deforms:
                    if param.name in values:
                        points = points + param.at(vals, values[param.name])
                for param, vals in part.opacities:
                    factor *= float(param.at(vals, values[param.name]))
                forms.append(points)
                opacities.append(factor)
            meshes.append({"part": part, "params": own, "forms": forms, "opacities": opacities})
        if not warp_params:
            rest_matrix = np.eye(4)
            for node in chain:
                rest_matrix = rest_matrix @ node.matrix(puppet.defaults())
            for mesh in meshes:
                mesh["forms"] = [self.to_model(apply(rest_matrix, f)) for f in mesh["forms"]]
                mesh["warp"] = None
            self.meshes.extend(meshes)
            return
        every = np.vstack([f for m in meshes for f in m["forms"]])
        lo, hi = every.min(0), every.max(0)
        pad = WARP_MARGIN * (hi - lo) + 2.0
        lo, hi = lo - pad, hi + pad
        span = hi - lo
        cols = int(min(max(WARP_CELLS, np.ceil(span[0] / WARP_CELL_SIZE)), MAX_WARP_CELLS))
        rows = int(min(max(WARP_CELLS, np.ceil(span[1] / WARP_CELL_SIZE)), MAX_WARP_CELLS))
        gx, gy = np.meshgrid(np.linspace(lo[0], hi[0], cols + 1), np.linspace(lo[1], hi[1], rows + 1))
        grid = np.stack([gx.ravel(), gy.ravel()], 1)          # row by row, x changing fastest
        forms = []
        for combo in combos(warp_params):
            values = dict(puppet.defaults())
            values.update({p.name: p.keys[k] for p, k in zip(warp_params, combo)})
            keyed = {p.name: k for p, k in zip(warp_params, combo)}
            points = grid.copy()
            for field in fields:
                points = points + field.offset(grid, keyed[field.param.name])
            matrix = np.eye(4)
            for node in chain:
                matrix = matrix @ node.matrix(values)
            forms.append(self.to_model(apply(matrix, points)))
        warp = {"id": "Warp%d" % (len(self.warps) + 1), "frame": frame, "params": warp_params, "forms": forms,
                "rows": rows, "cols": cols, "lo": lo, "hi": hi,
                "parts": [m["part"].name for m in meshes], "fields": sorted(field_names)}
        self.warps.append(warp)
        for mesh in meshes:
            mesh["forms"] = [(f - lo) / (hi - lo) for f in mesh["forms"]]   # the grid's own 0..1 space
            mesh["warp"] = warp
        self.meshes.extend(meshes)

    # ---- playing it back, the way Ayagami does ---------------------------------------------------

    @staticmethod
    def blend(params, forms, values):
        """Multilinear blend of keyforms laid out first-setting-fastest."""
        if not params:
            return forms[0]
        segs = [p.segment(values.get(p.name, p.default)) for p in params]
        counts = [len(p.keys) for p in params]
        out = 0.0
        for corner in range(1 << len(params)):
            index, stride, weight = 0, 1, 1.0
            for d, ((i, t), n) in enumerate(zip(segs, counts)):
                bit = (corner >> d) & 1
                if n == 1:
                    if bit:
                        weight = 0.0
                    k = 0
                else:
                    k = i + bit
                    weight *= t if bit else 1.0 - t
                index += k * stride
                stride *= n
            if weight:
                out = out + weight * np.asarray(forms[index])
        return out

    @staticmethod
    def warp_points(grid, cols, rows, uv):
        """Ayagami's warp for version 3.0 files: two triangles per cell."""
        if uv.min() < 0 or uv.max() > 1:
            raise ValueError("a point left its warp grid")
        size = np.array([cols, rows], float)
        rpos = uv * size
        ipos = np.clip(np.floor(rpos).astype(int), 0, size.astype(int) - 1)
        f = rpos - ipos
        g = grid.reshape(rows + 1, cols + 1, 2)
        p00 = g[ipos[:, 1], ipos[:, 0]]
        p01 = g[ipos[:, 1], ipos[:, 0] + 1]
        p10 = g[ipos[:, 1] + 1, ipos[:, 0]]
        p11 = g[ipos[:, 1] + 1, ipos[:, 0] + 1]
        lower = (f[:, 0] + f[:, 1]) < 1
        out = np.empty_like(uv)
        a = f[lower]
        out[lower] = ((1 - a.sum(1))[:, None] * p00[lower] + a[:, :1] * p01[lower] + a[:, 1:] * p10[lower])
        b = 1 - f[~lower]
        out[~lower] = ((1 - b.sum(1))[:, None] * p11[~lower] + b[:, :1] * p10[~lower] + b[:, 1:] * p01[~lower])
        return out

    def play(self, mesh, values):
        """A mesh's points on the canvas and its opacity, as a Live2D-format player computes them."""
        points = self.blend(mesh["params"], mesh["forms"], values)
        opacity = float(self.blend(mesh["params"], mesh["opacities"], values))
        warp = mesh["warp"]
        if warp is not None:
            grid = self.blend(warp["params"], warp["forms"], values)
            points = self.warp_points(grid, warp["cols"], warp["rows"], points)
        return self.to_canvas(points), opacity

    def check(self, samples=200, seed=7):
        """Largest difference from Inox2D's own result, in pixels and in opacity."""
        rng = random.Random(seed)
        puppet = self.puppet
        cases = [puppet.defaults()]
        cases += [{p.name: (p.lo if s else p.hi) for p in puppet.params} for s in (0, 1)]
        for _ in range(samples):
            cases.append({p.name: rng.choice([rng.uniform(p.lo, p.hi), rng.choice(p.keys)]) for p in puppet.params})
        worst, worst_opacity, where = 0.0, 0.0, ""
        for values in cases:
            for mesh in self.meshes:
                points, opacity = self.play(mesh, values)
                error = float(np.abs(points - puppet.world(mesh["part"], values)).max())
                if error > worst:
                    worst, where = error, mesh["part"].name
                worst_opacity = max(worst_opacity, abs(opacity - puppet.opacity(mesh["part"], values)))
        return {"cases": len(cases), "max_px": round(worst, 3), "worst_part": where,
                "max_opacity": round(worst_opacity, 4)}


# --------------------------------------------------------------------------------------------------
# Writing the files
# --------------------------------------------------------------------------------------------------

def safe_id(text, used):
    base = "".join(c if c.isalnum() or c == "_" else "_" for c in text)[:48] or "item"
    name, n = base, 2
    while name in used:
        name = "%s_%d" % (base, n)
        n += 1
    used.add(name)
    return name


def pack_textures(model):
    """Crop each part's picture to the area its mesh samples and pack the crops into square pages,
    the way Live2D-format models are laid out, instead of a whole-canvas picture per part (which
    costs tens of megabytes of memory on the device for nothing). Returns the pages as RGBA
    pictures and, for each mesh in order, its page number and its texture coordinates there."""
    puppet = model.puppet
    pictures, boxes = {}, []
    for mesh in model.meshes:
        part = mesh["part"]
        if part.texture not in pictures:
            with Image.open(io.BytesIO(puppet.textures[part.texture][1])) as im:
                pictures[part.texture] = im.convert("RGBA")
        w, h = pictures[part.texture].size
        px = part.uvs * [w, h]
        x0 = max(int(np.floor(px[:, 0].min())) - ATLAS_PAD, 0)
        y0 = max(int(np.floor(px[:, 1].min())) - ATLAS_PAD, 0)
        x1 = min(int(np.ceil(px[:, 0].max())) + ATLAS_PAD, w)
        y1 = min(int(np.ceil(px[:, 1].max())) + ATLAS_PAD, h)
        boxes.append((x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)))
    biggest = max(max(b[2] - b[0], b[3] - b[1]) for b in boxes)
    scale = min(1.0, ATLAS_MAX / biggest)
    sizes = [(max(1, int(round((b[2] - b[0]) * scale))), max(1, int(round((b[3] - b[1]) * scale)))) for b in boxes]
    order = sorted(range(len(boxes)), key=lambda k: (-sizes[k][1], -sizes[k][0]))

    def shelves(side):
        spots, page, x, y, row = [None] * len(boxes), 0, 0, 0, 0
        for k in order:
            w, h = sizes[k]
            if x + w > side:
                x, y, row = 0, y + row, 0
            if y + h > side:
                page, x, y, row = page + 1, 0, 0, 0
            spots[k] = (page, x, y)
            x, row = x + w, max(row, h)
        return spots, page + 1

    for side in (512, 1024, 2048, ATLAS_MAX):
        spots, pages = shelves(side)
        if pages == 1:
            break
    images = [Image.new("RGBA", (side, side), (0, 0, 0, 0)) for _ in range(pages)]
    layout = []
    for k, mesh in enumerate(model.meshes):
        part, box = mesh["part"], boxes[k]
        page, ax, ay = spots[k]
        crop = pictures[part.texture].crop(box)
        if crop.size != sizes[k]:
            crop = crop.resize(sizes[k], Image.LANCZOS)
        images[page].paste(crop, (ax, ay))
        w, h = pictures[part.texture].size
        px = part.uvs * [w, h]
        uvs = np.column_stack([(ax + (px[:, 0] - box[0]) * scale) / side, (ay + (px[:, 1] - box[1]) * scale) / side])
        layout.append((page, uvs))
    return images, layout


def moc3_bytes(model, layout=None):
    """The .moc3 file, built with image2live2d's from-scratch writer. With a layout from
    pack_textures, meshes use its pages and texture coordinates."""
    from image2live2d.backends.live2d.moc3_binary import write_moc3
    from image2live2d.backends.live2d.moc3_emit import EmitMesh, EmitParam, EmitPart, EmitWarp, build_moc3

    puppet = model.puppet
    params = [EmitParam(id=p.name, min=p.lo, max=p.hi, default=p.default, keys=list(p.keys)) for p in puppet.params]
    used = set()
    parts = [EmitPart(id="PartRoot", draw_order=500.0)]
    used.add("PartRoot")
    textures = []
    meshes = []
    n = len(model.meshes)
    for rank, mesh in enumerate(model.meshes):
        part = mesh["part"]
        # Draw order: back to front, spread over Live2D's usual 0..1000.
        parts.append(EmitPart(id=safe_id("Part_" + part.name, used), draw_order=float(round(100 + 800 * rank / max(n - 1, 1)))))
        if layout is None:
            if part.texture not in textures:
                textures.append(part.texture)
            texture_no, uvs = textures.index(part.texture), part.uvs
        else:
            texture_no, uvs = layout[rank]
        mesh_id = safe_id("ArtMesh_" + part.name, used)
        mesh["id"] = mesh_id
        meshes.append(EmitMesh(
            id=mesh_id, part_index=len(parts) - 1, texture_no=int(texture_no),
            uvs=[(float(u), float(v)) for u, v in uvs],
            triangles=[tuple(part.indices[i:i + 3]) for i in range(0, len(part.indices), 3)],
            param_indices=[p.index for p in mesh["params"]],
            keyforms=[[(float(x), float(y)) for x, y in form] for form in mesh["forms"]],
            opacities=[float(o) for o in mesh["opacities"]] if any(abs(o - 1.0) > 1e-9 for o in mesh["opacities"]) else []))
    warps = [EmitWarp(id=w["id"], parent_part_index=0, param_indices=[p.index for p in w["params"]],
                      rows=w["rows"], columns=w["cols"],
                      keyforms=[[(float(x), float(y)) for x, y in form] for form in w["forms"]],
                      child_ids={m["id"] for m in model.meshes if m["warp"] is w})
             for w in model.warps]
    size = model.canvas_hi - model.canvas_lo
    canvas = {"pixelsPerUnit": model.ppu, "originX": float(size[0] / 2), "originY": float(size[1] / 2),
              "width": float(size[0]), "height": float(size[1]), "flags": 0}
    moc = build_moc3(canvas, params, parts, meshes, warps=warps)
    # Every official version 3.0 file stores 3 in this field; Ayagami rejects other values.
    moc.sections["parameters"]["decimalPlaces"] = [3] * len(params)
    return moc3_bytes_checked(write_moc3(moc)), textures


def moc3_bytes_checked(data):
    from image2live2d.backends.live2d.moc3_binary import read_moc3
    read_moc3(data)                       # the writer's own reader must accept what it wrote
    return data


def export(inp_bytes, name=None, extras=None, check=True):
    """The Live2D-format files for a puppet, as {relative path: bytes}, and a report."""
    puppet = Puppet(inp_bytes)
    name = name or puppet.name
    model = Model(puppet)
    for mesh in model.meshes:
        tex = mesh["part"].texture
        if tex is None or tex >= len(puppet.textures):
            raise ValueError("a part uses a missing texture")
    pages, layout = pack_textures(model)
    moc, _ = moc3_bytes(model, layout)
    files = {"%s.moc3" % name: moc}
    texture_paths = []
    for i, page in enumerate(pages):
        path = "textures/texture_%02d.png" % i
        out = io.BytesIO()
        page.save(out, "PNG", optimize=True)
        files[path] = out.getvalue()
        texture_paths.append(path)
    refs = {"Moc": "%s.moc3" % name, "Textures": texture_paths, "DisplayInfo": "%s.cdi3.json" % name}
    extras = extras or {}
    physics = extras.get("physics")
    if physics is not None:
        refs["Physics"] = "%s.physics3.json" % name
        files[refs["Physics"]] = physics
    motions = extras.get("motions") or {}
    if motions:
        refs["Motions"] = {}
        used = set()
        for group, entries in motions.items():
            for _source, data in entries:
                # Named after the group: the rigger's own names carry the character's name, spaces and all.
                path = "motions/%s.motion3.json" % safe_id(group.lower(), used)
                refs["Motions"].setdefault(group, []).append({"File": path})
                files[path] = data
    names = {p.name for p in puppet.params}
    groups = [{"Target": "Parameter", "Name": g, "Ids": [i for i in ids if i in names]}
              for g, ids in GROUPS.items() if any(i in names for i in ids)]
    files["%s.model3.json" % name] = json.dumps(
        {"Version": 3, "FileReferences": refs, "Groups": groups}, indent=1).encode()
    files["%s.cdi3.json" % name] = json.dumps({
        "Version": 3,
        "Parameters": [{"Id": p.name, "GroupId": "", "Name": p.name} for p in puppet.params],
        "ParameterGroups": [],
        "Parts": [{"Id": "PartRoot", "Name": "Root"}],
    }, indent=1).encode()
    report = {
        "parts": len(model.meshes),
        "settings": len(puppet.params),
        "warps": [{"id": w["id"], "settings": [p.name for p in w["params"]], "fields": w["fields"],
                   "parts": len(w["parts"]), "keyforms": len(w["forms"])} for w in model.warps],
        "keyforms": sum(len(m["forms"]) for m in model.meshes),
        "most_keyforms": max((len(m["forms"]), m["part"].name) for m in model.meshes),
        "moc3_bytes": len(moc),
        "textures": len(texture_paths),
        "texture_side": pages[0].size[0],
    }
    if check:
        report["check"] = model.check()
    return files, report


def read_extras(directory):
    """Physics and motions from the rigger's --live2d folder, found through its .model3.json."""
    index = sorted(e for e in os.listdir(directory) if e.endswith(".model3.json"))
    if not index:
        raise ValueError("there is no .model3.json in %s" % directory)
    with open(os.path.join(directory, index[0]), encoding="utf-8") as f:
        refs = json.load(f).get("FileReferences", {})
    top = os.path.realpath(directory)

    def read(relative):
        path = os.path.realpath(os.path.join(top, relative))
        if os.path.dirname(path) != top and not path.startswith(top + os.sep):
            raise ValueError("the rigger's index points outside its folder: %s" % relative)
        with open(path, "rb") as f:
            return f.read()

    extras = {"motions": {}}
    if refs.get("Physics"):
        extras["physics"] = read(refs["Physics"])
    for group, entries in (refs.get("Motions") or {}).items():
        seen = set()
        for entry in entries:
            source = entry.get("File")
            if source and source not in seen:
                seen.add(source)
                extras["motions"].setdefault(group, []).append((source, read(source)))
    return extras


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("puppet")
    parser.add_argument("out_dir")
    parser.add_argument("--name")
    parser.add_argument("--extras", help="the rigger's --live2d folder (physics and motions)")
    args = parser.parse_args(argv)
    with open(args.puppet, "rb") as f:
        data = f.read()
    files, report = export(data, args.name, read_extras(args.extras) if args.extras else None)
    if os.path.isdir(args.out_dir):
        shutil.rmtree(os.path.join(args.out_dir, "textures"), ignore_errors=True)
    for path, content in files.items():
        full = os.path.join(args.out_dir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(content)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
