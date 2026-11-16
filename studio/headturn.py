#!/usr/bin/env python3
"""Replace a puppet's rigid head turn with an in-place warp.

The image2live2d rigger turns the head by rotating the whole head group as
one flat card. With long hair attached, the card's hinge ends up far below
the neck, so the head swings like a detached piece and uncovers what was
behind it.

Hand-made Live2D and Inochi2D puppets turn the head differently: nothing is
moved bodily. Each part's mesh is bent so that the features slide across the
face as if over a ball, the far side narrows, and the chin stays where it
is, joined to the neck. This tool rewrites a rigger puppet to do the same:

  * turn left/right and nod up/down: every head part is warped by one shared
    displacement field taken from a ball centred on the head. Points near the
    middle of the face move most; the rim of the head and everything below
    the chin hardly move.
  * tilt: the head leans about the base of the neck, fading out below the
    chin so long hair bends instead of swinging.

Only the three head-angle controls are changed. Blink, mouth, breathing, body
sway and hair physics are left as the rigger made them.

Usage: headturn.py IN.inp OUT.inp
"""
import copy
import json
import math
import struct
import sys

MAGIC = b"TRNSRTS\0"
ANGLE_PARAMS = ("ParamAngleX", "ParamAngleY", "ParamAngleZ")

# Head turn at the ends of the control's range, in radians.
MAX_YAW = 0.38
MAX_PITCH = 0.28
MAX_TILT = 0.16
# The ball's radius as a multiple of half the face width, and how far above
# the middle of the face its centre sits, as a share of the radius.
BALL_RADIUS = 1.55
BALL_RAISE = 0.18
# How far below the chin the movement fades to nothing, in ball radii.
FADE_BELOW_CHIN = 1.1


def read_puppet(data):
    if data[:8] != MAGIC:
        raise ValueError("not an Inochi2D puppet file")
    length = struct.unpack(">I", data[8:12])[0]
    return json.loads(data[12:12 + length]), data[12 + length:]


def write_puppet(puppet, rest):
    payload = json.dumps(puppet, separators=(",", ":")).encode()
    return MAGIC + struct.pack(">I", len(payload)) + payload + rest


def find_node(node, name):
    if node.get("name") == name:
        return node
    for child in node.get("children") or []:
        found = find_node(child, name)
        if found:
            return found
    return None


def smoothstep(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def head_geometry(head):
    """Where the ball and the neck are, from the face part's outline."""
    parts = [n for n in head.get("children") or [] if n.get("type") == "Part" and n.get("mesh")]
    face = next((p for p in parts if "face_base" in p["name"]), None)
    if face is None:
        raise ValueError("the puppet has no face part under its head")
    xs, ys = face["mesh"]["verts"][0::2], face["mesh"]["verts"][1::2]
    ox, oy = face["transform"]["trans"][0], face["transform"]["trans"][1]
    left, right, top, chin = min(xs) + ox, max(xs) + ox, min(ys) + oy, max(ys) + oy
    radius = BALL_RADIUS * (right - left) / 2.0
    centre = ((left + right) / 2.0, (top + chin) / 2.0 - BALL_RAISE * radius)
    return parts, centre, radius, ((left + right) / 2.0, chin)


def displacement(x, y, centre, radius, neck, yaw, pitch, tilt, depth=1.0):
    """How far one mesh point moves for the given head angles (y grows downwards)."""
    u, v = (x - centre[0]) / radius, (y - centre[1]) / radius
    inside = max(0.0, 1.0 - (u * u + v * v))
    bulge = depth * inside * inside          # height above the head's rim, smooth at the edge
    # Everything fades out below the chin so the head stays joined to the neck.
    weight = 1.0 - smoothstep((y - neck[1]) / (FADE_BELOW_CHIN * radius))
    dx = radius * (u * (math.cos(yaw) - 1.0) + bulge * math.sin(yaw))
    dy = radius * (v * (math.cos(pitch) - 1.0) - bulge * math.sin(pitch))
    # Tilt: lean about the base of the neck.
    angle = tilt * weight
    rx, ry = x - neck[0], y - neck[1]
    tx = rx * math.cos(angle) - ry * math.sin(angle) - rx
    ty = rx * math.sin(angle) + ry * math.cos(angle) - ry
    return (dx * weight + tx, dy * weight + ty)


def part_depth(name):
    """Hair in front of the face sits slightly proud of it, so it slides a little further."""
    return 1.08 if "hair_front" in name else (0.92 if "hair_back" in name else 1.0)


def refine(puppet):
    """Rewrite the head-angle controls in place. Returns a short report."""
    head = find_node(puppet["nodes"], "head")
    if head is None:
        raise ValueError("the puppet has no node called 'head'")
    parts, centre, radius, neck = head_geometry(head)
    params = {p["name"]: p for p in puppet.get("param", [])}
    missing = [name for name in ANGLE_PARAMS if name not in params]
    if missing:
        raise ValueError("the puppet lacks head-angle controls: %s" % ", ".join(missing))
    part_ids = {p["uuid"] for p in parts}
    report = {"head_parts": len(parts), "ball_radius": round(radius, 1), "removed": 0, "added": 0}
    for name in ANGLE_PARAMS:
        param = params[name]
        if param["axis_points"] != [[0.0, 0.5, 1.0], [0.0]]:
            raise ValueError("%s does not have the expected three positions" % name)
        kept = []
        for binding in param["bindings"]:
            rigid = binding["node"] == head["uuid"] and binding["param_name"].startswith("transform.")
            ours = binding["node"] in part_ids and binding["param_name"] == "deform"
            if rigid or ours:
                report["removed"] += 1
            else:
                kept.append(binding)
        for part in parts:
            verts = part["mesh"]["verts"]
            ox, oy = part["transform"]["trans"][0], part["transform"]["trans"][1]
            depth = part_depth(part["name"])
            columns = []
            for position in (-1.0, 0.0, 1.0):
                yaw = MAX_YAW * position if name == "ParamAngleX" else 0.0
                pitch = MAX_PITCH * position if name == "ParamAngleY" else 0.0
                tilt = MAX_TILT * position if name == "ParamAngleZ" else 0.0
                offsets = []
                for i in range(0, len(verts), 2):
                    dx, dy = displacement(verts[i] + ox, verts[i + 1] + oy, centre, radius, neck, yaw, pitch, tilt, depth)
                    offsets.append([round(dx, 3), round(dy, 3)])
                columns.append([offsets])
            kept.append({
                "node": part["uuid"],
                "param_name": "deform",
                "values": columns,
                "isSet": [[True], [True], [True]],
                "interpolate_mode": "Linear",
            })
            report["added"] += 1
        param["bindings"] = kept
    return report


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    with open(argv[1], "rb") as f:
        puppet, rest = read_puppet(f.read())
    try:
        report = refine(puppet)
    except ValueError as error:
        print("cannot refine this puppet: %s" % error, file=sys.stderr)
        return 1
    with open(argv[2], "wb") as f:
        f.write(write_puppet(puppet, rest))
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
