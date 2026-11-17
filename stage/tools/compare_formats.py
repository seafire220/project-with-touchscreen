#!/usr/bin/env python3
"""Draw a character in both of its formats with the stage, pose by pose, and compare.

    compare_formats.py STAGE CHARACTER_DIR OUT.png [--min-overlap 0.98] [--hold 2.0]

CHARACTER_DIR is an unpacked character package: it needs `visual/puppet.inp` and the
Live2D-format copy `visual/live2d/model.model3.json` (made with `make_character.py
--live2d`). Each pose is drawn by the stage from the Inochi2D puppet and from the
Live2D-format copy (played by Ayagami), whole-body, on a magenta background. For
each pose the report gives the overlap of the two silhouettes (intersection over
union) and the mean colour difference where both are drawn. OUT.png shows the two
drawings side by side, and a third column with the differences in red.

Exits with status 1 if any pose overlaps less than --min-overlap. Hair swings by
each format's own physics, so poses are held (--hold seconds) to let it settle.
Needs Xvfb, numpy and Pillow.
"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw

SIZE = (360, 640)
BACKGROUND = "ff00ff"
REST = {"ParamAngleX": 0, "ParamAngleY": 0, "ParamAngleZ": 0, "ParamBodyAngleX": 0, "ParamBodyAngleY": 0,
        "ParamBodyAngleZ": 0, "ParamBreath": 0, "ParamEyeLOpen": 1, "ParamEyeROpen": 1, "ParamMouthOpenY": 0,
        "ParamMouthForm": 0, "ParamArmLA": 0, "ParamArmRA": 0, "ParamArmLB": 0, "ParamArmRB": 0}
POSES = [
    ("rest", {}),
    ("turn left", {"ParamAngleX": -30}),
    ("turn right", {"ParamAngleX": 30}),
    ("nod down", {"ParamAngleY": -30}),
    ("nod up", {"ParamAngleY": 30}),
    ("tilt", {"ParamAngleZ": 30}),
    ("diagonal", {"ParamAngleX": 30, "ParamAngleY": 30}),
    ("body turn", {"ParamBodyAngleX": 10}),
    ("body lean", {"ParamBodyAngleY": 10, "ParamBodyAngleZ": 10}),
    ("blink", {"ParamEyeLOpen": 0, "ParamEyeROpen": 0}),
    ("talk", {"ParamMouthOpenY": 1, "ParamMouthForm": 1}),
    ("arms", {"ParamArmLA": 10, "ParamArmRA": -10, "ParamArmLB": 10, "ParamArmRB": -10}),
    ("breath", {"ParamBreath": 1}),
]


def draw(stage, character, names, hold):
    """Render each pose with the stage; returns RGB arrays in pose order."""
    lines, captures, t = [], [], 0.5
    for _, values in POSES:
        known = {k: v for k, v in dict(REST, **values).items() if k in names}
        lines.append({"at": round(t, 2), "set": known, "ease": 0})
        t += hold
        captures.append(round(t - 0.05, 2))
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "script.jsonl")
        with open(script, "w") as f:
            f.write("\n".join(json.dumps(line) for line in lines) + "\n")
        frames = os.path.join(tmp, "frames")
        os.makedirs(frames)
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 %dx%dx24" % (SIZE[0] + 64, SIZE[1] + 64), stage, character,
               "--size", "%dx%d" % SIZE, "--gl", "auto", "--still", "--no-stdin", "--background", BACKGROUND,
               "--script", script, "--fixed-dt", "0.02", "--capture-dir", frames,
               "--capture-at", ",".join("%.2f" % c for c in captures), "--exit-after", "%.2f" % (captures[-1] + 0.1)]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        events = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
        fatal = [e for e in events if e.get("event") == "fatal"]
        if run.returncode != 0 or fatal:
            raise RuntimeError("stage failed on %s: %s" % (character, (fatal or [run.stderr[-400:]])[0]))
        return [np.asarray(Image.open(os.path.join(frames, "frame_%03d.png" % i)).convert("RGB")).astype(int)
                for i in range(len(POSES))]


def param_names(stage, character):
    run = subprocess.run(["xvfb-run", "-a", stage, character, "--size", "64x64", "--no-stdin", "--fixed-dt", "0.02",
                          "--exit-after", "0.05"], capture_output=True, text=True, timeout=600)
    for line in run.stdout.splitlines():
        if line.startswith("{"):
            event = json.loads(line)
            if event.get("event") == "ready":
                return set(event["param_names"])
    raise RuntimeError("stage did not start on %s: %s" % (character, run.stderr[-400:]))


def covered(image):
    background = np.array([int(BACKGROUND[i:i + 2], 16) for i in (0, 2, 4)])
    return np.abs(image - background).sum(-1) > 40


def main(argv):
    min_overlap, hold = 0.98, 2.0
    args = list(argv[1:])
    for flag in ("--min-overlap", "--hold"):
        if flag in args:
            i = args.index(flag)
            value = float(args[i + 1])
            del args[i:i + 2]
            if flag == "--min-overlap":
                min_overlap = value
            else:
                hold = value
    if len(args) != 3:
        print(__doc__)
        return 2
    stage, folder, out_path = args
    inp = os.path.join(folder, "visual", "puppet.inp")
    model = os.path.join(folder, "visual", "live2d", "model.model3.json")
    names = param_names(stage, inp) & param_names(stage, model)
    a_frames, b_frames = draw(stage, inp, names, hold), draw(stage, model, names, hold)
    report, rows, worst = [], [], 1.0
    for (name, _), a, b in zip(POSES, a_frames, b_frames):
        ma, mb = covered(a), covered(b)
        overlap = float((ma & mb).sum() / max((ma | mb).sum(), 1))
        both = ma & mb
        colour = float(np.abs(a - b)[both].mean()) if both.any() else 0.0
        worst = min(worst, overlap)
        report.append({"pose": name, "overlap": round(overlap, 4), "colour_difference": round(colour, 2)})
        diff = np.zeros_like(a)
        diff[ma | mb] = (60, 60, 60)
        diff[ma ^ mb] = (255, 40, 40)
        diff[both & (np.abs(a - b).sum(-1) > 60)] = (255, 160, 40)
        row = np.hstack([a, b, diff]).astype(np.uint8)
        tile = Image.fromarray(row)
        ImageDraw.Draw(tile).text((6, 6), "%s  overlap %.4f" % (name, overlap), fill=(255, 255, 255))
        rows.append(tile)
    sheet = Image.new("RGB", (rows[0].width * 2, rows[0].height * ((len(rows) + 1) // 2)))
    for i, tile in enumerate(rows):
        sheet.paste(tile, ((i % 2) * tile.width, (i // 2) * tile.height))
    sheet.save(out_path)
    print(json.dumps({"poses": report, "worst_overlap": round(worst, 4), "min_overlap": min_overlap}, indent=1))
    return 0 if worst >= min_overlap else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
