#!/usr/bin/env python3
"""Download the source code of every operating-system package in a device image: what the GNU GPL and LGPL
entitle the device's owners to, published with each image (docs/34-licences.md).

    sudo python3 device/fetch-sources.py PACKAGES_DIR OUT_DIR

PACKAGES_DIR is what `check-image.sh IMAGE --packages DIR` copies out of the image: packages.tsv (every
installed package, with its source package and version), the image's own package sources (sources/)
and its archive keys (keyrings/).

Each source package is downloaded at exactly the version in the image, with apt, from the image's own
archives (Debian's and Raspberry Pi's), into OUT_DIR/<source package>/. One that has since been replaced
by a newer version is taken from the archives' pool folders, where Raspberry Pi keeps old versions
(each file checked against the SHA-256 its .dsc lists), or from Debian's snapshot archive
(snapshot.debian.org, each file checked against the hash it is listed with). OUT_DIR/README.txt says what is there; OUT_DIR/MISSING.txt lists any that could not be
found, and the script then ends with status 3.

apt runs with its own settings in a scratch folder, so the computer's own package sources are not used
or changed. Uses Python's own library and apt-get.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

SNAPSHOT = "https://snapshot.debian.org"
README = """SOURCE CODE OF THE OPERATING SYSTEM IN THE DEVICE'S CARD IMAGE

These are the source packages of every operating-system package installed in the device's card image
(Raspberry Pi OS, which is based on Debian GNU/Linux), each at exactly the version installed: the source
code the GNU General Public License, the GNU Lesser General Public License and other licences of those
packages entitle you to.

Each folder is one source package: its .dsc file and the archives it lists (an .orig.tar.* with the
original source and a .debian.tar.* with Debian's or Raspberry Pi's changes, or a single .tar.* for
packages made for Debian or Raspberry Pi). To unpack one, on Debian or Ubuntu:

    dpkg-source -x <package>_<version>.dsc

and to build it, `dpkg-buildpackage -b` in the unpacked folder (with the packages its
debian/control file names as build dependencies installed).

