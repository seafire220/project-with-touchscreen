"""VRM avatars (3D humanoid characters, `.vrm` files): checking one, making it fit the device's
memory, reading who made it and how it may be used, and turning it into a character package.

A VRM file is a glTF binary file (GLB): a JSON description and one binary chunk. The device's
stage program draws it (stage/src/vrm, docs/30-vrm.md); here the file is only read, checked and
re-packed: textures larger than the device keeps are scaled down once, at import, so the stage
never has to hold a huge picture in memory.
"""
import io
import json
import struct

GLB_MAGIC = b"glTF"
MAX_VRM_BYTES = 160 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024
# The bones VRM requires (1.0 names; 0.x files name them the same way).
REQUIRED_BONES = ("hips", "spine", "head", "leftUpperArm", "leftLowerArm", "leftHand", "rightUpperArm",
                  "rightLowerArm", "rightHand", "leftUpperLeg", "leftLowerLeg", "leftFoot", "rightUpperLeg",
                  "rightLowerLeg", "rightFoot")
# VRM 0.x expression presets, by their VRM 1.0 names.
PRESETS_V0 = {"joy": "happy", "angry": "angry", "sorrow": "sad", "fun": "relaxed", "surprised": "surprised",
              "a": "aa", "i": "ih", "u": "ou", "e": "ee", "o": "oh", "blink": "blink", "blink_l": "blinkLeft",
              "blink_r": "blinkRight", "lookup": "lookUp", "lookdown": "lookDown", "lookleft": "lookLeft",
              "lookright": "lookRight", "neutral": "neutral"}
# The largest texture side kept: 1024 on 1 GB devices, 2048 with more memory.
TEXTURE_SIDE = 1024


class VrmError(ValueError):
    pass


def device_texture_side():
    """The largest texture side for this device: 2048 with 1.5 GB of memory or more, else 1024
    (the stage program decides the same way)."""
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return 2048 if int(line.split()[1]) >= 1_500_000 else 1024
    except (OSError, ValueError, IndexError):
        pass
    return TEXTURE_SIDE


