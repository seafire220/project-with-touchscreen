"""Full-body animation for 3D (VRM) avatars, on the device (docs/30-vrm.md).

A VRM character moves in one of two styles, chosen for each character on the settings page:

  full   animation clips (VRM Animation, .vrma) play on the whole skeleton: an idle loop for what the
         character is doing and its mood, and gestures and idle actions; the stage's own motion (where
         it looks, nods, its face and mouth) goes on top. The default.
  light  the controls the 2D characters use, turned into bone turns. No clips are read, so it uses a
         little less memory and processor time.

In the full style the stage plays its built-in clips (stage/motions/vrma) and any the owner adds for the
character. Those are kept in characters/<id>/animations/<role>.vrma, where the role says what each is
for: an idle loop (idle, idle_<mood>, idle_listen, idle_think, idle_talk, idle_sleep), a built-in
gesture or idle action it replaces (wave, stretch ...), or a new gesture of the character's own, asked
for by name, with the words that say what it means. They stay on the device: like its other choices
for a character, they are never written into its package.

The core writes the settings of the character on the screen to current-stage.json, which the stage
reads when it starts (`--settings`): the style, the clip folders, how much the drawing may cost
("lite" leaves out outlines and keeps textures small) and how much of the avatar to show.
"""
import json
import os
import re
import struct
import time

from . import package, vrm
from .store import write_atomic

STYLES = ("full", "light")
QUALITIES = ("auto", "lite")
SHOTS = ("upper", "bust", "full")
DEFAULTS = {"animation": "full", "quality": "auto", "shot": "upper"}
MOODS = ("happy", "sad", "angry", "surprised", "embarrassed", "thinking")
LOOP_LABELS = dict(
    [("idle", "Idle (any mood)")]
    + [("idle_" + m, "Idle when %s" % m) for m in MOODS]
    + [("idle_listen", "Idle while listening"), ("idle_think", "Idle while thinking"),
       ("idle_talk", "Idle while talking"), ("idle_sleep", "Dozing")])
LOOPS = tuple(LOOP_LABELS)
NAME = re.compile(r"[a-z_]{1,40}")
MAX_BYTES = 16 << 20
MAX_SECONDS = 120.0
MAX_CLIPS = 40
FOLDER = "animations"
INDEX = "animations.json"
# In the settings file's clip folders: the stage's own built-in clips.
BUILTIN = "builtin"


class AnimationError(ValueError):
    pass