packages.tsv lists every installed package: its name, version, source package and source version.
The licences themselves are in each package's debian/copyright file, and on the device in
/usr/share/doc/<package>/copyright (the settings page's "Licences and notices" shows them).

%d source packages.%s
"""


def read_packages(path):
    """The (source package, source version) pairs in packages.tsv, each once."""
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 4 and parts[2].strip() and parts[3].strip():
                out.add((parts[2].strip(), parts[3].strip()))
    return sorted(out)


def _key_name(path):
    """A key file's name apt accepts: .asc if it is armoured, .gpg otherwise."""
    with open(path, "rb") as f:
        armoured = f.read(64).lstrip().startswith(b"-----BEGIN")
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem + (".asc" if armoured else ".gpg")


def source_entries(text, name, keys, renamed):
    """An image's package-source file as source-code sources ("deb-src"), its keys in `keys`."""
    if name.endswith(".sources"):
        text = re.sub(r"(?m)^Types:.*$", "Types: deb-src", text)
    elif name.endswith(".list"):
        text = "".join("deb-src" + line[3:] + "\n" for line in text.splitlines() if re.match(r"deb\s", line))
    else:
        return ""

    def key(m):
        base = os.path.basename(m.group(2).strip())
        return m.group(1) + os.path.join(keys, renamed.get(base, base))
    text = re.sub(r"(?m)^(Signed-By:\s*)(/\S+)\s*$", key, text)
    return re.sub(r"signed-by=(/[^\s\]]+)", lambda m: "signed-by=" + os.path.join(
        keys, renamed.get(os.path.basename(m.group(1)), os.path.basename(m.group(1)))), text)


def apt_command(work, packages_dir):
    """apt-get with its own settings in `work`: the image's sources as source-code sources, its keys."""
    etc = os.path.join(work, "etc")
    parts, keys = os.path.join(etc, "sources.list.d"), os.path.join(etc, "keys")
    for d in (parts, keys, os.path.join(work, "lists", "partial"),
              os.path.join(work, "cache", "archives", "partial")):
        os.makedirs(d, exist_ok=True)
    renamed = {}
    key_dir = os.path.join(packages_dir, "keyrings")
    for name in sorted(os.listdir(key_dir)) if os.path.isdir(key_dir) else []:
        path = os.path.join(key_dir, name)
        if os.path.isfile(path):
            renamed[name] = _key_name(path)
            shutil.copy2(path, os.path.join(keys, renamed[name]))
    found = 0
    for name in sorted(os.listdir(os.path.join(packages_dir, "sources"))):
        with open(os.path.join(packages_dir, "sources", name), encoding="utf-8") as f:
            text = source_entries(f.read(), name, keys, renamed)
        if text.strip():
            found += 1
            with open(os.path.join(parts, name if name.endswith(".sources") else name[:-5] + ".list"), "w",
                      encoding="utf-8") as f:
                f.write(text)
    if not found:
        raise SystemExit("no package sources in %s/sources" % packages_dir)
    command = ["apt-get", "-q", "-o", "Dir::Etc::SourceList=/dev/null", "-o", "Dir::Etc::SourceParts=" + parts,
               "-o", "Dir::Etc::TrustedParts=" + keys, "-o", "Dir::Etc::Trusted=/dev/null",
               "-o", "Dir::State::Lists=" + os.path.join(work, "lists"), "-o", "Dir::Cache=" + os.path.join(work, "cache"),
               "-o", "Dir::Etc::Preferences=/dev/null", "-o", "Dir::Etc::PreferencesParts=/dev/null"]
    if os.geteuid() == 0:
        command += ["-o", "APT::Sandbox::User=root"]
    return command


def archives(packages_dir):
    """The image's archives: (address, components) for each source entry, from its package sources."""
    out = []
    folder = os.path.join(packages_dir, "sources")
    for name in sorted(os.listdir(folder)):
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            text = f.read()
        if name.endswith(".sources"):
            for stanza in re.split(r"\n\s*\n", text):
                fields = dict(re.findall(r"(?m)^([A-Za-z-]+):\s*(.*)$", stanza))
                if fields.get("Enabled", "yes").lower() == "no":
                    continue
                for uri in fields.get("URIs", "").split():
                    out.append((uri.rstrip("/"), fields.get("Components", "main").split()))
        elif name.endswith(".list"):
            for line in text.splitlines():
                m = re.match(r"deb(?:-src)?\s+(?:\[[^\]]*\]\s+)?(\S+)\s+\S+\s+(.*)$", line.strip())
                if m:
                    out.append((m.group(1).rstrip("/"), m.group(2).split() or ["main"]))
    seen, unique = set(), []
    for uri, components in out:
        for c in components:
            if (uri, c) not in seen:
                seen.add((uri, c))
                unique.append((uri, c))
    return unique


def pool_folder(source):
    return source[:4] if source.startswith("lib") and len(source) > 3 else source[0]


def dsc_files(text):
    """The (name, SHA-256) of each file a .dsc lists."""
    m = re.search(r"(?ms)^Checksums-Sha256:\s*\n((?:[ \t]+\S+[ \t]+\d+[ \t]+\S+\n?)+)", text)
    if not m:
        return []
    return [(parts[2], parts[0]) for parts in (line.split() for line in m.group(1).splitlines()) if len(parts) == 3]


def from_pool(source, version, folder, places):
    """A source package from an archive's pool folder, which may keep versions its index no longer lists."""
    plain = version.split(":", 1)[-1]
    for uri, component in places:
        base = "%s/pool/%s/%s/%s/" % (uri, component, pool_folder(source), source)
        dsc_name = "%s_%s.dsc" % (source, plain)
        try:
            dsc = _get(base + urllib.parse.quote(dsc_name), attempts=1)
        except OSError:
            continue
        files = dsc_files(dsc.decode("utf-8", "replace"))
        if not files:
            continue
        for name, digest in files:
            data = _get(base + urllib.parse.quote(name))
            if hashlib.sha256(data).hexdigest() != digest:
                raise OSError("%s from %s does not match its .dsc" % (name, uri))
            with open(os.path.join(folder, name), "wb") as f:
                f.write(data)
        with open(os.path.join(folder, dsc_name), "wb") as f:
            f.write(dsc)
        return True
    return False


def _get(url, attempts=4):
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as error:
            if error.code == 404 or attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))


