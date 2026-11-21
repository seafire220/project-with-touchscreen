"""Character Studio's "Licences and notices" (`/licences`, linked at the bottom of its page): the parts the
app is made of and what it downloads, each with its licence.

- Character Studio's own notice and the trademarks (`packaging/notice.txt`);
- the Python inside the app: its own LICENSE.txt and the libraries built into it
  (`packaging/python-licences.txt`);
- the Python packages it downloaded when it was set up, with the licence files each carries, read from
  what is installed (core/companion/notices.py);
- the part finder (See-through) it downloaded: its licence file and the model's terms;
- in the Linux app, the AppImage runtime (`packaging/appimage-runtime-licences.txt`);
- the short list of everything (THIRD_PARTY.md).

In the app, build_app.py puts the packaging files in `licenses/` beside the studio's code.
"""
import os

from companion import notices

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                # the app's own folder, or the repository
BUNDLED = {"notice.txt": "notice.txt", "python-components.txt": "python-licences.txt",
           "appimage-runtime.txt": "appimage-runtime-licences.txt"}
LICENCE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE", "COPYING", "NOTICE")


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def bundled(name, from_source=True):
    """A licence file the app carries in licenses/ (run from the source: studio/packaging/)."""
    candidates = [os.path.join(ROOT, "licenses", name)]
    if from_source:
        candidates.append(os.path.join(HERE, "packaging", BUNDLED[name]))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def studio_notice():
    path = bundled("notice.txt")
    text = _read(path) if path else "Character Studio\n"
    return text.replace("{maker}", notices.product().get("maker") or "the maker of Character Studio")


def python_licence():
    """The Python running the studio: its own licence, then the licences of what is built into it."""
    lib = os.path.dirname(os.__file__)          # .../lib/python3.12, or ...\Lib on Windows
    out = []
    for path in (os.path.join(lib, "LICENSE.txt"), os.path.join(os.path.dirname(lib), "LICENSE.txt")):
        if os.path.isfile(path):
            out.append("Python's own licence (%s)\n\n%s" % (os.path.basename(path), _read(path).strip() + "\n"))
            break
    components = bundled("python-components.txt")
    if components:
        out.append(_read(components))
    return ("\n" + "=" * 100 + "\n").join(out) or "Python's licence files were not found.\n"


def packages():
    return notices.python_licences(
        "Python packages Character Studio uses on this computer",
        "Downloaded from the Python Package Index (PyTorch from its project's own server) when Character Studio "
        "was set up, into its own folder on this computer. ")


def part_finder(config):
    """See-through, downloaded at setup: its licence file, and the model's terms."""
    out = ["THE PART FINDER (SEE-THROUGH)\n\n"
           "Character Studio finds a character's body parts with See-through (shitagaki-lab), downloaded when it\n"
           "was set up: its code at a fixed version from https://github.com/shitagaki-lab/see-through, and its\n"
           "body-part model (24yearsold/l2d_sam_iter2, a fine-tune of SAM-HQ) from\n"
           "https://huggingface.co/24yearsold/l2d_sam_iter2. Both are under the Apache License 2.0; the model's\n"
           "page says it may be used commercially. Neither is part of the app.\n"]
    folder = (config or {}).get("see_through")
    if folder and os.path.isdir(folder):
        for name in LICENCE_NAMES:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                out.append("=" * 100 + "\nSee-through's %s, as downloaded:\n\n%s" % (name, _read(path).strip() + "\n"))
    else:
        out.append("(Not downloaded on this computer yet.)\n")
    return "\n".join(out)


def appimage_runtime():
    path = bundled("appimage-runtime.txt", from_source=False)
    return _read(path) if path else ""


def documents(config=None):
    """The documents to list: key -> (title, function giving the text). The AppImage's only in the Linux app."""
    out = {
        "notice": ("Character Studio's notice and trademarks", studio_notice),
        "python": ("The Python inside Character Studio", python_licence),
        "packages": ("Python packages it downloaded", packages),
        "part-finder": ("The part finder (See-through) and its model", lambda: part_finder(config)),
    }
    if bundled("appimage-runtime.txt", from_source=False):
        out["appimage"] = ("The AppImage runtime (Linux) and its source code", appimage_runtime)
    out["third-party"] = ("Everything, in short", notices.third_party)
    return out


def index(config=None, version=""):
    names = {key: title for key, (title, _) in documents(config).items()}
    return notices.index_page(names, version, what="Character Studio", back=("/", "Back to Character Studio"))
