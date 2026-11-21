#!/usr/bin/env python3
"""Write the licences of the Rust libraries built into the stage program, for the device's notices:
stage/THIRD_PARTY_LICENSES.txt.

    python3 stage/tools/notices.py           # write it
    python3 stage/tools/notices.py --check   # fail if it no longer matches Cargo.lock (the workflows run this)

Every library the device's build compiles in (the aarch64 Linux target, not tests or build helpers) is
listed with its version, licence and the licence text from its own package, each different text once.
Where a library offers a choice of licences, the notice follows the first that is permissive and short
(MIT, then BSD, ISC, Zlib, then Apache-2.0). The two libraries that ship no licence file (both MIT) get the
standard MIT text with their authors as copyright holders.
"""
import json
import os
import re
import subprocess
import sys

STAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(STAGE, "THIRD_PARTY_LICENSES.txt")
TARGET = "aarch64-unknown-linux-gnu"
PREFER = ["MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib", "0BSD", "Unlicense", "Apache-2.0",
          "Apache-2.0 WITH LLVM-exception", "Unicode-3.0", "BSL-1.0", "CC0-1.0"]
FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|UNLICENSE|COPYRIGHT)", re.I)
MIT = """Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial
portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
USE OR OTHER DEALINGS IN THE SOFTWARE.
"""


def metadata():
    out = subprocess.run(["cargo", "metadata", "--format-version", "1", "--filter-platform", TARGET, "--locked"],
                         cwd=STAGE, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def built_in(meta):
    """The packages compiled into the program: normal dependencies, followed from the program itself."""
    packages = {p["id"]: p for p in meta["packages"]}
    nodes = {n["id"]: n for n in meta["resolve"]["nodes"]}
    root = meta["resolve"]["root"]
    seen, stack = set(), [root]
    while stack:
        i = stack.pop()
        if i in seen:
            continue
        seen.add(i)
        for dep in nodes[i]["deps"]:
            if any(k.get("kind") is None for k in dep["dep_kinds"]):
                stack.append(dep["pkg"])
    seen.discard(root)
    return sorted((packages[i] for i in seen), key=lambda p: (p["name"], p["version"]))


def chosen(expression):
    """The licence the notice follows, from an SPDX expression such as "MIT OR Apache-2.0"."""
    expression = (expression or "").replace("/", " OR ")
    if " AND " in expression:
        return expression.strip()                     # all apply: keep the whole expression
    options = [o.strip(" ()") for o in expression.split(" OR ")]
    for want in PREFER:
        if want in options:
            return want
    return options[0] if options else "unknown"


def texts(package, licence):
    """The licence texts to include: the package's own files for the licence followed, and any NOTICE."""
    folder = os.path.dirname(package["manifest_path"])
    files = sorted(f for f in os.listdir(folder) if FILE.match(f) and os.path.isfile(os.path.join(folder, f)))
    key = {"MIT": "MIT", "Apache-2.0": "APACHE", "BSD-2-Clause": "BSD", "BSD-3-Clause": "BSD", "Zlib": "ZLIB",
           "Unlicense": "UNLICENSE", "ISC": "ISC"}.get(licence)
    pick = [f for f in files if key and key in f.upper()] if len(files) > 1 else files
    pick = pick or [f for f in files if "NOTICE" not in f.upper()] or files
    pick += [f for f in files if "NOTICE" in f.upper() and f not in pick]
    out = []
    for f in pick:
        with open(os.path.join(folder, f), encoding="utf-8", errors="replace") as handle:
            out.append(handle.read().strip() + "\n")
    if not out and licence == "MIT":
        holders = ", ".join(re.sub(r"\s*<[^>]*>", "", a) for a in package.get("authors") or []) or "the authors"
        out.append("MIT License\n\nCopyright (c) %s\n\n%s" % (holders, MIT))
    return out


def render(meta):
    packages = built_in(meta)
    blocks, order, listing = {}, [], []
    for p in packages:
        licence = chosen(p.get("license"))
        refs = []
        for text in texts(p, licence):
            if text not in blocks:
                blocks[text] = len(order) + 1
                order.append(text)
            refs.append(blocks[text])
        listing.append("%-40s %-12s %-28s text %s" % (p["name"], p["version"], licence,
                                                        ", ".join("[%d]" % r for r in refs) or "(none)"))
    head = ("Licences of the Rust libraries built into the stage program (the device's screen program)\n"
            "%d libraries, for %s; made by stage/tools/notices.py from stage/Cargo.lock.\n"
            "Each library's licence text is given once below, numbered; a library offering a choice of licences\n"
            "is used under the one shown.\n\n" % (len(packages), TARGET))
    body = "\n".join(listing) + "\n"
    texts_part = "".join("\n" + "=" * 100 + "\n[%d]\n\n%s" % (i + 1, t) for i, t in enumerate(order))
    return head + body + texts_part


def main(argv):
    text = render(metadata())
    if "--check" in argv:
        try:
            with open(OUT, encoding="utf-8") as f:
                same = f.read() == text
        except OSError:
            same = False
        if not same:
            raise SystemExit("stage/THIRD_PARTY_LICENSES.txt is out of date: run python3 stage/tools/notices.py")
        print("stage/THIRD_PARTY_LICENSES.txt is up to date")
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
