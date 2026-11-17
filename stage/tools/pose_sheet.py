#!/usr/bin/env python3
"""Render a puppet in a set of poses, for a person to judge by eye.

Writes to OUT_DIR:
  sheet.png   close-ups of the head and whole-figure views in each pose:
              rest, turn left/right, nod up/down, tilt left/right, blink,
              mouth open
  motion.gif  a close-up of the head sweeping through turn, nod and tilt

Unlike visual_test.py this checks nothing; it exists because automatic
checks have passed puppets that looked wrong.

Usage: pose_sheet.py STAGE_BINARY PUPPET.inp OUT_DIR [--gl es|desktop|auto]

Needs Xvfb and Pillow.
"""
import json
import math
import os
import struct
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

BACKGROUND = (16, 16, 20)
CLOSE = (360, 360)
FULL = (240, 360)
WARM_UP = 6.0
HOLD = 2.0

POSES = [
    ("rest", {}),
    ("turn -", {"ParamAngleX": -30}),
    ("turn +", {"ParamAngleX": 30}),
    ("nod -", {"ParamAngleY": -30}),
    ("nod +", {"ParamAngleY": 30}),
    ("tilt -", {"ParamAngleZ": -30}),
    ("tilt +", {"ParamAngleZ": 30}),
    ("blink", {"ParamEyeLOpen": 0, "ParamEyeROpen": 0}),
    ("mouth", {"ParamMouthOpenY": 1}),
]


