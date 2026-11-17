"""Character packages: one `.char` zip file per character.

Layout (see docs/06-architecture.md):

    manifest.json     format version, id, name, kind, author, licence note, capabilities
    persona.md        system prompt, greeting, speaking style
    voice.json        preferred voice per provider type; never credentials
    voice/sample.wav  optional sample for cloning
    behaviour.json    emotion names, idle behaviour, end-of-speech pause
    visual/           depends on kind:
      puppet.inp + puppet.map.json   Inochi2D puppet and parameter mapping
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
import re
import zipfile

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
    manifest = json.loads(files["manifest.json"])
    _check_manifest(manifest)
    kind = manifest["kind"]
    if kind == "puppet" and not any(n.startswith("visual/puppet.in") for n in files):
        raise PackageError("a puppet character needs visual/puppet.inp")
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
            stored = name.endswith((".png", ".webp", ".jpg", ".webm", ".mp4", ".inp", ".inx"))
            archive.writestr(name, data, zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
    data = out.getvalue()
    open_package(io.BytesIO(data))
    return data


def slug(name):
    """A package id made from a character's name."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48]
    return s or "character"
