"""Character packages: one `.char` zip file per character.

Layout (see docs/06-architecture.md):

    manifest.json     format version, id, name, kind, author, licence note, capabilities
    persona.md        system prompt, greeting, speaking style
    voice.json        preferred voice per provider type; never credentials
    voice/sample.wav  optional sample for cloning
    behaviour.json    emotion names, idle behaviour, end-of-speech pause
    visual/           depends on kind:
      puppet.inp + puppet.map.json   Inochi2D puppet and parameter mapping
      live2d/model.model3.json + model.moc3 + textures/, motions/ ...
                                     the same puppet in the Live2D format (optional;
                                     a puppet character needs one of the two)
      clips.json + clips/*           loops per state and emotion
      sprite.json + frames/*         still frames per emotion and mouth level
    ui/               optional background and colours
    preview.png|webp

A package never holds API keys or memories. Opening one checks everything
before anything is stored: names, sizes, types, JSON, and that nothing tries
to escape the package or looks like a secret. Nothing in a package is run.
"""
import io
import json
import posixpath
import re
import zipfile

from . import vrm as vrm_format

FORMAT = 1
KINDS = ("puppet", "clips", "sprite")

MAX_TOTAL = 200 * 1024 * 1024
MAX_FILES = 2000
MAX_RATIO = 250            # uncompressed / compressed, per file: guards against zip bombs
MAX_TEXT = 256 * 1024
MAX_PREVIEW_SIDE = 2048

# Allowed names, and the largest each may be.
ALLOWED = [
    (re.compile(r"manifest\.json"), MAX_TEXT),
    (re.compile(r"persona\.md"), MAX_TEXT),
    (re.compile(r"voice\.json"), MAX_TEXT),
    (re.compile(r"voice/sample\.wav"), 20 * 1024 * 1024),
    (re.compile(r"behaviour\.json"), MAX_TEXT),
    (re.compile(r"visual/puppet\.(inp|inx)"), 96 * 1024 * 1024),
    (re.compile(r"visual/puppet\.map\.json"), MAX_TEXT),
    (re.compile(r"visual/(clips|sprite)\.json"), MAX_TEXT),
    (re.compile(r"visual/live2d/model\.moc3"), 64 * 1024 * 1024),
    (re.compile(r"visual/live2d/model\.(model3|physics3|cdi3|pose3)\.json"), 4 * 1024 * 1024),
    (re.compile(r"visual/live2d/motions/[A-Za-z0-9_.\-]{1,96}\.motion3\.json"), 4 * 1024 * 1024),
    (re.compile(r"visual/live2d/expressions/[A-Za-z0-9_.\-]{1,96}\.exp3\.json"), MAX_TEXT),
    (re.compile(r"visual/live2d/textures/[A-Za-z0-9_.\-]{1,96}\.png"), 32 * 1024 * 1024),
    (re.compile(r"visual/emotions\.json"), MAX_TEXT),
    (re.compile(r"visual/vrm/model\.vrm"), vrm_format.MAX_VRM_BYTES),
    (re.compile(r"visual/clips/[A-Za-z0-9_\-]{1,64}\.(webm|mp4|webp|png)"), 32 * 1024 * 1024),
    (re.compile(r"visual/frames/[A-Za-z0-9_\-]{1,64}\.(webp|png)"), 4 * 1024 * 1024),
    (re.compile(r"ui/background\.(webp|png|jpg)"), 8 * 1024 * 1024),
    (re.compile(r"ui/colours\.json"), MAX_TEXT),
    (re.compile(r"preview\.(png|webp)"), 4 * 1024 * 1024),
    (re.compile(r"studio/report\.json"), MAX_TEXT),
]