def read_puppet(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"TRNSRTS\0":
        raise ValueError("not an Inochi2D puppet file")
    length = struct.unpack(">I", data[8:12])[0]
    return json.loads(data[12:12 + length])


def part_boxes(node, origin=(0.0, 0.0), parents=()):
    """(name, parents, box) of every mesh part, in puppet units."""
    trans = node.get("transform", {}).get("trans", [0.0, 0.0])
    here = (origin[0] + trans[0], origin[1] + trans[1])
    verts = node.get("mesh", {}).get("verts") if node.get("type") == "Part" else None
    if verts:
        xs, ys = verts[0::2], verts[1::2]
        yield node.get("name", ""), parents, (min(xs) + here[0], min(ys) + here[1], max(xs) + here[0], max(ys) + here[1])
    for child in node.get("children") or []:
        yield from part_boxes(child, here, parents + (node.get("name"),))


def views(puppet):
    """Boxes to frame: the head close up, and the whole figure."""
    boxes = list(part_boxes(puppet["nodes"]))
    if not boxes:
        raise ValueError("the puppet has no visible parts")
    x0 = min(b[2][0] for b in boxes); y0 = min(b[2][1] for b in boxes)
    x1 = max(b[2][2] for b in boxes); y1 = max(b[2][3] for b in boxes)
    face = next((b[2] for b in boxes if b[0].endswith("face_base")), None)
    if face is None:
        # A hand-made puppet: assume the head is the top fifth of the figure.
        size = (y1 - y0) * 0.2
        cx, cy = (x0 + x1) / 2.0, y0 + size * 0.5
    else:
        size = (face[2] - face[0]) * 2.6
        cx, cy = (face[0] + face[2]) / 2.0, (face[1] + face[3]) / 2.0 - 0.1 * size
    close = (cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)
    return close, (x0, y0, x1, y1)


def fit_aspect(box, size):
    """Grow a box so it has the render size's shape."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    want = size[0] / size[1]
    if w / h < want:
        grow = (h * want - w) / 2
        return (x0 - grow, y0, x1 + grow, y1)
    grow = (w / want - h) / 2
    return (x0, y0 - grow, x1, y1 + grow)


def run_stage(binary, puppet, view, size, script_lines, captures, gl, env, out_dir, tag):
    script = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    script.write("\n".join(json.dumps(line) for line in script_lines) + "\n")
    script.close()
    frames = os.path.join(out_dir, "frames_" + tag)
    os.makedirs(frames, exist_ok=True)
    for name in os.listdir(frames):
        os.remove(os.path.join(frames, name))
    cmd = [binary, puppet, "--size", "%dx%d" % size, "--gl", gl, "--still", "--no-stdin",
           "--view", ",".join("%.2f" % v for v in fit_aspect(view, size)),
           "--script", script.name, "--fixed-dt", "0.02",
           "--capture-dir", frames, "--capture-at", ",".join("%.2f" % t for t in captures),
           "--exit-after", "%.2f" % (captures[-1] + 0.1)]
    try:
        run = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    finally:
        os.unlink(script.name)
    errors = [l for l in run.stdout.splitlines() if '"error"' in l or '"fatal"' in l]
    if run.returncode != 0 or errors:
        raise RuntimeError("stage failed: %s %s" % (errors[:3], run.stderr[-300:]))
    return [Image.open(os.path.join(frames, "frame_%03d.png" % i)).convert("RGB") for i in range(len(captures))]


def pose_script():
    lines = [{"at": 0.2, "state": "idle"}]
    captures = []
    t = WARM_UP
    for _, params in POSES:
        lines.append({"at": round(t, 2), "clear": True, "ease": 0})
        if params:
            lines.append({"at": round(t + 0.01, 2), "set": params, "ease": 0.25})
        t += HOLD
        captures.append(round(t - 0.05, 2))
    return lines, captures


def motion_script():
    """Turn left and right, nod, then tilt, as smooth sweeps."""
    lines, captures = [{"at": 0.2, "state": "idle"}], []
    t = WARM_UP
    step = 0.08
    for name in ("ParamAngleX", "ParamAngleY", "ParamAngleZ"):
        for i in range(31):
            value = 30.0 * math.sin(2 * math.pi * i / 30)
            lines.append({"at": round(t, 2), "set": {name: round(value, 2)}, "ease": 0})
            captures.append(round(t + step * 0.5, 3))
            t += step
        lines.append({"at": round(t, 2), "set": {name: None}, "ease": 0})
        t += 0.1
    return lines, captures


def label(tile, text):
    draw = ImageDraw.Draw(tile)
    draw.rectangle((0, 0, 8 + 7 * len(text), 16), fill=(0, 0, 0))
    draw.text((4, 2), text, fill=(255, 255, 255))
    return tile


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    binary, puppet_path, out_dir = sys.argv[1:4]
    gl = sys.argv[sys.argv.index("--gl") + 1] if "--gl" in sys.argv else "auto"
    os.makedirs(out_dir, exist_ok=True)
    close, full = views(read_puppet(puppet_path))

    xvfb = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "800x1000x24"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    display = ":" + xvfb.stdout.readline().strip()
    env = dict(os.environ, DISPLAY=display, LIBGL_ALWAYS_SOFTWARE="1")
    env.pop("WAYLAND_DISPLAY", None)
    try:
        lines, captures = pose_script()
        close_frames = run_stage(binary, puppet_path, close, CLOSE, lines, captures, gl, env, out_dir, "close")
        full_frames = run_stage(binary, puppet_path, full, FULL, lines, captures, gl, env, out_dir, "full")
        lines, captures = motion_script()
        motion = run_stage(binary, puppet_path, close, (300, 300), lines, captures, gl, env, out_dir, "motion")
    finally:
        xvfb.terminate()

    columns = len(POSES)
    sheet = Image.new("RGB", (columns * CLOSE[0], CLOSE[1] + FULL[1]), BACKGROUND)
    for i, (name, _) in enumerate(POSES):
        sheet.paste(label(close_frames[i], name), (i * CLOSE[0], 0))
        sheet.paste(full_frames[i], (i * CLOSE[0] + (CLOSE[0] - FULL[0]) // 2, CLOSE[1]))
    sheet.save(os.path.join(out_dir, "sheet.png"))
    motion[0].save(os.path.join(out_dir, "motion.gif"), save_all=True, append_images=motion[1:],
                   duration=80, loop=0)
    print(json.dumps({"sheet": os.path.join(out_dir, "sheet.png"), "motion": os.path.join(out_dir, "motion.gif")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
