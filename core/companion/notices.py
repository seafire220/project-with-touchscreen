"""Licences and notices: the parts the device's software is made of, and the terms each comes with.

The settings page's "Licences and notices" (`/licences`, open to anyone on the home network, like the
licence leaflet in a box) shows:

- this product's own notice, trademarks and the offer of source code (`notices/device.txt`, with the
  maker's details from `notices/product.json`);
- the licences of the libraries built into the stage program (`share/licenses/stage.txt`, made by
  `stage/tools/notices.py`);
- every Python package installed, with the licence files it carries, read from the installed packages
  themselves, so it is always what is on the device;
- the libraries built into the speech package (sherpa-onnx), which its own files do not list, with
  ONNX Runtime's third-party notices (`notices/libraries.txt`, `notices/onnxruntime-notices.txt`);
- every operating-system package, with its Debian copyright file (which holds its licence);
- the speech and voice models, with their credits (some licences require them) and the licence files
  that came with them.

Character Studio shows the same for its own parts (`studio/app.py`), with these functions.
"""
import html
import importlib.metadata
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OWN = os.path.join(HERE, "notices")
SHARE = os.environ.get("COMPANION_SHARE", "/opt/companion/share")
LICENCE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|AUTHORS|COPYRIGHT)[^/]*$", re.I)
CLASSIFIER = "License :: "


