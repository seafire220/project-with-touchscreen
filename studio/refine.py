#!/usr/bin/env python3
"""Improve a rigged puppet's head movement and mouth.

Head movement
-------------

The image2live2d rigger turns the head by rotating the whole head group as
one flat card about a hinge far below the neck. An earlier version of this
tool replaced that with a warp that slid every mesh point separately, which
stretched and squashed the eyes and mouth while the head itself stayed put.

This version follows how hand-made Live2D and Inochi2D puppets are built:

  * Tilt: the whole head (face, features, hair) leans as one rigid piece
    about a point in the neck. The neck bends to follow, and long hair fades
    out of the movement below the neck so it hangs instead of swinging.
  * Turn and nod: the head is treated as a rounded surface. The middle of
    the face slides furthest, the cheeks and chin less, and the outline of
    the head not at all. Eyes, eyebrows, nose and mouth each move as a
    rigid piece by the amount at their own centre, so they never change
    shape. The face and hair bend smoothly around them.

Mouth
-----
The rigger opens the mouth by stretching the drawn mouth line, which is
often only a few pixels high, so the mouth hardly moves. partsplit.py draws
an open mouth sized to the face, hidden at rest. Here the mouth line fades
out as the mouth opens and the open mouth grows down from the line.

Body turn and lean
------------------
The rigger's body turn slid the whole head 40 pixels sideways (and its
lean 30 up or down), leaving empty space where the head had been. Now the
upper body turns as a cylinder about the spine: the middle of the chest
moves most, the outline is held and the turn dies out towards the hips.
The neck and head ride on the spine, so they move a few pixels, together;
each arm moves with its shoulder. A lean raises or lowers the shoulders,
neck and head together.

Blink, breathing and hair physics are left as the rigger made them.

Usage: refine.py IN.inp OUT.inp
"""
import json
import math
import struct
import sys

MAGIC = b"TRNSRTS\0"
ANGLE_PARAMS = ("ParamAngleX", "ParamAngleY", "ParamAngleZ")

# Turn and nod: how far the head turns at the end of the control's range.
TURN_ANGLE = math.radians(18)
NOD_ANGLE = math.radians(12)
# How far each kind of part stands out from the rounded head surface, in
# head half-widths: the nose stands out and so moves furthest. Parts not
# listed lie on the surface. Hair at the back lies behind the middle of the
# head, at this share of the front surface's depth, so it moves the other way.
DEPTH = {"nose": 0.18, "fringe": 0.06, "ears": -0.12}
BACK_DEPTH = 0.6
# Near the head's outline, points are held in place, so the outline only
# moves a little and nothing behind the head is uncovered. This is the depth
# below the surface (0 at the outline, 1 at the middle) where holding stops.
OUTLINE_HOLD = 0.35
# Each part follows a coarse grid of points, the way a Live2D artist puts each
# part in its own warp deformer: small parts and features keep their shape.
GRIDS = {"eye": (3, 3), "mouth": (3, 2), "nose": (2, 2), "blush": (2, 2)}
GRID_DEFAULT = (3, 3)
FEATURE_KINDS = ("eye", "mouth", "nose", "blush", "ear")
# Head lean at the end of the range, in radians (about 9 degrees).
MAX_TILT = 0.16
# The rounded surface: half-width as a share of face width (limits), and how
# far below the chin it ends, as a multiple of the eye-to-chin distance.
SURFACE_MIN = 0.62
SURFACE_MAX = 0.95
SURFACE_BELOW = 1.25
# Where the head leans from: this share of the way down the visible neck,
# but no further below the chin than this share of the face width.
PIVOT_DOWN_NECK = 0.5
PIVOT_LIMIT = 0.3
# Below the pivot, hair leaves the lean over this distance (in face widths).
HAIR_FADE = 0.9

# Parts that must keep their shape: each group moves as one rigid piece.
RIGID_GROUPS = {
    "eye_l": ("eye_l", "eye_white_l", "pupil_l", "eye_closed_l"),
    "eye_r": ("eye_r", "eye_white_r", "pupil_r", "eye_closed_r"),
    "mouth": ("mouth", "mouth_cavity"),
    "nose": ("nose",),
    "eyebrow_l": ("eyebrow_l",),
    "eyebrow_r": ("eyebrow_r",),
}