# Things that look like credentials. A package containing one is refused.
SECRET_PATTERNS = [
    re.compile(r"sk-(ant-|proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bsk_car_[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bsk_[0-9a-f]{32,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxai-[A-Za-z0-9]{20,}"),
    re.compile(r"\b(sk|pk)_(live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)\"(api[_-]?key|secret|token|password|authorization)\"\s*:\s*\"[^\"]{8,}\""),
    re.compile(r"(?i)\b(api[_-]?key|xi-api-key)\s*[:=]\s*[A-Za-z0-9_\-]{16,}"),
]

ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9\-]{0,47}")
TEXT_SUFFIXES = (".json", ".md")
PUPPET_MAGIC = b"TRNSRTS\0"
MOC3_MAGIC = b"MOC3"
LIVE2D_MODEL = "visual/live2d/model.model3.json"
VRM_MODEL = "visual/vrm/model.vrm"


class PackageError(ValueError):
    """The package is unusable; the message says why in plain words."""


def _allowed_size(name):
    for pattern, limit in ALLOWED:
        if pattern.fullmatch(name):
            return limit
    return None


def _check_name(info):
    name = info.filename
    if info.is_dir():
        return None
    if name.startswith("/") or "\\" in name or ".." in name.split("/") or "\x00" in name:
        raise PackageError("the package contains a file path that points outside it: %r" % name)
    mode = (info.external_attr >> 16) & 0o170000
    if mode == 0o120000:
        raise PackageError("the package contains a link (%s); links are not allowed" % name)
    limit = _allowed_size(name)
    if limit is None:
        raise PackageError("the package contains a file this device does not use: %s" % name)
    return limit


def contains_secret(text):
    return any(p.search(text) for p in SECRET_PATTERNS)


def _check_manifest(manifest):
    if not isinstance(manifest, dict):
        raise PackageError("manifest.json must be a JSON object")
    if manifest.get("format") != FORMAT:
        raise PackageError("this package is format %r; this device reads format %d" % (manifest.get("format"), FORMAT))
    cid = manifest.get("id")
    if not isinstance(cid, str) or not ID_PATTERN.fullmatch(cid):
        raise PackageError("the character id must be 1-48 lowercase letters, digits or dashes")
    name = manifest.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        raise PackageError("the character needs a name of 1 to 60 characters")
    if manifest.get("kind") not in KINDS:
        raise PackageError("the character kind must be one of: %s" % ", ".join(KINDS))
    for field, limit in (("author", 100), ("licence", 400), ("created", 40)):
        value = manifest.get(field, "")
        if not isinstance(value, str) or len(value) > limit:
            raise PackageError("%s must be text of at most %d characters" % (field, limit))
    caps = manifest.get("capabilities", {})
    if not isinstance(caps, dict) or not all(isinstance(k, str) and isinstance(v, bool) for k, v in caps.items()):
        raise PackageError("capabilities must map names to true or false")


def _check_image(name, data):
    try:
        from PIL import Image
    except ImportError:          # pragma: no cover - Pillow is installed on the device
        return
    try:
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
            im.verify()
    except Exception:
        raise PackageError("%s is not a readable picture" % name)
    if name.startswith("preview") and max(width, height) > MAX_PREVIEW_SIDE:
        raise PackageError("%s is larger than %d pixels" % (name, MAX_PREVIEW_SIDE))


def _check_puppet(name, data):
    if not data.startswith(PUPPET_MAGIC) or len(data) < 12:
        raise PackageError("%s is not an Inochi2D puppet" % name)
    length = int.from_bytes(data[8:12], "big")
    if length <= 0 or 12 + length > len(data):
        raise PackageError("%s is damaged: its header is cut short" % name)
    try:
        header = json.loads(data[12:12 + length])
    except ValueError:
        raise PackageError("%s is damaged: its header is not readable" % name)
    if contains_secret(data[12:12 + length].decode("utf-8", "replace")):
        raise PackageError("%s appears to contain an API key; it was refused" % name)
    if not isinstance(header, dict) or "nodes" not in header:
        raise PackageError("%s has no puppet in it" % name)


