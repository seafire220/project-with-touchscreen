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

Blink, breathing, body sway and hair physics are left as the rigger made
them.

Usage: refine.py IN.inp OUT.inp
"""
import json
import math
import struct
import sys

MAGIC = b"TRNSRTS\0"
ANGLE_PARAMS = ("ParamAngleX", "ParamAngleY", "ParamAngleZ")

# How far the middle of the face slides at the end of the control's range,
# as a share of the face's width.
TURN_SHIFT = 0.13
NOD_SHIFT = 0.09
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


def height_on_surface(x, y, g):
    """1 at the middle of the face, falling to 0 at the outline of the head."""
    u = (x - g["centre"][0]) / g["half_width"]
    dy = y - g["centre"][1]
    v = dy / (g["up"] if dy < 0 else g["down"])
    return max(0.0, 1.0 - u * u - v * v)


def slide(x, y, g, turn, nod):
    """Turn and nod: how far the surface point at (x, y) slides. y grows downwards."""
    height = height_on_surface(x, y, g)
    return (TURN_SHIFT * g["face_width"] * height * turn, -NOD_SHIFT * g["face_width"] * height * nod)


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
    if group is not None:
        move = slide(g["anchors"][group][0], g["anchors"][group][1], g, turn, nod)
        return [move] * len(pts)
    return [slide(x, y, g, turn, nod) for x, y in pts]


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
    return report


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