def read_description(path):
    """Only the description of a .vrm file on disk (its JSON), without reading the rest."""
    with open(path, "rb") as f:
        head = f.read(20)
        if len(head) < 20 or head[:4] != GLB_MAGIC:
            raise VrmError("not a glTF binary file")
        length, kind = struct.unpack_from("<I4s", head, 12)
        if kind != b"JSON" or length > MAX_JSON_BYTES:
            raise VrmError("its description is missing or too large")
        try:
            return json.loads(f.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise VrmError("its description is not readable")


def is_vrm(data):
    """Does this look like a VRM avatar (a glTF binary file with VRM information)?"""
    if len(data) < 20 or data[:4] != GLB_MAGIC:
        return False
    length = struct.unpack_from("<I", data, 12)[0]
    head = data[20:20 + min(length, MAX_JSON_BYTES)]
    return b'"VRMC_vrm"' in head or b'"VRM"' in head


def read_glb(data):
    """The description (as a dict) and the binary chunk of a glTF binary file."""
    if len(data) < 20 or data[:4] != GLB_MAGIC:
        raise VrmError("this is not a glTF binary (.vrm or .glb) file")
    version, total = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise VrmError("glTF version %d is not supported (version 2 is)" % version)
    total = min(total, len(data))
    at, doc, binary = 12, None, b""
    while at + 8 <= total:
        length, kind = struct.unpack_from("<I4s", data, at)
        start, end = at + 8, at + 8 + length
        if end > total:
            raise VrmError("the file is cut short")
        if kind == b"JSON":
            if length > MAX_JSON_BYTES:
                raise VrmError("its description is far too large")
            try:
                doc = json.loads(data[start:end].decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise VrmError("its description is not readable")
        elif kind == b"BIN\x00" and not binary:
            binary = data[start:end]
        at = (end + 3) & ~3
    if not isinstance(doc, dict):
        raise VrmError("the file has no description")
    return doc, binary


def build_glb(doc, binary):
    text = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary = bytes(binary) + b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + (8 + len(binary) if binary else 0)
    out = io.BytesIO()
    out.write(struct.pack("<4sII", GLB_MAGIC, 2, total))
    out.write(struct.pack("<I4s", len(text), b"JSON"))
    out.write(text)
    if binary:
        out.write(struct.pack("<I4s", len(binary), b"BIN\x00"))
        out.write(binary)
    return out.getvalue()


def _ext(doc):
    ext = doc.get("extensions") or {}
    if isinstance(ext.get("VRMC_vrm"), dict):
        return 1, ext["VRMC_vrm"]
    if isinstance(ext.get("VRM"), dict):
        return 0, ext["VRM"]
    raise VrmError("this glTF file is not a VRM avatar (it has no VRM information)")


def info(doc):
    """What the device shows and needs about an avatar: its version, name, authors, licence terms
    (as the maker set them), expression names, and which image is its thumbnail."""
    version, vrm = _ext(doc)
    meta = vrm.get("meta") or {}
    humanoid = vrm.get("humanoid") or {}
    if version == 1:
        bones = set((humanoid.get("humanBones") or {}).keys())
        name = meta.get("name") or ""
        authors = [a for a in meta.get("authors") or [] if isinstance(a, str)]
        licence = {k: meta[k] for k in ("licenseUrl", "avatarPermission", "commercialUsage", "allowRedistribution",
                                         "modification", "creditNotation", "otherLicenseUrl") if k in meta}
        ex = vrm.get("expressions") or {}
        expressions = list((ex.get("preset") or {}).keys()) + list((ex.get("custom") or {}).keys())
        thumbnail = meta.get("thumbnailImage")
    else:
        bones = {b.get("bone") for b in humanoid.get("humanBones") or [] if isinstance(b, dict)}
        name = meta.get("title") or ""
        authors = [meta["author"]] if isinstance(meta.get("author"), str) and meta["author"] else []
        licence = {k: meta[k] for k in ("licenseName", "otherPermissionUrl", "allowedUserName", "commercialUssageName",
                                         "violentUssageName", "sexualUssageName", "otherLicenseUrl") if k in meta}
        expressions = []
        groups = (vrm.get("blendShapeMaster") or {}).get("blendShapeGroups") or []
        for g in groups:
            if not isinstance(g, dict):
                continue
            preset = PRESETS_V0.get(str(g.get("presetName") or "").lower())
            label = preset or g.get("name")
            if isinstance(label, str) and label and label not in expressions:
                expressions.append(label)
        texture = meta.get("texture")
        textures = doc.get("textures") or []
        thumbnail = None
        if isinstance(texture, int) and 0 <= texture < len(textures):
            thumbnail = textures[texture].get("source")
    return {"version": version, "name": name if isinstance(name, str) else "", "authors": authors,
            "licence": licence, "expressions": [e for e in expressions if isinstance(e, str)],
            "bones": sorted(b for b in bones if isinstance(b, str)),
            "thumbnail": thumbnail if isinstance(thumbnail, int) else None}


def check(data):
    """Refuse a file the device cannot use, saying why. Returns (description, binary, info)."""
    if len(data) > MAX_VRM_BYTES:
        raise VrmError("the avatar is too large (over %d MB)" % (MAX_VRM_BYTES // (1024 * 1024)))
    doc, binary = read_glb(data)
    about = info(doc)
    missing = [b for b in REQUIRED_BONES if b not in about["bones"]]
    if missing:
        raise VrmError("the avatar has no %s bone, which VRM requires" % missing[0])
    for b in doc.get("buffers") or []:
        if isinstance(b, dict) and "uri" in b:
            raise VrmError("the avatar keeps its data in a separate file; use a single .vrm file")
    return doc, binary, about


def licence_summary(about):
    """The maker's terms in plain words, for the settings page."""
    words = {
        "avatarPermission": {"onlyAuthor": "only its maker may use it as an avatar",
                             "onlySeparatelyLicensedPerson": "only people its maker licensed may use it",
                             "everyone": "anyone may use it as an avatar"},
        "allowedUserName": {"OnlyAuthor": "only its maker may use it as an avatar",
                            "ExplicitlyLicensedPerson": "only people its maker licensed may use it",
                            "Everyone": "anyone may use it as an avatar"},
        "commercialUsage": {"personalNonProfit": "personal, non-profit use only",
                            "personalProfit": "personal use, including for profit",
                            "corporation": "commercial use allowed"},
        "commercialUssageName": {"Disallow": "no commercial use", "Allow": "commercial use allowed"},
    }
    parts = []
    for key, value in about["licence"].items():
        if key in words and value in words[key]:
            parts.append(words[key][value])
    url = about["licence"].get("licenseUrl") or about["licence"].get("otherPermissionUrl")
    who = ", ".join(about["authors"]) or "an unnamed maker"
    text = "VRM avatar%s by %s" % (" “%s”" % about["name"] if about["name"] else "", who)
    if parts:
        text += ": " + "; ".join(parts)
    if url:
        text += " (terms: %s)" % url
    return text + ". The person who imported it is responsible for having the right to use it on this device."


def restricted(about):
    """A note if the maker allows only themselves (or people they licensed) to use the avatar."""
    value = about["licence"].get("avatarPermission") or about["licence"].get("allowedUserName")
    if value in ("onlyAuthor", "OnlyAuthor"):
        return "Its maker allows only themselves to use this avatar."
    if value in ("onlySeparatelyLicensedPerson", "ExplicitlyLicensedPerson"):
        return "Its maker allows only people they licensed to use this avatar."
    return None


def shrink_textures(doc, binary, side=TEXTURE_SIDE):
    """Scale down every image larger than `side` pixels, once, keeping PNG as PNG and JPEG as JPEG,
    and re-pack the binary chunk. Returns (doc, binary, report)."""
    from PIL import Image
    views = doc.get("bufferViews") or []
    images = doc.get("images") or []
    replaced = {}
    report = {"images": len(images), "shrunk": 0, "bytes_before": len(binary)}
    for i, img in enumerate(images):
        v = img.get("bufferView") if isinstance(img, dict) else None
        if not isinstance(v, int) or not 0 <= v < len(views):
            continue
        view = views[v]
        start = view.get("byteOffset", 0)
        data = binary[start:start + view.get("byteLength", 0)]
        try:
            with Image.open(io.BytesIO(data)) as im:
                if max(im.size) <= side:
                    continue
                fmt = "JPEG" if (im.format == "JPEG" or img.get("mimeType") == "image/jpeg") else "PNG"
                im.load()
                scale = side / float(max(im.size))
                small = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
                out = io.BytesIO()
                if fmt == "JPEG":
                    small.convert("RGB").save(out, "JPEG", quality=90)
                else:
                    small.save(out, "PNG", optimize=True)
        except Exception:                       # an unreadable picture is left as it is for the stage to judge
            continue
        replaced[v] = out.getvalue()
        report["shrunk"] += 1
    if not replaced:
        report["bytes_after"] = len(binary)
        return doc, binary, report
    # Re-pack every buffer view, in order, each starting on a 4-byte boundary.
    out = io.BytesIO()
    new_views = []
    for k, view in enumerate(views):
        pad = (-out.tell()) % 4
        out.write(b"\x00" * pad)
        if k in replaced:
            data = replaced[k]
        else:
            start = view.get("byteOffset", 0)
            data = binary[start:start + view.get("byteLength", 0)]
        nv = dict(view)
        nv["byteOffset"] = out.tell()
        nv["byteLength"] = len(data)
        new_views.append(nv)
        out.write(data)
    doc = dict(doc)
    doc["bufferViews"] = new_views
    packed = out.getvalue()
    if doc.get("buffers"):
        doc["buffers"] = [dict(doc["buffers"][0], byteLength=len(packed))] + list(doc["buffers"][1:])
    report["bytes_after"] = len(packed)
    return doc, packed, report


def thumbnail(doc, binary, about, side=512):
    """The avatar's own thumbnail as PNG bytes, or None."""
    from PIL import Image
    index = about.get("thumbnail")
    images = doc.get("images") or []
    if index is None or not 0 <= index < len(images):
        return None
    v = images[index].get("bufferView")
    views = doc.get("bufferViews") or []
    if not isinstance(v, int) or not 0 <= v < len(views):
        return None
    start = views[v].get("byteOffset", 0)
    try:
        with Image.open(io.BytesIO(binary[start:start + views[v].get("byteLength", 0)])) as im:
            im = im.convert("RGBA")
            im.thumbnail((side, side))
            out = io.BytesIO()
            im.save(out, "PNG")
            return out.getvalue()
    except Exception:
        return None


def guess_emotions(expressions, guess_custom):
    """Our emotions shown by the avatar's own expressions: the presets of the same name, and its
    other expressions by their names (a blush for embarrassment, say)."""
    mapping = {}
    for emotion in ("happy", "sad", "angry", "surprised"):
        if emotion in expressions:
            mapping[emotion] = emotion
    custom = [e for e in expressions if e not in PRESETS_V0.values()]
    for emotion, name in guess_custom(custom).items():
        mapping.setdefault(emotion, name)
    return mapping