def product():
    """The maker's details for the notices (the owner fills these in: notices/product.json)."""
    try:
        with open(os.path.join(OWN, "product.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


IMAGE_FILE = os.environ.get("COMPANION_IMAGE_FILE", "/etc/companion-image")


def image_version():
    """The version of the card image the device came with (its operating system's packages are from it)."""
    try:
        with open(IMAGE_FILE, encoding="utf-8") as f:
            return f.read().strip() or "unknown"
    except OSError:
        return "unknown"


def device_notice():
    with open(os.path.join(OWN, "device.txt"), encoding="utf-8") as f:
        text = f.read()
    p = product()
    image = image_version()
    source = (p.get("source_url") or "the address given by the seller").replace("{image_version}", image)
    return (text.replace("{maker}", p.get("maker") or "the maker of this device")
            .replace("{source_url}", source)
            .replace("{contact}", p.get("contact") or "the seller")
            .replace("{image_version}", image))


def stage_licences():
    """The stage program's libraries, as installed with this version (or beside the source)."""
    for path in (os.path.join(SHARE, "licenses", "stage.txt"),
                 os.path.join(HERE, "..", "..", "stage", "THIRD_PARTY_LICENSES.txt")):
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
    return "The stage program's licence list is not installed.\n"


def _licence_name(meta):
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [c[len(CLASSIFIER):].split(" :: ")[-1] for c in meta.get_all("Classifier") or []
                   if c.startswith(CLASSIFIER)]
    if classifiers:
        return "; ".join(classifiers)
    short = (meta.get("License") or "").strip()
    return short if short and len(short) < 80 and "\n" not in short else "see its licence text"


def python_packages():
    """Every installed Python package: name, version, licence and the licence files it carries."""
    out, seen = [], set()
    for dist in importlib.metadata.distributions():
        meta = dist.metadata
        name = meta.get("Name") or "?"
        key = (name.lower(), dist.version)
        if key in seen:
            continue
        seen.add(key)
        texts = []
        for f in dist.files or []:
            path = str(f)
            if ".dist-info/" in path and LICENCE_FILE.search(path):
                try:
                    texts.append(f.read_text(encoding="utf-8").strip() + "\n")
                except (OSError, UnicodeDecodeError, ValueError):
                    pass
        out.append({"name": name, "version": dist.version, "licence": _licence_name(meta), "texts": texts})
    return sorted(out, key=lambda p: p["name"].lower())


def _numbered(entries):
    """A list of entries with their texts given once each, numbered: (lines, texts)."""
    index, order, lines = {}, [], []
    for name, version, licence, texts in entries:
        refs = []
        for t in texts:
            if t not in index:
                index[t] = len(order) + 1
                order.append(t)
            refs.append("[%d]" % index[t])
        lines.append("%-40s %-24s %-36s %s" % (name, version, licence[:36], " ".join(refs) or "-"))
    return lines, order


def _document(title, intro, lines, texts):
    out = [title, "", intro, ""] + lines + [""]
    for i, t in enumerate(texts, start=1):
        out += ["=" * 100, "[%d]" % i, "", t]
    return "\n".join(out) + "\n"


def python_licences(title="Python packages on this device", where=""):
    packages = python_packages()
    lines, texts = _numbered((p["name"], p["version"], p["licence"], p["texts"]) for p in packages)
    return _document(title, "%s%d packages, each with the licence it is used under and the licence files it "
                     "carries (numbered below, each text once)." % (where, len(packages)), lines, texts)


def speech_libraries():
    """The libraries built into the speech package (sherpa-onnx), whose own files do not list them, and
    ONNX Runtime's third-party notices (notices/libraries.txt, notices/onnxruntime-notices.txt)."""
    out = []
    for name in ("libraries.txt", "onnxruntime-notices.txt"):
        with open(os.path.join(OWN, name), encoding="utf-8") as f:
            out.append(f.read().rstrip() + "\n")
    return ("\n" + "=" * 100 + "\n").join(out)


def os_packages(status="/var/lib/dpkg/status"):
    """The operating system's installed packages: (name, version, source package)."""
    out = []
    try:
        with open(status, encoding="utf-8", errors="replace") as f:
            blocks = f.read().split("\n\n")
    except OSError:
        return out
    for block in blocks:
        fields = dict(re.findall(r"^([A-Za-z-]+): ?(.*)$", block, re.M))
        if fields.get("Package") and "installed" in fields.get("Status", ""):
            source = (fields.get("Source") or fields["Package"]).split(" ")[0]
            out.append((fields["Package"], fields.get("Version", ""), source))
    return sorted(out)


def os_licences(status="/var/lib/dpkg/status", docs="/usr/share/doc"):
    packages = os_packages(status)
    entries = []
    for name, version, source in packages:
        texts = []
        path = os.path.join(docs, name.split(":")[0], "copyright")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                texts.append(f.read().strip() + "\n")
        except OSError:
            pass
        entries.append((name, version, "source package: " + source, texts))
    lines, texts = _numbered(entries)
    return _document("Operating-system packages on this device (Raspberry Pi OS, based on Debian)",
                     "%d packages, each with its Debian copyright file (numbered below, each text once), which "
                     "gives its licence. See the offer of source code in this device's notice." % len(packages),
                     lines, texts)


MODEL_FILES = ("MODEL_CARD", "LICENSE", "README.md", "README")


def model_licences(folders):
    """The models' credits (notices/models.txt) and the licence files that came with each."""
    with open(os.path.join(OWN, "models.txt"), encoding="utf-8") as f:
        out = [f.read().rstrip() + "\n"]
    for name, folder in folders:
        for leaf in MODEL_FILES:
            path = os.path.join(folder, leaf)
            if os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                if len(text) > 60000:
                    text = text[:60000] + "\n[...]\n"
                out.append("=" * 100 + "\nAs it came with the %s model (%s):\n\n%s" % (name, leaf, text.strip() + "\n"))
    return "\n".join(out)


def third_party():
    for path in (os.path.join(SHARE, "THIRD_PARTY.md"), os.path.join(HERE, "..", "..", "THIRD_PARTY.md")):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    return ""


DOCUMENTS = {
    "device": ("This device's notice, trademarks and source code", "device_notice"),
    "third-party": ("What is in it, in short", "third_party"),
    "stage": ("The screen program's libraries", "stage_licences"),
    "python": ("Python packages", "python_licences"),
    "libraries": ("Libraries inside the speech package (ONNX Runtime, Eigen and others)", "speech_libraries"),
    "os": ("Operating-system packages", "os_licences"),
    "models": ("Speech, voice and other models", "model_licences"),
}


def index_page(names, version="", what="This device's software", back=("/", "Back to the settings page")):
    """The page linking to each document, for the settings page's "Licences and notices" (and Character
    Studio's)."""
    items = "".join('<li><a href="/licences/%s.txt">%s</a></li>' % (key, html.escape(names[key])) for key in names)
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Licences and notices</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}
@media (prefers-color-scheme: dark){body{color:#eee;background:#17171a}a{color:#9ab}}</style></head><body>
<h1>Licences and notices</h1>
<p>%s%s is made with open-source software and models from many people. Each part's licence, and the
credits some of them ask for, are below. Some licences (the GNU GPL and LGPL among them) let you have the
source code: see the first document.</p>
<ul>%s</ul>
<p><a href="%s">%s</a></p>
</body></html>""" % (html.escape(what), " (version %s)" % html.escape(version) if version else "", items,
                     html.escape(back[0]), html.escape(back[1]))
