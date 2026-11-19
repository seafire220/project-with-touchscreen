"""Gestures and idle actions changed or added on the device, with the settings page's editor.

Each is kept as the stage's library writes it (`stage/motions/library.json`), checked here the way
the stage checks its own library, and sent to the stage when it starts: a changed one replaces the
built-in one; an added gesture can be asked for by the language model, with the words that say what it
means. They stay on the device, apart from any character.
"""
import json
import os
import re

from .store import write_atomic

# The stage's controls (stage/src/motion.rs KEYS); a test keeps the two in step.
CONTROLS = ("head_yaw", "head_pitch", "head_roll", "body_yaw", "body_pitch", "body_roll", "gaze_x", "gaze_y",
            "brows", "brow_form", "smile", "eye_smile", "cheek", "arm_left", "arm_right", "arm_left_b",
            "arm_right_b", "shoulders", "mouth_open", "blink")
CHANNELS = ("head", "torso", "eyes", "brows", "expression", "arm_left", "arm_right", "mouth", "eyelids")
KINDS = ("gesture", "idle", "reaction")
NAME = re.compile(r"[a-z_]{1,40}")
TRY = "_try"                     # the name a clip is tried under, never kept
MAX_SECONDS = 30.0
MAX_KEYS = 200


def _tracks(tracks, where):
    if not isinstance(tracks, dict) or not tracks:
        raise ValueError("%s: it needs at least one track" % where)
    out = {}
    for control, keys in tracks.items():
        if control not in CONTROLS:
            raise ValueError("%s: there is no control called %s" % (where, control))
        if not isinstance(keys, list) or not 2 <= len(keys) <= MAX_KEYS:
            raise ValueError("%s: %s needs two or more keys" % (where, control))
        points = []
        for key in keys:
            if not (isinstance(key, (list, tuple)) and len(key) == 2
                    and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in key)):
                raise ValueError("%s: each key of %s is [seconds, value]" % (where, control))
            points.append([round(float(key[0]), 3), round(float(key[1]), 3)])
        if any(b[0] <= a[0] for a, b in zip(points, points[1:])) or points[0][0] < 0 or points[-1][0] > MAX_SECONDS:
            raise ValueError("%s: the keys of %s must go forward in time, within %d seconds" % (where, control, MAX_SECONDS))
        if points[0][1] != 0 or points[-1][1] != 0:
            raise ValueError("%s: %s must start and end at 0" % (where, control))
        if any(abs(p[1]) > 1.5 for p in points):
            raise ValueError("%s: the values of %s are between -1.5 and 1.5" % (where, control))
        out[control] = points
    return out


def clean(name, entry):
    """A clip from the editor, checked; raises ValueError with what is wrong."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("a name is lower-case letters and _, such as little_dance")
    if not isinstance(entry, dict):
        raise ValueError("send the gesture as the library writes it")
    kind = entry.get("kind", "gesture")
    if kind not in KINDS:
        raise ValueError("its kind is gesture, idle or reaction")
    needs = entry.get("needs", [])
    if not isinstance(needs, list) or not all(
            isinstance(n, str) and n and all(part in CONTROLS for part in n.split("|")) for n in needs):
        raise ValueError("what it needs is a list of controls, such as head_pitch or arm_left|arm_right")
    out = {"kind": kind, "needs": needs, "tracks": _tracks(entry.get("tracks"), name)}
    takes = entry.get("takes")
    if takes:
        if not isinstance(takes, list) or len(takes) > 8:
            raise ValueError("%s: takes are a list of up to 8 {\"tracks\": ...}" % name)
        out["takes"] = [{"tracks": _tracks((t or {}).get("tracks") if isinstance(t, dict) else None, name)}
                        for t in takes]
    for flag in ("big", "mirror", "exact"):
        if entry.get(flag):
            out[flag] = True
    if entry.get("instead"):
        if not isinstance(entry["instead"], str) or not NAME.fullmatch(entry["instead"]):
            raise ValueError("what plays instead is the name of another gesture")
        out["instead"] = entry["instead"]
    if entry.get("holds"):
        if not isinstance(entry["holds"], list) or not all(c in CHANNELS for c in entry["holds"]):
            raise ValueError("what it holds is a list of: " + ", ".join(CHANNELS))
        out["holds"] = list(entry["holds"])
    if entry.get("stroke") is not None:
        if not isinstance(entry["stroke"], (int, float)) or not 0 <= entry["stroke"] <= MAX_SECONDS:
            raise ValueError("when it lands is a number of seconds")
        out["stroke"] = float(entry["stroke"])
    words = entry.get("words")
    if words:
        if not isinstance(words, str) or len(words) > 80 or "[" in words or "]" in words:
            raise ValueError("what it means is a few plain words, such as \"do a little dance\"")
        out["words"] = " ".join(words.split())
    return out


class CustomMotions:
    """The clips changed or added on this device, in one file."""

    def __init__(self, path):
        self.path = path

    def all(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if isinstance(v, dict) and NAME.fullmatch(k)}
        except (OSError, ValueError):
            return {}

    def set(self, name, entry):
        data = self.all()
        data[name] = clean(name, entry)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        write_atomic(self.path, json.dumps(data, indent=1))
        return data[name]

    def remove(self, name):
        data = self.all()
        if data.pop(name, None) is None:
            return False
        write_atomic(self.path, json.dumps(data, indent=1))
        return True

    def words(self):
        """The added gestures the language model may ask for, with what each means."""
        return {name: entry.get("words") or name.replace("_", " ")
                for name, entry in self.all().items() if entry.get("kind", "gesture") == "gesture"}