def builtin_folder():
    """Where the stage's built-in clips are (installed on the device, or beside the source)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.environ.get("COMPANION_VRMA_DIR", ""), "/opt/companion/share/vrma",
                 os.path.join(here, "..", "..", "stage", "motions", "vrma")):
        if path and os.path.isdir(path):
            return os.path.normpath(path)
    return None


def builtin_names():
    folder = builtin_folder()
    if not folder:
        return []
    return sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".vrma"))


def _accessor_floats(doc, binary, index):
    acc = (doc.get("accessors") or [])[index]
    if acc.get("componentType") != 5126 or acc.get("type") != "SCALAR" or "bufferView" not in acc:
        raise AnimationError("its animation's times are not stored as plain numbers")
    view = (doc.get("bufferViews") or [])[acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    count = int(acc.get("count", 0))
    stride = view.get("byteStride") or 4
    if count <= 0 or count > 4_000_000 or start + (count - 1) * stride + 4 > len(binary):
        raise AnimationError("its animation's data is damaged")
    return [struct.unpack_from("<f", binary, start + k * stride)[0] for k in range(count)]


def check(data):
    """A VRM Animation file, checked. Returns its facts: {"seconds", "bones", "expressions"}.
    Raises AnimationError saying what is wrong."""
    if len(data) > MAX_BYTES:
        raise AnimationError("the file is too large (%d MB; at most %d MB)" % (len(data) >> 20, MAX_BYTES >> 20))
    try:
        doc, binary = vrm.read_glb(data)
    except vrm.VrmError as error:
        raise AnimationError(str(error))
    ext = (doc.get("extensions") or {}).get("VRMC_vrm_animation")
    if not isinstance(ext, dict):
        raise AnimationError("this is not a VRM Animation file (.vrma); VRoid Hub, VRM Posing Desktop and "
                             "Blender with the VRM add-on can save one")
    bones = (ext.get("humanoid") or {}).get("humanBones") or {}
    if not isinstance(bones, dict) or "hips" not in bones:
        raise AnimationError("its skeleton has no hips bone")
    for kind in ("buffers", "images"):
        if any(isinstance(b, dict) and "uri" in b for b in doc.get(kind) or []):
            raise AnimationError("its data is in a separate file; save it as one .vrma file")
    animations = doc.get("animations") or []
    if not animations or not isinstance(animations[0], dict):
        raise AnimationError("it has no animation")
    seconds = 0.0
    try:
        for sampler in animations[0].get("samplers") or []:
            acc = (doc.get("accessors") or [])[sampler["input"]]
            top = acc.get("max")
            if isinstance(top, list) and top and isinstance(top[0], (int, float)):
                seconds = max(seconds, float(top[0]))
            else:
                seconds = max(seconds, max(_accessor_floats(doc, binary, sampler["input"])))
    except (KeyError, IndexError, TypeError, struct.error):
        raise AnimationError("its animation's data is damaged")
    if not 0.0 < seconds <= MAX_SECONDS:
        raise AnimationError("it must last between a moment and %d seconds (it lasts %.0f)" % (MAX_SECONDS, seconds))
    if package.contains_secret(json.dumps(doc)):
        raise AnimationError("it appears to contain an API key; it was not used")
    expressions = []
    for group in ("preset", "custom"):
        expressions += sorted((ext.get("expressions") or {}).get(group) or {})
    return {"seconds": round(seconds, 2), "bones": sorted(b for b in bones if isinstance(b, str))[:60],
            "expressions": expressions[:60]}


def clean_words(words, name):
    words = " ".join(str(words or "").split())
    if len(words) > 80 or "[" in words or "]" in words:
        raise AnimationError("what it means is a few plain words, such as \"do a little dance\"")
    return words or name.replace("_", " ")


class Animations:
    """The animation style, and the clips added, for each character."""

    def __init__(self, characters):
        self.characters = characters

    def settings(self, cid):
        saved = self.characters.device_settings(cid).get("vrm") or {}
        out = dict(DEFAULTS)
        # An avatar that is heavy for this device starts with its drawing kept light.
        try:
            if (self.characters.manifest(cid).get("vrm_cost") or {}).get("lite"):
                out["quality"] = "lite"
        except (OSError, ValueError):
            pass
        for key, allowed in (("animation", STYLES), ("quality", QUALITIES), ("shot", SHOTS)):
            if saved.get(key) in allowed:
                out[key] = saved[key]
        return out

    def set_settings(self, cid, changes):
        current = self.settings(cid)
        for key, allowed in (("animation", STYLES), ("quality", QUALITIES), ("shot", SHOTS)):
            if key in changes:
                if changes[key] not in allowed:
                    raise AnimationError("%s is one of: %s" % (key, ", ".join(allowed)))
                current[key] = changes[key]
        self.characters.set_device_settings(cid, {"vrm": current})
        return current

    def folder(self, cid):
        return os.path.join(self.characters._dir(cid), FOLDER)

    def index(self, cid):
        try:
            with open(os.path.join(self.folder(cid), INDEX), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in data.items() if NAME.fullmatch(k) and isinstance(v, dict)
                and os.path.isfile(os.path.join(self.folder(cid), k + ".vrma"))}

    def path(self, cid, role):
        if role not in self.index(cid):
            raise KeyError(role)
        return os.path.join(self.folder(cid), role + ".vrma")

    def add(self, cid, role, data, title="", words=None, gestures=()):
        """Keep a clip for a character in the given role. `gestures` are the names of the gestures and
        idle actions the stage has (a clip of one of those names replaces it). Returns its entry."""
        if not isinstance(role, str) or not NAME.fullmatch(role) or role.startswith("_"):
            raise AnimationError("a name is lower-case letters and _, such as little_dance")
        if role.startswith("idle") and role not in LOOPS:
            raise AnimationError("names starting with idle are for the idle loops: " + ", ".join(LOOPS))
        facts = check(data)
        index = self.index(cid)
        if role not in index and len(index) >= MAX_CLIPS:
            raise AnimationError("a character can have at most %d animations of its own" % MAX_CLIPS)
        if role in LOOPS:
            kind = "loop"
        elif role in gestures or role in builtin_names():
            kind = "replaces"
        else:
            kind = "gesture"
        entry = {"kind": kind, "title": " ".join(str(title or "").split())[:80], "seconds": facts["seconds"],
                 "added": int(time.time())}
        if kind == "gesture":
            entry["words"] = clean_words(words, role)
        os.makedirs(self.folder(cid), exist_ok=True)
        write_atomic(os.path.join(self.folder(cid), role + ".vrma"), data)
        index[role] = entry
        write_atomic(os.path.join(self.folder(cid), INDEX), json.dumps(index, indent=1))
        return entry

    def remove(self, cid, role):
        index = self.index(cid)
        if index.pop(role, None) is None:
            return False
        os.remove(os.path.join(self.folder(cid), role + ".vrma"))
        write_atomic(os.path.join(self.folder(cid), INDEX), json.dumps(index, indent=1))
        return True

    def words(self, cid):
        """The new gestures a character's own clips add, with what each means (for the language model)."""
        if self.characters.drawing(cid) != "vrm" or self.settings(cid)["animation"] != "full":
            return {}
        return {role: e.get("words") or role.replace("_", " ") for role, e in self.index(cid).items()
                if e.get("kind") == "gesture"}

    def stage_settings(self, cid):
        """The stage's settings for this character on the screen."""
        drawing = self.characters.drawing(cid) if cid else ""
        if drawing == "live2d":
            from .characters import OWN_MOTIONS
            return {"model_motions": OWN_MOTIONS[self.characters.own_motion_setting(cid)]}
        if drawing != "vrm":
            return {}
        s = self.settings(cid)
        return {"vrm_animation": s["animation"], "quality": s["quality"], "shot": s["shot"],
                "clip_folders": [BUILTIN, self.folder(cid)]}

    def describe(self, cid, gestures=()):
        """For the settings page: the style, the clips added, and what a clip can be added as."""
        index = self.index(cid)
        builtin = builtin_names()
        added = [dict(e, role=role, label=LOOP_LABELS.get(role) or ("New gesture: " if e.get("kind") == "gesture"
                                                                    else "Instead of: ") + role.replace("_", " "))
                 for role, e in sorted(index.items())]
        roles = [{"role": r, "label": label, "kind": "loop", "builtin": r in builtin} for r, label in LOOP_LABELS.items()]
        for name in sorted(set(gestures) | {n for n in builtin if n not in LOOPS}):
            roles.append({"role": name, "label": "Instead of: " + name.replace("_", " "), "kind": "replaces",
                          "builtin": name in builtin})
        device = self.characters.device_settings(cid)
        try:
            cost = self.characters.manifest(cid).get("vrm_cost") or {}
        except (OSError, ValueError):
            cost = {}
        return {"settings": self.settings(cid), "added": added, "roles": roles, "builtin": builtin,
                "styles": list(STYLES), "qualities": list(QUALITIES), "shots": list(SHOTS), "cost": cost,
                "failsafe": device.get("vrm_failsafe"), "quality_seen": device.get("vrm_quality_seen")}
