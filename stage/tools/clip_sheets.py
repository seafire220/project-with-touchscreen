#!/usr/bin/env python3
"""Play every gesture, idle action, mood and state on the real stage for one character, and save
sheets of frames to look at.

    python3 stage/tools/clip_sheets.py CHARACTER.char OUT_DIR [--name NAME] [--background RRGGBB]

CHARACTER.char is a package made by the studio (it holds both the Inochi2D puppet, used here only to
find the head, and the Live2D-format model the device plays). Writes to OUT_DIR:

  NAME_peaks.png    each gesture and idle action at its largest moment, then each mood and state,
                    head to hips
  NAME_face.png     the head close up: at rest, through a blink, mouth opening, each mood, head turns
                    and nods, looking around
  NAME_motion.png   six moments through the wave, hands on hips, shrug, stretch, yawn and nodding off
  NAME_events.json  what the stage said it played: a stand-in in place of a gesture the character
                    cannot make ("played"), anything skipped, any error

Needs Xvfb and a release build of the stage (stage/target/release/stage). Runs in about ten seconds.
Used for the test of all eleven test characters (docs/27-character-tests.md).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(HERE, "..", "target", "release", "stage")
LIBRARY = os.path.join(HERE, "..", "motions", "library.json")
sys.path.insert(0, HERE)
import pose_sheet  # noqa: E402

MOTION = ["wave", "hands_on_hips", "shrug", "stretch", "yawn", "nod_off"]


def font():
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", 15)
    except OSError:
        return ImageFont.load_default()


def value_at(track, t):
    if t <= track[0][0]:
        return track[0][1]
    for (t0, v0), (t1, v1) in zip(track, track[1:]):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * (t - t0) / max(t1 - t0, 1e-6)
    return track[-1][1]


def clip_timing(clip):
    """(length, moment of its largest pose) of a clip's first take; arms count double."""
    tracks = clip.get("tracks") or clip["takes"][0]["tracks"]
    length = max(p[0] for track in tracks.values() for p in track)
    best, best_t, t = -1.0, length / 2, 0.0
    while t <= length:
        size = sum((2.0 if key.startswith("arm") else 1.0) * abs(value_at(track, t)) for key, track in tracks.items())
        if size > best:
            best, best_t = size, t
        t += 0.02
    return length, best_t


def run_stage(model, view, size, lines, captures, frames_dir, background, env):
    """Play a script on the stage, saving frames at the given times. Returns (frames, events)."""
    os.makedirs(frames_dir, exist_ok=True)
    for old in os.listdir(frames_dir):
        os.remove(os.path.join(frames_dir, old))
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as script:
        script.write("\n".join(json.dumps(line) for line in lines) + "\n")
    cmd = [STAGE, model, "--size", "%dx%d" % size, "--gl", "es", "--still", "--no-stdin", "--background", background,
           "--script", script.name, "--fixed-dt", "0.02", "--capture-dir", frames_dir,
           "--capture-at", ",".join("%.2f" % t for t in captures), "--exit-after", "%.2f" % (captures[-1] + 0.1)]
    if view:
        cmd[2:2] = ["--view", ",".join("%.2f" % v for v in pose_sheet.fit_aspect(view, size))]
    try:
        run = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1200)
    finally:
        os.unlink(script.name)
    if run.returncode != 0:
        raise RuntimeError("the stage failed: %s" % run.stderr[-500:])
    events = []
    for line in run.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    frames = [Image.open(os.path.join(frames_dir, "frame_%03d.png" % i)).convert("RGB") for i in range(len(captures))]
    return frames, events