def from_snapshot(source, version, folder):
    """A source package's files from snapshot.debian.org, each checked against its SHA-1 there."""
    url = "%s/mr/package/%s/%s/srcfiles?fileinfo=1" % (SNAPSHOT, urllib.parse.quote(source, safe=""),
                                                       urllib.parse.quote(version, safe=""))
    listing = json.loads(_get(url))
    hashes = [entry["hash"] for entry in listing.get("result", [])]
    if not hashes:
        return False
    for digest in hashes:
        name = listing["fileinfo"][digest][0]["name"]
        data = _get("%s/file/%s" % (SNAPSHOT, digest))
        if hashlib.sha1(data).hexdigest() != digest:
            raise OSError("%s from the snapshot archive does not match its hash" % name)
        with open(os.path.join(folder, os.path.basename(name)), "wb") as f:
            f.write(data)
    return True


def fetch(packages_dir, out):
    pairs = read_packages(os.path.join(packages_dir, "packages.tsv"))
    places = archives(packages_dir)
    os.makedirs(out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="apt-sources-")
    try:
        apt = apt_command(work, packages_dir)
        if subprocess.run(apt + ["update"]).returncode != 0:
            print("::warning::some package archives could not be read; their packages come from the snapshot "
                  "archive instead", flush=True)
        missing = []
        for source, version in pairs:
            # Each version into a folder of its own first: a failed try then leaves nothing behind.
            folder = tempfile.mkdtemp(prefix=".fetching-", dir=out)
            got = subprocess.run(apt + ["source", "--download-only", "%s=%s" % (source, version)], cwd=folder,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            how = "archive"
            if not got:
                try:
                    got, how = from_pool(source, version, folder, places), "archive's pool"
                except OSError as error:
                    print("pool: %s %s: %s" % (source, version, error), file=sys.stderr)
            if not got:
                try:
                    got, how = from_snapshot(source, version, folder), "snapshot.debian.org"
                except (OSError, ValueError, KeyError) as error:
                    print("snapshot archive: %s %s: %s" % (source, version, error), file=sys.stderr)
            if got and any(n.endswith(".dsc") for n in os.listdir(folder)):
                final = os.path.join(out, source)
                os.makedirs(final, exist_ok=True)
                for name in os.listdir(folder):
                    os.replace(os.path.join(folder, name), os.path.join(final, name))
                print("%-40s %-40s %s" % (source, version, how), flush=True)
            else:
                missing.append((source, version))
                print("%-40s %-40s NOT FOUND" % (source, version), flush=True)
            shutil.rmtree(folder, ignore_errors=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    shutil.copy2(os.path.join(packages_dir, "packages.tsv"), os.path.join(out, "packages.tsv"))
    note = ""
    if missing:
        with open(os.path.join(out, "MISSING.txt"), "w", encoding="utf-8") as f:
            f.writelines("%s\t%s\n" % m for m in missing)
        note = " %d could not be found (MISSING.txt)." % len(missing)
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as f:
        f.write(README % (len(pairs) - len(missing), note))
    return missing


def main(argv):
    if len(argv) != 2:
        raise SystemExit(__doc__.split("\n\n")[1])
    missing = fetch(argv[0], argv[1])
    if missing:
        print("::warning::%d source packages could not be found: %s" % (
            len(missing), ", ".join("%s %s" % m for m in missing[:20])))
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