def read_puppet(data):
    if data[:8] != MAGIC:
        raise ValueError("not an Inochi2D puppet file")
    length = struct.unpack(">I", data[8:12])[0]
    return json.loads(data[12:12 + length]), data[12 + length:]


def write_puppet(puppet, rest):
    payload = json.dumps(puppet, separators=(",", ":")).encode()
    return MAGIC + struct.pack(">I", len(payload)) + payload + rest


def smoothstep(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def role_of(name):
    """'30_eye_white_l' -> 'eye_white_l'."""
    head, _, tail = name.partition("_")
    return tail if head.isdigit() else name


def walk_parts(node, origin=(0.0, 0.0), under=None, out=None, parents=()):
    """Every mesh part with its position on the canvas and the names of the nodes above it."""
    out = [] if out is None else out
    transform = node.get("transform", {})
    trans = transform.get("trans", [0.0, 0.0, 0.0])
    rot = transform.get("rot", [0.0, 0.0, 0.0])
    scale = transform.get("scale", [1.0, 1.0])
    if any(abs(r) > 1e-6 for r in rot) or any(abs(s - 1.0) > 1e-6 for s in scale):
        raise ValueError("node '%s' is rotated or scaled at rest; only plain offsets are supported" % node.get("name"))
    here = (origin[0] + trans[0], origin[1] + trans[1])
    if node.get("type") == "Part" and node.get("mesh", {}).get("verts"):
        out.append({"node": node, "origin": here, "parents": parents, "role": role_of(node.get("name", ""))})
    for child in node.get("children") or []:
        walk_parts(child, here, under, out, parents + (node.get("name"),))
    return out


def points(part):
    verts = part["node"]["mesh"]["verts"]
    ox, oy = part["origin"]
    return [(verts[i] + ox, verts[i + 1] + oy) for i in range(0, len(verts), 2)]


def box(point_list):
    xs = [p[0] for p in point_list]
    ys = [p[1] for p in point_list]
    return min(xs), min(ys), max(xs), max(ys)


def head_geometry(parts):
    """Measure the head: face, eye line, rounded surface and the point it leans from."""
    head_parts = [p for p in parts if "head" in p["parents"]]
    face = next((p for p in head_parts if p["role"] == "face_base"), None)
    if face is None:
        raise ValueError("the puppet has no face part under its head")
    left, top, right, chin = box(points(face))
    width = right - left
    if width <= 0 or chin <= top:
        raise ValueError("the face part has no size")
    centre_x = (left + right) / 2.0

    groups = {}
    for part in head_parts:
        for group, roles in RIGID_GROUPS.items():
            if part["role"] in roles:
                groups.setdefault(group, []).append(part)
    anchors = {}
    for group, members in groups.items():
        x0, y0, x1, y1 = box([pt for m in members for pt in points(m)])
        anchors[group] = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    eye_ys = [anchors[g][1] for g in ("eye_l", "eye_r") if g in anchors]
    eye_line = sum(eye_ys) / len(eye_ys) if eye_ys else top + 0.45 * (chin - top)
    eye_line = min(max(eye_line, top + 0.2 * (chin - top)), chin - 0.2 * (chin - top))

    hx0, hy0, hx1, _ = box([pt for p in head_parts for pt in points(p)])
    half_width = min(max((hx1 - hx0) / 2.0, SURFACE_MIN * width), SURFACE_MAX * width)
    up = min(max(eye_line - hy0, 0.5 * width), 1.1 * width)
    down = SURFACE_BELOW * (chin - eye_line)

    neck = next((p for p in parts if p["role"] == "neck"), None)
    pivot = (centre_x, chin)
    neck_bottom = None
    if neck is not None:
        nx0, _, nx1, ny1 = box(points(neck))
        if ny1 > chin:
            neck_bottom = ny1
            pivot = ((nx0 + nx1) / 2.0, chin + min(PIVOT_DOWN_NECK * (ny1 - chin), PIVOT_LIMIT * width))
    return {
        "head_parts": head_parts, "neck": neck, "groups": groups, "anchors": anchors,
        "face_width": width, "centre": (centre_x, eye_line), "half_width": half_width,
        "up": up, "down": down, "chin": chin, "pivot": pivot, "neck_bottom": neck_bottom,
    }


def surface_depth(x, y, g):
    """How far the head's rounded surface stands out at (x, y): 1 at the middle, 0 at the outline."""
    u = (x - g["centre"][0]) / g["half_width"]
    dy = y - g["centre"][1]
    v = dy / (g["up"] if dy < 0 else g["down"])
    return math.sqrt(max(0.0, 1.0 - u * u - v * v))


def turned(x, y, g, turn, nod, depth=(1.0, 0.0)):
    """Turn and nod: where the point at (x, y) goes when the head turns (turn) or nods (nod), each -1..1.

    The head is a rounded solid. Each point is turned with it about the
    head's middle, by its depth, and drawn straight on. `depth` is (side,
    extra): side 1 is the front surface, a negative side behind the middle,
    and extra is for parts that stand out from the surface. So the middle of the face
    moves furthest, the side turning away gets narrower and the near side
    wider, parts in front move more than the face and parts behind move the
    other way. Near the outline points are held, so the outline moves only a
    little. y grows downwards; a positive nod looks up.
    """
    rx = g["half_width"]
    dy = y - g["centre"][1]
    ry = g["up"] if dy < 0 else g["down"]
    u = (x - g["centre"][0]) / rx
    v = dy / ry
    s = surface_depth(x, y, g)
    hold = smoothstep(s / OUTLINE_HOLD)
    z = depth[0] * s + depth[1]
    a, b = TURN_ANGLE * turn, NOD_ANGLE * nod
    u2 = u * math.cos(a) + z * math.sin(a)
    z2 = z * math.cos(a) - u * math.sin(a)
    v2 = v * math.cos(b) - z2 * math.sin(b)
    return ((u2 - u) * rx * hold, (v2 - v) * ry * hold)


def kind_of(role):
    for key in ("eye", "mouth", "nose", "blush", "face_base", "hair", "ear"):
        if role.startswith(key) or key in role:
            return key
    return role


def depth_at(role, x, y, g):
    """Where a part lies at (x, y), by what it is, as (side, extra) for turned()."""
    kind = kind_of(role)
    if kind == "nose":
        return (1.0, DEPTH["nose"])
    if kind == "ear":
        return (1.0, DEPTH["ears"])
    if role.startswith("hair_back"):
        return (-BACK_DEPTH, 0.0)
    if kind == "hair":
        # The fringe lies over the forehead, in front of it; other hair is on the surface.
        inside = abs(x - g["centre"][0]) < 0.5 * g["face_width"] and y < g["centre"][1]
        return (1.0, DEPTH["fringe"] if inside else 0.0)
    return (1.0, 0.0)


def grid_offsets(pts, box_, shape, field):
    """Offsets for points that follow a coarse grid over box_: the field is worked out at the grid's
    points and spread between them, so a part changes shape smoothly, as in a Live2D warp deformer."""
    x0, y0, x1, y1 = box_
    nx, ny = shape
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    grid = [[field(x0 + w * i / (nx - 1), y0 + h * j / (ny - 1)) for i in range(nx)] for j in range(ny)]
    out = []
    for x, y in pts:
        fx = min(max((x - x0) / w, 0.0), 1.0) * (nx - 1)
        fy = min(max((y - y0) / h, 0.0), 1.0) * (ny - 1)
        i, j = min(int(fx), nx - 2), min(int(fy), ny - 2)
        tx, ty = fx - i, fy - j
        (a, b), (c, d) = grid[j][i], grid[j][i + 1]
        (e, f), (k, m) = grid[j + 1][i], grid[j + 1][i + 1]
        top = (a + (c - a) * tx, b + (d - b) * tx)
        bottom = (e + (k - e) * tx, f + (m - f) * tx)
        out.append((top[0] + (bottom[0] - top[0]) * ty, top[1] + (bottom[1] - top[1]) * ty))
    return out


def lean(x, y, g, tilt, fade):
    """Tilt: rotate about the pivot, fully above it and fading out over `fade` below it."""
    px, py = g["pivot"]
    weight = 1.0 if fade <= 0 else 1.0 - smoothstep((y - py) / fade)
    if y <= py:
        weight = 1.0
    angle = MAX_TILT * tilt * weight
    rx, ry = x - px, y - py
    return (rx * math.cos(angle) - ry * math.sin(angle) - rx, rx * math.sin(angle) + ry * math.cos(angle) - ry)


def offsets_for(part, g, name, position):
    """Per-point movement of one part for one control at one end of its range."""
    pts = points(part)
    group = next((k for k, members in g["groups"].items() if part in members), None)
    if name == "ParamAngleZ":
        if part is g["neck"]:
            fade = max(g["neck_bottom"] - g["pivot"][1], 1e-6)
        else:
            fade = HAIR_FADE * g["face_width"]
        return [lean(x, y, g, position, fade) for x, y in pts]
    turn = position if name == "ParamAngleX" else 0.0
    nod = position if name == "ParamAngleY" else 0.0
    if turn == 0.0 and nod == 0.0:
        return [(0.0, 0.0)] * len(pts)
    role = part["role"]
    kind = kind_of(role)
    if group is None and kind not in FEATURE_KINDS:
        # Face, hair and the like follow the rounded surface point by point, so the hold at the
        # outline is exact.
        return [turned(x, y, g, turn, nod, depth_at(role, x, y, g)) for x, y in pts]
    # A feature follows a coarse grid, so it keeps its shape; the pieces of a group (an eye with its
    # closed eye, the mouth with its open mouth) share the group's grid, so they stay together.
    members = g["groups"][group] if group is not None else [part]
    area = box([pt for m in members for pt in points(m)])
    shape = GRIDS.get(kind, GRID_DEFAULT)
    return grid_offsets(pts, area, shape, lambda x, y: turned(x, y, g, turn, nod, depth_at(role, x, y, g)))


def refine(puppet):
    """Rewrite the head-angle controls in place. Returns a short report."""
    parts = walk_parts(puppet["nodes"])
    g = head_geometry(parts)
    params = {p["name"]: p for p in puppet.get("param", [])}
    missing = [name for name in ANGLE_PARAMS if name not in params]
    if missing:
        raise ValueError("the puppet lacks head-angle controls: %s" % ", ".join(missing))
    head_node = next(n for n in _nodes(puppet["nodes"]) if n.get("name") == "head")
    moved = list(g["head_parts"])
    ids = {p["node"]["uuid"] for p in moved}
    if g["neck"] is not None and g["neck_bottom"] is not None:
        ids.add(g["neck"]["node"]["uuid"])
    report = {"head_parts": len(moved), "rigid_groups": sorted(g["groups"]), "neck_bends": g["neck_bottom"] is not None,
              "removed": 0, "added": 0}
    for name in ANGLE_PARAMS:
        param = params[name]
        if param["axis_points"] != [[0.0, 0.5, 1.0], [0.0]]:
            raise ValueError("%s does not have the expected three positions" % name)
        kept = []
        for binding in param["bindings"]:
            rigid = binding["node"] == head_node["uuid"] and binding["param_name"].startswith("transform.")
            ours = binding["node"] in ids and binding["param_name"] == "deform"
            if rigid or ours:
                report["removed"] += 1
            else:
                kept.append(binding)
        targets = list(moved)
        if name == "ParamAngleZ" and g["neck"] is not None and g["neck_bottom"] is not None:
            targets.append(g["neck"])
        for part in targets:
            columns = []
            for position in (-1.0, 0.0, 1.0):
                columns.append([[[round(dx, 3), round(dy, 3)] for dx, dy in offsets_for(part, g, name, position)]])
            kept.append({
                "node": part["node"]["uuid"],
                "param_name": "deform",
                "values": columns,
                "isSet": [[True], [True], [True]],
                "interpolate_mode": "Linear",
            })
            report["added"] += 1
        param["bindings"] = kept
    report.update(refine_mouth(puppet, parts))
    report.update(refine_body(puppet, parts, g))
    return report


BODY_PARAMS = ("ParamBodyAngleX", "ParamBodyAngleY")
# Body turn at the end of its range, and how far behind the chest's front the spine is (share of the
# body's half-width): the neck and head ride on the spine, so they move much less than the chest.
BODY_TURN_ANGLE = math.radians(8)
SPINE_DEPTH = 0.3
# Body lean: how far the shoulders, neck and head rise (lean back) or drop (lean forward) at the end
# of the range, as a share of the body's half-width.
BODY_LEAN = 0.05
BODY_BANDS = 40


def body_geometry(parts):
    """The upper body: its middle, half-width, shoulder line and where the turn has died out (hips)."""
    torso = next((p for p in parts if p["role"] == "torso"), None)
    if torso is None:
        return None
    pts = points(torso)
    x0, y0, x1, y1 = box(pts)
    arms = [p for p in parts if p["role"].startswith("arm")]
    shoulders = min([y0] + [box(points(a))[1] for a in arms])
    # The body's own width at each height, so the turn holds its real outline, not its widest point's.
    bands = []
    step = max((y1 - y0) / BODY_BANDS, 1e-6)
    for i in range(BODY_BANDS):
        lo, hi = y0 + i * step, y0 + (i + 1) * step
        xs = [x for x, y in pts if lo <= y <= hi]
        if xs:
            bands.append(((lo + hi) / 2.0, min(xs), max(xs)))
    return {"centre": (x0 + x1) / 2.0, "half_width": max((x1 - x0) / 2.0, 1e-6), "shoulders": shoulders,
            "hips": shoulders + 0.65 * (y1 - shoulders), "bands": bands}


def body_width_at(b, y):
    """The body's middle and half-width at height y, from its outline."""
    bands = b["bands"]
    if not bands:
        return b["centre"], b["half_width"]
    if y <= bands[0][0]:
        _, l, r = bands[0]
    elif y >= bands[-1][0]:
        _, l, r = bands[-1]
    else:
        for (ya, la, ra), (yb, lb, rb) in zip(bands, bands[1:]):
            if ya <= y <= yb:
                t = (y - ya) / max(yb - ya, 1e-6)
                l, r = la + (lb - la) * t, ra + (rb - ra) * t
                break
    return (l + r) / 2.0, max((r - l) / 2.0, 1e-6)


def body_moved(x, y, b, turn, lean, spine_only=False):
    """Where a point of the upper body goes when it turns (turn) or leans (lean), each -1..1.

    The chest turns as an upright cylinder about the spine: its middle moves most, the side turning away
    narrows, the outline is held. The turn fades out towards the hips. Near the shoulder line the body
    is at the spine's depth, so the collar moves with the neck. spine_only gives the spine's own
    movement at that height, which the neck and head follow.
    """
    up = 1.0 - smoothstep((y - b["shoulders"]) / max(b["hips"] - b["shoulders"], 1e-6))
    middle, rb = body_width_at(b, y)
    u = (x - middle) / rb
    if spine_only:
        u, s, hold, front = 0.0, 0.0, 1.0, 0.0
    else:
        s = math.sqrt(max(0.0, 1.0 - u * u))
        hold = smoothstep(s / OUTLINE_HOLD)
        front = smoothstep((y - b["shoulders"]) / max(0.3 * (b["hips"] - b["shoulders"]), 1e-6))
    z = SPINE_DEPTH + (1.0 - SPINE_DEPTH) * s * front
    a = BODY_TURN_ANGLE * turn * up
    dx = (u * math.cos(a) + z * math.sin(a) - u) * rb * hold
    dy = -BODY_LEAN * lean * up * b["half_width"]
    return dx, dy


def refine_body(puppet, parts, g):
    """Body turn and lean: replace the rigger's, which slid the whole head sideways or up and down.

    The upper body turns as a cylinder about the spine; the neck and head ride on the spine, so they
    move a little, together; each arm moves with its shoulder.
    """
    b = body_geometry(parts)
    params = {p["name"]: p for p in puppet.get("param", [])}
    if b is None:
        return {"body": "left as rigged"}
    rides = {p["node"]["uuid"] for p in g["head_parts"]}
    if g["neck"] is not None:
        rides.add(g["neck"]["node"]["uuid"])
    done = []
    for name in BODY_PARAMS:
        param = params.get(name)
        if param is None or len(param["axis_points"][0]) != 3:
            continue
        kept = [x for x in param["bindings"] if x["param_name"] != "deform"]
        for part in parts:
            uid = part["node"]["uuid"]
            pts = points(part)
            columns = []
            for position in (-1.0, 0.0, 1.0):
                turn = position if name == "ParamBodyAngleX" else 0.0
                lean = position if name == "ParamBodyAngleY" else 0.0
                if uid in rides and part["role"].startswith("hair"):
                    # Hair rides on the head down to the chin; below the shoulders it lies on the chest
                    # and moves with it, so the body under it is not uncovered.
                    spine = body_moved(b["centre"], b["shoulders"], b, turn, lean, spine_only=True)
                    span = max(b["shoulders"] - g["chin"], 1e-6)
                    offsets = []
                    for x, y in pts:
                        t = smoothstep((y - g["chin"]) / span)
                        chest = body_moved(x, max(y, b["shoulders"]), b, turn, lean)
                        offsets.append((spine[0] + (chest[0] - spine[0]) * t, spine[1] + (chest[1] - spine[1]) * t))
                elif uid in rides:
                    # The head and neck move as one with the top of the spine.
                    offsets = [body_moved(b["centre"], b["shoulders"], b, turn, lean, spine_only=True)] * len(pts)
                elif part["role"].startswith("arm"):
                    # An arm moves as one with its shoulder.
                    ax0, ay0, ax1, _ = box(pts)
                    offsets = [body_moved((ax0 + ax1) / 2.0, ay0, b, turn, lean)] * len(pts)
                else:
                    offsets = [body_moved(x, y, b, turn, lean) for x, y in pts]
                columns.append([[[round(dx, 3), round(dy, 3)] for dx, dy in offsets]])
            if any(abs(v) > 1e-9 for column in columns for pair in column[0] for v in pair):
                kept.append({"node": uid, "param_name": "deform", "values": columns,
                             "isSet": [[True], [True], [True]], "interpolate_mode": "Linear"})
        param["bindings"] = kept
        done.append(name)
    return {"body": done}


MOUTH_PARAM = "ParamMouthOpenY"
# Openness at which the open mouth is fully visible, and how visible the
# mouth line still is there.
MOUTH_SHOWN = 0.25
LINE_AT_SHOWN = 0.6


def refine_mouth(puppet, parts):
    """Rewrite the mouth control: the line fades as the open mouth grows from it."""
    params = {p["name"]: p for p in puppet.get("param", [])}
    param = params.get(MOUTH_PARAM)
    lips = next((p for p in parts if p["role"] == "mouth"), None)
    cavity = next((p for p in parts if p["role"] == "mouth_cavity"), None)
    if param is None or lips is None or cavity is None:
        return {"mouth": "left as rigged"}
    ours = {lips["node"]["uuid"], cavity["node"]["uuid"]}
    kept = [b for b in param["bindings"] if b["node"] not in ours]
    top = box(points(cavity))[1]
    keys = (0.0, MOUTH_SHOWN, 1.0)
    shut = [[0.0, round(top - y, 3)] for _, y in points(cavity)]

    def deform(node, columns):
        return {"node": node["uuid"], "param_name": "deform", "values": [[c] for c in columns],
                "isSet": [[True]] * len(columns), "interpolate_mode": "Linear"}

    def opacity(node, values):
        return {"node": node["uuid"], "param_name": "opacity", "values": [[v] for v in values],
                "isSet": [[True]] * len(values), "interpolate_mode": "Linear"}

    zeros = [[0.0, 0.0]] * len(shut)
    kept.append(deform(cavity["node"], [shut, [[0.0, round(dy * (1 - MOUTH_SHOWN), 3)] for _, dy in shut], zeros]))
    kept.append(opacity(cavity["node"], [0.0, 1.0, 1.0]))
    kept.append(opacity(lips["node"], [1.0, LINE_AT_SHOWN, 0.0]))
    param["axis_points"] = [list(keys), [0.0]]
    param["bindings"] = kept
    return {"mouth": "line fades, open mouth grows from it"}


def finish(data):
    """Refine a rigger puppet file. Returns (new file bytes, report)."""
    puppet, rest = read_puppet(data)
    report = refine(puppet)
    return write_puppet(puppet, rest), report


def _nodes(node):
    yield node
    for child in node.get("children") or []:
        yield from _nodes(child)


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    with open(argv[1], "rb") as f:
        data = f.read()
    try:
        data, report = finish(data)
    except (ValueError, StopIteration) as error:
        print("cannot refine this puppet: %s" % error, file=sys.stderr)
        return 1
    with open(argv[2], "wb") as f:
        f.write(data)
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