def _check_moc3(name, data):
    if not data.startswith(MOC3_MAGIC) or len(data) < 64 or not 1 <= data[4] <= 6:
        raise PackageError("%s is not a valid .moc3 model file" % name)
    if contains_secret(data.decode("latin-1")):
        raise PackageError("%s appears to contain an API key; it was refused" % name)


def _check_vrm(name, data):
    try:
        doc, _, _ = vrm_format.check(data)
    except vrm_format.VrmError as error:
        raise PackageError("%s: %s" % (name, error))
    if contains_secret(json.dumps(doc, ensure_ascii=False)):
        raise PackageError("%s appears to contain an API key; it was refused" % name)


def _check_live2d(files):
    """The Live2D-format model's index must name only files that are in the package, beside it."""
    if not any(n.startswith("visual/live2d/") for n in files):
        return
    if LIVE2D_MODEL not in files or "visual/live2d/model.moc3" not in files:
        raise PackageError("a .model3.json model needs visual/live2d/model.model3.json and model.moc3")
    model = json.loads(files[LIVE2D_MODEL])
    refs = model.get("FileReferences") if isinstance(model, dict) else None
    if not isinstance(refs, dict) or refs.get("Moc") != "model.moc3":
        raise PackageError("model.model3.json must name model.moc3 as its model")
    try:
        named = [refs.get("Moc"), refs.get("Physics"), refs.get("Pose"), refs.get("DisplayInfo")]
        named += list(refs.get("Textures") or [])
        for group in (refs.get("Motions") or {}).values():
            named += [m.get("File") for m in group]
        named += [e.get("File") for e in (refs.get("Expressions") or [])]
    except (AttributeError, TypeError):
        raise PackageError("model.model3.json is not laid out as a .model3.json model index")
    for item in named:
        if item is None:
            continue
        if not isinstance(item, str) or item.startswith("/") or ".." in item.split("/") or "\\" in item:
            raise PackageError("model.model3.json names a file outside the model: %r" % (item,))
        if "visual/live2d/" + item not in files:
            raise PackageError("model.model3.json names %s, which is not in the package" % item)


class Package:
    """A checked package, held in memory."""

    def __init__(self, files):
        self.files = files
        self.manifest = json.loads(files["manifest.json"])
        self.persona = files["persona.md"].decode("utf-8")

    @property
    def id(self):
        return self.manifest["id"]

    @property
    def kind(self):
        return self.manifest["kind"]

    def json(self, name, default=None):
        return json.loads(self.files[name]) if name in self.files else default


def open_package(source):
    """Read and check a package from a path or a file object. Raises PackageError."""
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError):
        raise PackageError("this is not a character package (not a zip file)")
    files = {}
    total = 0
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES:
            raise PackageError("the package holds too many files")
        for info in infos:
            limit = _check_name(info)
            if limit is None:
                continue
            if info.filename in files:
                raise PackageError("the package contains %s twice" % info.filename)
            if info.file_size > limit:
                raise PackageError("%s is too large" % info.filename)
            if info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_RATIO:
                raise PackageError("%s is suspiciously compressed; it was refused" % info.filename)
            with archive.open(info) as f:
                data = f.read(limit + 1)
            if len(data) > limit:
                raise PackageError("%s is too large" % info.filename)
            total += len(data)
            if total > MAX_TOTAL:
                raise PackageError("the package is too large")
            files[info.filename] = data
    for required in ("manifest.json", "persona.md"):
        if required not in files:
            raise PackageError("the package has no %s" % required)
    for name, data in files.items():
        if name.endswith(TEXT_SUFFIXES):
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                raise PackageError("%s is not UTF-8 text" % name)
            if contains_secret(text):
                raise PackageError("%s appears to contain an API key or password; it was refused" % name)
            if name.endswith(".json"):
                try:
                    json.loads(text)
                except ValueError as error:
                    raise PackageError("%s is not valid JSON (%s)" % (name, error))
        elif name.endswith((".png", ".webp", ".jpg")):
            _check_image(name, data)
        elif name.endswith((".inp", ".inx")):
            _check_puppet(name, data)
        elif name.endswith(".moc3"):
            _check_moc3(name, data)
        elif name.endswith(".vrm"):
            _check_vrm(name, data)
    manifest = json.loads(files["manifest.json"])
    _check_manifest(manifest)
    _check_live2d(files)
    kind = manifest["kind"]
    if (kind == "puppet" and not any(n.startswith("visual/puppet.in") for n in files) and LIVE2D_MODEL not in files
            and VRM_MODEL not in files):
        raise PackageError("a puppet character needs visual/puppet.inp (Inochi2D), a .model3.json model or a VRM avatar")
    if kind == "clips" and "visual/clips.json" not in files:
        raise PackageError("a clips character needs visual/clips.json")
    if kind == "sprite" and "visual/sprite.json" not in files:
        raise PackageError("a sprite character needs visual/sprite.json")
    return Package(files)