def sheet(frames, names, cols):
    f = font()
    w, h = frames[0].size
    out = Image.new("RGB", (w * cols, h * ((len(frames) + cols - 1) // cols)), (30, 30, 30))
    for i, (frame, name) in enumerate(zip(frames, names)):
        d = ImageDraw.Draw(frame)
        d.rectangle((0, 0, 8 * len(name) + 10, 20), fill=(0, 0, 0))
        d.text((4, 2), name, fill=(255, 255, 0), font=f)
        out.paste(frame, (w * (i % cols), h * (i // cols)))
    return out


def peaks_script(library):
    lines, caps, names, t = [{"at": 0.2, "state": "idle"}], [], [], 1.5
    for section in ("gestures", "actions"):
        for name, clip in library[section].items():
            if name.startswith("_"):
                continue
            length, peak = clip_timing(clip)
            lines.append({"at": round(t, 2), "gesture": name})
            caps.append(round(t + peak, 2))
            names.append(name)
            t += length + 0.8
    for mood in library["moods"]:
        lines.append({"at": round(t, 2), "emotion": mood})
        caps.append(round(t + 2.4, 2))
        names.append("mood " + mood)
        t += 3.2
    lines.append({"at": round(t, 2), "emotion": "neutral"})
    t += 1.0
    for state in ("listening", "thinking"):
        lines.append({"at": round(t, 2), "state": state})
        caps.append(round(t + 1.8, 2))
        names.append("state " + state)
        t += 2.2
    lines += [{"at": round(t, 2), "state": "speaking"}, {"at": round(t + 0.05, 2), "mouth": 0.8}]
    caps.append(round(t + 0.6, 2))
    names.append("speaking")
    lines.append({"at": round(t + 1.0, 2), "state": "idle"})
    return lines, caps, names


def face_script(library):
    lines, caps, names, t = [{"at": 0.2, "state": "idle"}], [1.0], ["rest"], 1.5
    lines.append({"at": t, "blink": True})
    for dt in (0.04, 0.08, 0.12, 0.16):
        caps.append(round(t + dt, 2))
        names.append("blink +%.2f" % dt)
    t += 1.0
    lines.append({"at": t, "state": "speaking"})
    for m in (0.3, 0.6, 1.0):
        lines.append({"at": round(t, 2), "mouth": m})
        caps.append(round(t + 0.4, 2))
        names.append("mouth %.1f" % m)
        t += 0.6
    lines += [{"at": round(t, 2), "mouth": 0.0}, {"at": round(t + 0.1, 2), "state": "idle"}]
    t += 0.8
    for mood in library["moods"]:
        lines.append({"at": round(t, 2), "emotion": mood})
        caps.append(round(t + 2.4, 2))
        names.append(mood)
        t += 3.2
    lines.append({"at": round(t, 2), "emotion": "neutral"})
    t += 1.2
    for name, params in (("turn +30", {"ParamAngleX": 30}), ("turn -30", {"ParamAngleX": -30}),
                         ("nod up", {"ParamAngleY": 30}), ("nod down", {"ParamAngleY": -30}),
                         ("tilt", {"ParamAngleZ": 20}), ("diagonal", {"ParamAngleX": 25, "ParamAngleY": 20})):
        lines += [{"at": round(t, 2), "clear": True, "ease": 0}, {"at": round(t + 0.01, 2), "set": params, "ease": 0.25}]
        caps.append(round(t + 1.0, 2))
        names.append(name)
        t += 1.2
    lines.append({"at": round(t, 2), "clear": True, "ease": 0})
    t += 0.5
    for name, xy in (("look left", [-1, 0]), ("look right", [1, 0]), ("look up", [0, 1])):
        lines.append({"at": round(t, 2), "look": xy})
        caps.append(round(t + 1.0, 2))
        names.append(name)
        t += 1.2
    return lines, caps, names


def motion_script(library):
    lines, caps, names, t = [{"at": 0.2, "state": "idle"}], [], [], 1.5
    for name in MOTION:
        section = "gestures" if name in library["gestures"] else "actions"
        length, _ = clip_timing(library[section][name])
        lines.append({"at": round(t, 2), "gesture": name})
        for k in range(6):
            at = length * (k + 0.5) / 6
            caps.append(round(t + at, 2))
            names.append("%s %.1fs" % (name, at))
        t += length + 0.8
    return lines, caps, names


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("package")
    parser.add_argument("out")
    parser.add_argument("--name")
    parser.add_argument("--background", default="b4b4b4", help="a mid grey shows dark and light characters")
    args = parser.parse_args(argv)
    name = args.name or os.path.splitext(os.path.basename(args.package))[0]
    library = json.load(open(LIBRARY))
    os.makedirs(args.out, exist_ok=True)
    with tempfile.TemporaryDirectory() as unpacked:
        with zipfile.ZipFile(args.package) as z:
            z.extractall(unpacked)
        model = os.path.join(unpacked, "visual", "live2d", "model.model3.json")
        inp = os.path.join(unpacked, "visual", "puppet.inp")
        if not os.path.exists(inp):
            raise SystemExit("this package has no studio puppet (visual/puppet.inp) to find the head with")
        if not os.path.exists(model):
            model = inp                                # an older package: the Inochi2D puppet alone
        head, full = pose_sheet.views(pose_sheet.read_puppet(inp))
        x0, y0, x1, y1 = full
        w, h = x1 - x0, y1 - y0
        # Live2D-format views are in canvas pixels: the puppet's bounds grown by a twentieth each way.
        lo = (x0 - 0.05 * w, y0 - 0.05 * h) if model.endswith(".json") else (0.0, 0.0)

        def place(box):
            return (box[0] - lo[0], box[1] - lo[1], box[2] - lo[0], box[3] - lo[1])
        size = head[2] - head[0]
        cx = (head[0] + head[2]) / 2
        upper = place((cx - 1.2 * size, head[1], cx + 1.2 * size, min(head[1] + 2.6 * size, y1 + 0.02 * h)))
        face = place((head[0] - 0.1 * size, head[1] - 0.05 * size, head[2] + 0.1 * size, head[3] + 0.15 * size))
        xvfb = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "1200x1200x24"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        env = dict(os.environ, DISPLAY=":" + xvfb.stdout.readline().strip(), LIBGL_ALWAYS_SOFTWARE="1")
        report = {"name": name}
        try:
            frames_dir = os.path.join(unpacked, "frames")
            for kind, script, view, tile, cols in (("peaks", peaks_script, upper, (300, 290), 7),
                                                   ("face", face_script, face, (220, 220), 8),
                                                   ("motion", motion_script, upper, (300, 290), 6)):
                lines, caps, names = script(library)
                frames, events = run_stage(model, view, tile, lines, caps, frames_dir, args.background, env)
                sheet(frames, names, cols).save(os.path.join(args.out, "%s_%s.png" % (name, kind)))
                if kind == "peaks":
                    ready = next((e for e in events if e.get("event") == "ready"), {})
                    report["gestures_available"] = ready.get("gestures")
                    report["actions_available"] = ready.get("actions")
                    played = [e for e in events if e.get("event") == "gesture"]
                    report["stand_ins"] = {e["name"]: e["played"] for e in played if e.get("played")}
                    report["skipped"] = [e for e in events if e.get("event") == "gesture_skipped"]
                    report["errors"] = [e for e in events if e.get("event") in ("error", "fatal")]
        finally:
            xvfb.terminate()
    with open(os.path.join(args.out, name + "_events.json"), "w") as f:
        json.dump(report, f, indent=1)
    print(json.dumps({k: report[k] for k in ("stand_ins", "skipped", "errors")}))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
