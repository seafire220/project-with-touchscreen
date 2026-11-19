#!/usr/bin/env python3
"""Play full-body animation clips (.vrma) on a VRM avatar with the real stage, and save sheets of
frames (and, if asked, animated GIFs) to look at.

    python3 stage/tools/vrma_sheets.py AVATAR.vrm OUT_DIR [--clips DIR] [--only a,b] [--frames 6]
                                       [--shot upper|full|bust] [--gif] [--name NAME]

Idle loops (idle, idle_*) are each shown as the avatar's only loop, round once; gestures and idle
actions are played as the stage plays them in the full-body style (`{"gesture": name}`), over the
plain idle loop. Writes NAME_loops.png and NAME_gestures.png (one row per clip, frames across it),
and with --gif NAME_<clip>.gif for each clip.

Needs Xvfb and a release build of the stage (stage/target/release/stage).
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import clip_sheets  # noqa: E402

DEFAULT_CLIPS = os.path.join(HERE, "..", "motions", "vrma")


def clip_length(path):
    """A clip's length in seconds, from its time accessor's max."""
    import json
    with open(path, "rb") as f:
        data = f.read()
    n = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(data[20:20 + n])
    return max(a.get("max", [0])[0] for a in doc["accessors"] if a.get("type") == "SCALAR")


def labelled(frames, label, every):
    out = []
    for k, frame in enumerate(frames):
        d = ImageDraw.Draw(frame)
        text = "%s %.1fs" % (label, k * every) if k else label
        d.rectangle((0, 0, 7 * len(text) + 8, 18), fill=(0, 0, 0))
        d.text((4, 3), text, fill=(255, 255, 0))
        out.append(frame)
    return out


def grid(rows):
    w, h = rows[0][0].size
    cols = max(len(r) for r in rows)
    out = Image.new("RGB", (w * cols, h * len(rows)), (30, 30, 30))
    for y, row in enumerate(rows):
        for x, frame in enumerate(row):
            out.paste(frame, (x * w, y * h))
    return out


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("avatar")
    parser.add_argument("out")
    parser.add_argument("--clips", default=DEFAULT_CLIPS)
    parser.add_argument("--only", default="")
    parser.add_argument("--frames", type=int, default=6)
    parser.add_argument("--shot", default="upper")
    parser.add_argument("--size", default="260x300")
    parser.add_argument("--gif", action="store_true")
    parser.add_argument("--name")
    parser.add_argument("--background", default="b4b4b4")
    args = parser.parse_args(argv)
    name = args.name or os.path.splitext(os.path.basename(args.avatar))[0]
    size = tuple(int(v) for v in args.size.split("x"))
    only = set(filter(None, args.only.split(",")))
    files = sorted(f for f in os.listdir(args.clips) if f.endswith(".vrma"))
    clips = [(f[:-5], os.path.join(args.clips, f)) for f in files if not only or f[:-5] in only]
    loops = [(n, p) for n, p in clips if n == "idle" or n.startswith("idle_")]
    gestures = [(n, p) for n, p in clips if (n, p) not in loops]
    os.makedirs(args.out, exist_ok=True)
    model = os.path.abspath(args.avatar)
    xvfb = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "1400x1400x24"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    env = dict(os.environ, DISPLAY=":" + xvfb.stdout.readline().strip(), LIBGL_ALWAYS_SOFTWARE="1")
    problems = []
    try:
        with tempfile.TemporaryDirectory() as work:
            frames_dir = os.path.join(work, "frames")
            rows = []
            for loop, path in loops:
                # The loop alone, as the avatar's plain idle loop.
                folder = os.path.join(work, "loop_" + loop)
                os.makedirs(folder)
                shutil.copy(path, os.path.join(folder, "idle.vrma"))
                length = clip_length(path)
                start = 1.5
                caps = [round(start + length * k / args.frames, 2) for k in range(args.frames)]
                gif_caps = [round(start + k / 12.0, 3) for k in range(int(length * 12))] if args.gif else []
                lines = [{"at": 0.1, "state": "idle"}]
                frames, events = clip_sheets.run_stage(model, None, size, lines, sorted(caps + gif_caps), frames_dir,
                                                       args.background, env,
                                                       ["--shot", args.shot, "--vrm-animation", "full", "--clips", folder])
                problems += [e for e in events if e.get("event") in ("error", "fatal", "warning")]
                by_time = dict(zip(sorted(caps + gif_caps), frames))
                rows.append(labelled([by_time[c].copy() for c in caps], loop, length / args.frames))
                if args.gif:
                    seq = [by_time[c] for c in gif_caps]
                    seq[0].save(os.path.join(args.out, "%s_%s.gif" % (name, loop)), save_all=True,
                                append_images=seq[1:], duration=83, loop=0)
            if rows:
                grid(rows).save(os.path.join(args.out, name + "_loops.png"))
            rows = []
            if gestures:
                lines, caps, gif_caps, spans = [{"at": 0.1, "state": "idle"}], [], [], []
                t = 1.5
                for gesture, path in gestures:
                    length = clip_length(path)
                    lines.append({"at": round(t, 2), "gesture": gesture})
                    mine = [round(t + length * (k + 0.5) / args.frames, 2) for k in range(args.frames)]
                    caps += mine
                    g = [round(t + k / 12.0, 3) for k in range(int((length + 0.3) * 12))] if args.gif else []
                    gif_caps += g
                    spans.append((gesture, mine, g, length))
                    t += length + 1.0
                everything = sorted(set(caps + gif_caps))
                frames, events = clip_sheets.run_stage(model, None, size, lines, everything, frames_dir, args.background, env,
                                                       ["--shot", args.shot, "--vrm-animation", "full", "--clips", args.clips])
                problems += [e for e in events if e.get("event") in ("error", "fatal", "warning", "gesture_skipped")]
                by_time = dict(zip(everything, frames))
                for gesture, mine, g, length in spans:
                    rows.append(labelled([by_time[c].copy() for c in mine], gesture, length / args.frames))
                    if args.gif:
                        seq = [by_time[c] for c in g]
                        seq[0].save(os.path.join(args.out, "%s_%s.gif" % (name, gesture)), save_all=True,
                                    append_images=seq[1:], duration=83, loop=0)
                grid(rows).save(os.path.join(args.out, name + "_gestures.png"))
    finally:
        xvfb.terminate()
    for p in problems:
        print("stage:", p)


if __name__ == "__main__":
    main(sys.argv[1:])