def build(files, manifest):
    """Make package bytes from a dict of name -> bytes and a manifest dict. The result is checked."""
    manifest = dict(manifest)
    manifest.setdefault("format", FORMAT)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=1, ensure_ascii=False))
        for name in sorted(files):
            if name == "manifest.json":
                continue
            data = files[name]
            if isinstance(data, str):
                data = data.encode("utf-8")
            stored = name.endswith((".png", ".webp", ".jpg", ".webm", ".mp4", ".inp", ".inx", ".moc3"))
            archive.writestr(name, data, zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
    data = out.getvalue()
    open_package(io.BytesIO(data))
    return data


def slug(name):
    """A package id made from a character's name."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48]
    return s or "character"


# --------------------------------------------------------------------------------------------------
# Importing a Live2D-format model folder (as made for VTube Studio and similar programs)
# --------------------------------------------------------------------------------------------------

# Words in a model's expression names that suggest which of our emotions each one shows.
# Names such as "F01" say nothing; those are left for the buyer to choose on the settings page.
EMOTION_WORDS = {
    "happy": ("happy", "smile", "joy", "glad", "laugh", "grin", "fun", "cheer"),
    "sad": ("sad", "cry", "tear", "sorrow", "upset", "gloom"),
    "angry": ("angry", "anger", "mad", "rage", "annoy", "pout", "irritat"),
    "surprised": ("surprise", "shock", "wow", "astonish", "startle"),
    "embarrassed": ("blush", "shy", "embarrass", "fluster"),
    "thinking": ("think", "ponder", "wonder", "curious", "hmm"),
}


def guess_emotions(names):
    """A first mapping from our emotions to a model's own expressions, by their names."""
    mapping, used = {}, set()
    for emotion, words in EMOTION_WORDS.items():
        for name in names:
            if name not in used and any(w in name.lower() for w in words):
                mapping[emotion] = name
                used.add(name)
                break
    return mapping


IMPORT_LICENCE = ("Imported 2D rigged model (.model3.json). The person who imported it is responsible for having the "
                  "right to use it on this device.")

IMPORT_PERSONA = """# {name}

You are {name}, a character who lives on a small screen on the user's desk and talks with them
by voice.

Describe {name} here: personality, background, likes and dislikes, and how they treat the user.
Keep it in the second person ("You are...").

## How you speak

Your replies are spoken aloud, so keep them short and natural: one to three sentences unless
asked for more. No lists, headings or emoji.
"""


def _unsafe_path(name):
    return (not isinstance(name, str) or not name or name.startswith("/") or "\\" in name or "\x00" in name
            or ".." in name.split("/"))


def is_live2d_zip(data):
    """A zip holding a Live2D-format model rather than a character package."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return False
    return "manifest.json" not in names and any(_is_model_index(n) for n in names)


def _is_model_index(name):
    base = name.rsplit("/", 1)[-1]
    return base.lower().endswith(".model3.json") and not base.startswith("._") and not name.startswith("__MACOSX/")


def _stem(text, used):
    stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", posixpath.basename(str(text)).split(".")[0])[:60].strip("_") or "item"
    candidate, n = stem, 2
    while candidate.lower() in used:
        candidate, n = "%s_%d" % (stem, n), n + 1
    used.add(candidate.lower())
    return candidate


def from_live2d_zip(source, name=None):
    """Make a character package from a zip of a Live2D-format model's folder: its .model3.json
    and the files that names (model, textures, physics, pose, display names, expressions,
    motions). Only those files are read; sounds and user data are left out, and everything
    gets the package's fixed names. Returns package bytes. Raises PackageError."""
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError):
        raise PackageError("this is not a zip file")
    with archive:
        infos = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            if _unsafe_path(info.filename):
                raise PackageError("the zip contains a file path that points outside it: %r" % info.filename)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PackageError("the zip contains a link (%s); links are not allowed" % info.filename)
            infos[info.filename] = info
        if len(infos) > MAX_FILES:
            raise PackageError("the zip holds too many files")
        indexes = sorted(n for n in infos if _is_model_index(n))
        if not indexes:
            raise PackageError("there is no 2D rigged model in the zip (no .model3.json file)")
        if len(indexes) > 1:
            raise PackageError("the zip holds several models (%s); put one model in each zip" % ", ".join(indexes[:4]))
        index = indexes[0]
        folder = posixpath.dirname(index)
        total = [0]
        read_already = {}

        def read(rel, limit):
            if _unsafe_path(rel):
                raise PackageError("the model names a file outside its folder: %r" % (rel,))
            path = posixpath.normpath(posixpath.join(folder, rel))
            if path.startswith("../") or path == "..":
                raise PackageError("the model names a file outside its folder: %r" % (rel,))
            info = infos.get(path)
            if info is None:
                raise PackageError("the model names %s, which is not in the zip" % rel)
            if info.file_size > limit:
                raise PackageError("%s is too large" % rel)
            if info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_RATIO:
                raise PackageError("%s is suspiciously compressed; it was refused" % rel)
            with archive.open(info) as f:
                data = f.read(limit + 1)
            if len(data) > limit:
                raise PackageError("%s is too large" % rel)
            total[0] += len(data)
            if total[0] > MAX_TOTAL:
                raise PackageError("the model is too large")
            return path, data

        try:
            model = json.loads(read(posixpath.basename(index), 4 * 1024 * 1024)[1].decode("utf-8-sig"))
            refs = model["FileReferences"]
            moc = refs["Moc"]
            textures = list(refs.get("Textures") or [])
            motions = dict(refs.get("Motions") or {})
            expressions = list(refs.get("Expressions") or [])
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
            raise PackageError("%s is not a .model3.json model index" % posixpath.basename(index))
        if not textures:
            raise PackageError("the model lists no textures")

        files, out_refs = {}, {"Moc": "model.moc3", "Textures": []}

        def put(rel, limit, target):
            path, data = read(rel, limit)
            if path in read_already:
                return read_already[path]
            if target.endswith(".json") and data.startswith(b"\xef\xbb\xbf"):
                data = data[3:]              # some tools write a byte-order mark; JSON readers here do not want one
            files["visual/live2d/" + target] = data
            read_already[path] = target
            return target

        put(moc, 64 * 1024 * 1024, "model.moc3")
        for i, texture in enumerate(textures):
            if not isinstance(texture, str) or not texture.lower().endswith(".png"):
                raise PackageError("texture %r is not a PNG picture" % (texture,))
            out_refs["Textures"].append(put(texture, 32 * 1024 * 1024, "textures/%02d.png" % i))
        for key, fixed in (("Physics", "model.physics3.json"), ("Pose", "model.pose3.json"),
                           ("DisplayInfo", "model.cdi3.json")):
            if refs.get(key):
                out_refs[key] = put(refs[key], 4 * 1024 * 1024, fixed)
        used = set()
        try:
            out_expressions = []
            for e in expressions:
                target = "expressions/%s.exp3.json" % _stem(e.get("Name") or e["File"], used)
                out_expressions.append({"Name": str(e.get("Name") or target)[:96], "File": put(e["File"], MAX_TEXT, target)})
            out_motions = {}
            for group, items in motions.items():
                entries = []
                for m in items:
                    target = "motions/%s.motion3.json" % _stem(m["File"], used)
                    entry = {k: m[k] for k in ("FadeInTime", "FadeOutTime") if isinstance(m.get(k), (int, float))}
                    entry["File"] = put(m["File"], 4 * 1024 * 1024, target)
                    entries.append(entry)
                out_motions[str(group)[:64]] = entries
        except (KeyError, TypeError, AttributeError):
            raise PackageError("%s lists its motions or expressions in a way this device cannot read"
                               % posixpath.basename(index))
        if out_expressions:
            out_refs["Expressions"] = out_expressions
            guessed = guess_emotions([e["Name"] for e in out_expressions])
            if guessed:
                files["visual/emotions.json"] = json.dumps(guessed, indent=1)
        if out_motions:
            out_refs["Motions"] = out_motions
        out_model = {"Version": 3, "FileReferences": out_refs}
        for key in ("Groups", "HitAreas", "Layout"):
            if key in model:
                out_model[key] = model[key]
        files[LIVE2D_MODEL] = json.dumps(out_model, indent=1, ensure_ascii=False)

    name = (name or posixpath.basename(index)[:-len(".model3.json")]).strip()[:60] or "Character"
    groups = {g.get("Name"): g.get("Ids") for g in model.get("Groups") or [] if isinstance(g, dict)}
    manifest = {
        "format": FORMAT,
        "id": slug(name),
        "name": name,
        "kind": "puppet",
        "licence": IMPORT_LICENCE,
        "capabilities": {"blink": bool(groups.get("EyeBlink")), "speak": bool(groups.get("LipSync"))},
    }
    files["persona.md"] = IMPORT_PERSONA.format(name=name)
    files["voice.json"] = json.dumps({"note": "Choose the voice on the device. No keys are stored here."}, indent=1)
    return build(files, manifest)


