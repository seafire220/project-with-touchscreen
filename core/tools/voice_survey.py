#!/usr/bin/env python3
"""Survey an on-device voice's speakers and write the list the settings page offers
(core/companion/voices.json).

Each speaker reads two harder sentences, which the device's own speech recognition must hear without a
mistake (a second try is allowed: the voice varies a little each time); those that pass are kept, and so
are speakers of the accents asked for (--prefer, such as Australian) that slip by one word at most; labelled by accent and sex when the voice's dataset says (VCTK's
speaker-info.txt), with their pitch. The clearest over six everyday sentences is the default.

    python3 core/tools/voice_survey.py --voice MODEL_DIR --stt STT_DIR --out core/companion/voices.json
        [--speaker-info speaker-info.txt] [--credit TEXT] [--about TEXT]

Needs sherpa-onnx and espeak-ng, as the device does.
"""
import argparse
import asyncio
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from companion.providers import LocalSTT, LocalTTS  # noqa: E402

HARD = ["Would you like a cup of tea before the weather turns cold?",
        "Thirty-three people visited the museum on Thursday afternoon."]
EVERYDAY = ["Good morning! Did you sleep well last night?",
            "I think the weather will be lovely for your walk this afternoon.",
            "Tell me more about the book you started reading yesterday.",
            "That sounds wonderful, I'm really happy for you.",
            "Remember to drink some water and take a short break.",
            "Would you like to hear a story before you go to bed?"]
ACCENTS = {"NorthernIrish": "Northern Irish", "NewZealand": "New Zealand", "SouthAfrican": "South African",
           "Unknown": ""}


def words(text):
    return re.sub(r"[^a-z0-9' ]", " ", text.lower().replace("-", " ")).split()


def word_errors(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)]


def tidy_region(accent, region):
    """VCTK's region notes, readable: "English Sydney" for an Australian speaker says where, not the accent."""
    words = region.split()
    if accent != "English" and words and words[0] == "English":
        words = words[1:]
    return " ".join(words)


def pitch(samples, rate):
    """Median pitch of the voiced parts, in Hz (autocorrelation over 40 ms frames)."""
    x = samples.astype(np.float32)
    frame, hop = int(0.04 * rate), int(0.01 * rate)
    lo, hi = int(rate / 400), int(rate / 60)
    found = []
    for start in range(0, len(x) - frame, hop):
        f = x[start:start + frame]
        f = f - f.mean()
        energy = float(np.dot(f, f))
        if energy < 1e-3 * frame * (np.abs(x).max() ** 2 + 1e-9):
            continue
        ac = np.correlate(f, f, mode="full")[frame - 1:]
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0.4 * ac[0]:
            found.append(rate / lag)
    return float(np.median(found)) if found else 0.0


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--voice", required=True)
    p.add_argument("--stt", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--speaker-info")
    p.add_argument("--credit", default="")
    p.add_argument("--about", default="")
    p.add_argument("--prefer", default="", help="accents kept with one slip, comma-separated (e.g. Australian)")
    a = p.parse_args(argv)
    tts, stt = LocalTTS(a.voice, threads=2), LocalSTT(a.stt, threads=2)
    model = [f for f in os.listdir(a.voice) if f.endswith(".onnx")][0][:-len(".onnx")]
    with open(os.path.join(a.voice, model + ".onnx.json"), encoding="utf-8") as f:
        names = {v: k for k, v in (json.load(f).get("speaker_id_map") or {}).items()}
    info = {}
    if a.speaker_info:
        for line in open(a.speaker_info, encoding="utf-8", errors="replace").read().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4:
                info[parts[0]] = {"sex": parts[2], "accent": ACCENTS.get(parts[3], parts[3]),
                                  "region": " ".join(parts[4:])}

    def hear(sid, sentences):
        tts.sid = sid
        errors, audio = 0, []
        for s in sentences:
            x = np.frombuffer(tts._speak(s), dtype=np.int16)
            audio.append(x)
            y = np.interp(np.arange(0, len(x), tts.rate / 16000.0), np.arange(len(x)), x.astype(np.float32))
            errors += word_errors(s, asyncio.run(stt.transcribe(y.astype(np.int16).tobytes(), 16000)))
        return errors, np.concatenate(audio)

    prefer = {a.strip() for a in a.prefer.split(",") if a.strip()}
    passed = []
    for sid in range(max(tts.speakers, 1)):
        errors, audio = hear(sid, HARD)
        if errors:
            errors, audio = hear(sid, HARD)
        accent = info.get(names.get(sid, ""), {}).get("accent", "")
        if errors > (1 if accent in prefer else 0):
            continue
        everyday, more = hear(sid, EVERYDAY)
        who = info.get(names.get(sid, ""), {})
        passed.append({"id": sid, "speaker": names.get(sid, str(sid)), "pitch_hz": round(pitch(np.concatenate([audio, more]), tts.rate), 1),
                       "errors": everyday, **who})
        print("speaker %3d %-6s passes: %d everyday errors, %.0f Hz %s" % (
            sid, names.get(sid, ""), everyday, passed[-1]["pitch_hz"], who.get("accent", "")), flush=True)
    if not passed:
        raise SystemExit("no speaker passed")
    median = float(np.median([v["pitch_hz"] for v in passed]))
    default = min(passed, key=lambda v: (v["errors"], abs(v["pitch_hz"] - median)))
    voices = []
    for v in sorted(passed, key=lambda v: (v.get("accent", ""), v.get("sex", ""), v["pitch_hz"])):
        sex = {"F": "woman", "M": "man"}.get(v.get("sex", ""), "voice")
        if v.get("accent"):
            label = "%s %s" % (v["accent"], sex)
        elif v.get("sex"):
            label = "%s %d" % (sex.capitalize(), v["id"])
        else:
            label = "Voice %d" % v["id"]
        region = tidy_region(v.get("accent", ""), v.get("region", ""))
        if region:
            label += " (%s)" % region
        voices.append({"id": v["id"], "label": label, "pitch_hz": v["pitch_hz"]})
    out = {"about": a.about or ("Clear voices from the on-device voice (%s), chosen by a survey: each speaker read two harder "
                                "sentences, which the device's own speech recognition had to hear without a mistake. "
                                "%d of %d passed." % (model, len(passed), max(tts.speakers, 1))),
           "model": model, "credit": a.credit, "default": default["id"], "voices": voices}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print("%d of %d passed; default %d (%s); written to %s" % (len(passed), tts.speakers, default["id"],
                                                               default.get("accent", ""), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