# Importing a VRM avatar (a 3D humanoid character, as made with VRoid Studio and similar programs)
# --------------------------------------------------------------------------------------------------

def _shorten(text, limit):
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "\u2026"


def is_inochi(data):
    """An Inochi2D puppet on its own (.inp, or Inochi Creator's .inx), rather than a character package."""
    return isinstance(data, (bytes, bytearray)) and data[:len(PUPPET_MAGIC)] == PUPPET_MAGIC


def _inochi_capabilities(params):
    """What a puppet's parameters let it do, by their names (Inochi2D's own, or Live2D's)."""
    names = [str(p.get("name", "")).lower() for p in params if isinstance(p, dict)]

    def has(*needles):
        return any(all(n in name for n in needle.split("+")) for name in names for needle in needles)
    return {"blink": has("blink", "eye+open", "eyelopen", "eyeropen"),
            "speak": has("mouth+open", "mouthopen", "mouth+aa", "vowel"),
            "head_turn": has("head+yaw", "anglex", "head+x"),
            "arm_left": has("arm+left", "arm+:: l", "arml", "armla"),
            "arm_right": has("arm+right", "arm+:: r", "armr", "armra")}


def from_inochi(data, name=None):
    """Make a character package from an Inochi2D puppet (.inp, or Inochi Creator's .inx), rigged by its
    owner. Its name, artist and licence come from its own header; which parameter turns the head, blinks
    or opens the mouth the device works out from their names (the Movement section changes that). Returns
    package bytes. Raises PackageError."""
    _check_puppet("the puppet", data)
    length = int.from_bytes(data[8:12], "big")
    header = json.loads(data[12:12 + length])
    meta = header.get("meta") if isinstance(header.get("meta"), dict) else {}
    params = header.get("param") if isinstance(header.get("param"), list) else []
    name = (name or str(meta.get("name") or "") or "Character").strip()[:60] or "Character"
    author = ", ".join(str(meta[k]).strip() for k in ("artist", "rigger") if str(meta.get(k) or "").strip())
    terms = []
    if str(meta.get("copyright") or "").strip():
        terms.append(str(meta["copyright"]).strip())
    if str(meta.get("licenseURL") or "").strip():
        terms.append("Licence: %s" % str(meta["licenseURL"]).strip())
    rights = meta.get("rights") if isinstance(meta.get("rights"), dict) else {}
    if rights.get("allow_commercial") is False:
        terms.append("Not for commercial use.")
    if rights.get("require_attribution"):
        terms.append("Credit the artist.")
    manifest = {
        "format": FORMAT,
        "id": slug(name),
        "name": name,
        "kind": "puppet",
        "author": author[:100],
        "licence": _shorten(" ".join(terms), 400),
        "capabilities": _inochi_capabilities(params),
    }
    files = {"visual/puppet.inp": bytes(data), "persona.md": IMPORT_PERSONA.format(name=name),
             "voice.json": json.dumps({"note": "Choose the voice on the device. No keys are stored here."}, indent=1)}
    return build(files, manifest)


def from_vrm(data, name=None, texture_side=vrm_format.TEXTURE_SIDE):
    """Make a character package from a .vrm file. Its textures are scaled down to `texture_side`
    pixels once, here, so the device never holds a larger picture; its maker's licence terms go into
    the manifest for the settings page to show. Returns package bytes. Raises PackageError."""
    try:
        doc, binary, about = vrm_format.check(data)
    except vrm_format.VrmError as error:
        raise PackageError(str(error))
    if contains_secret(json.dumps(doc, ensure_ascii=False)):
        raise PackageError("the avatar appears to contain an API key; it was refused")
    # Fitted to the device: textures scaled down (further if need be), or refused if it cannot be shown.
    try:
        doc, binary, fitted = vrm_format.fit(doc, binary, texture_side)
    except vrm_format.VrmError as error:
        raise PackageError(str(error))
    files = {VRM_MODEL: vrm_format.build_glb(doc, binary)}
    preview = vrm_format.thumbnail(doc, binary, about)
    if preview:
        files["preview.png"] = preview
    guessed = vrm_format.guess_emotions(about["expressions"], guess_emotions)
    if guessed:
        files["visual/emotions.json"] = json.dumps(guessed, indent=1)
    name = (name or about["name"] or "Character").strip()[:60] or "Character"
    expressions = set(about["expressions"])
    manifest = {
        "format": FORMAT,
        "id": slug(name),
        "name": name,
        "kind": "puppet",
        "author": ", ".join(about["authors"])[:100],
        "licence": _shorten(vrm_format.licence_summary(about), 400),
        "capabilities": {"blink": bool(expressions & {"blink", "blinkLeft"}), "speak": "aa" in expressions,
                         "head_turn": True, "arm_left": True, "arm_right": True, "legs": True, "vrm": True},
    }
    note = vrm_format.restricted(about)
    if note:
        manifest["licence_note"] = note
    # What it costs to show, for the settings page; a heavy one starts with its drawing kept light.
    manifest["vrm_cost"] = {k: fitted[k] for k in ("points", "triangles", "texture_mb", "estimate_mb", "textures", "lite")}
    files["persona.md"] = IMPORT_PERSONA.format(name=name)
    files["voice.json"] = json.dumps({"note": "Choose the voice on the device. No keys are stored here."}, indent=1)
    return build(files, manifest)
