#!/usr/bin/env python3
"""Make signed software updates for sold devices (docs/32-updates.md). Run on your own computer.

    python3 device/release.py keygen
    python3 device/release.py check
    python3 device/release.py sign companion-2026.12.1.unsigned.update
    python3 device/release.py build --version 2026.12.1 --stage-binary PATH [--notes "What changed"]

keygen makes the key pair updates are signed with, in ~/companion-signing. The private key
(update-key-private.pem) is the one thing that lets anyone update every device you have sold: keep it
off the repository, with a backup somewhere safe (a password manager, an encrypted USB stick). The
public key is copied to device/config/update-key.pem, which goes into every device image and update.
The key files are plain text; you never need to open them.

check says whether your private key matches the public key in this copy of the project (so devices
made from it will accept what you sign), and where devices look for updates.

sign signs an update built without a key: the "Make an update" workflow on GitHub builds one (an
.unsigned.update file), or `build --unsigned` does. It writes `companion-<version>.update` and
`latest.json` beside it (or in --out). Publish both: a new release of your update repository, with the
two files attached.

build makes the update here, from this copy of the project, and signs it unless --unsigned is given.
The stage program must be the 64-bit ARM build (stage/README.md); --any-arch skips that check, for
tests only.

--key defaults to ~/companion-signing/update-key-private.pem. Nothing here needs OpenSSL: signing is
done in Python (device/ed25519.py), with the same result OpenSSL gives.
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ed25519  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_KEY = os.path.join(REPO, "device", "config", "update-key.pem")
UPDATE_ADDRESS = os.path.join(REPO, "device", "config", "update.json")
DEFAULT_KEY = "~/companion-signing/update-key-private.pem"
SYSTEM_FILES = {
    "companion-core.service": "device/systemd/companion-core.service",
    "companion-stage.service": "device/systemd/companion-stage.service",
    "companion-update.service": "device/systemd/companion-update.service",
    "companion-update.path": "device/systemd/companion-update.path",
    "companion-update-boot.service": "device/systemd/companion-update-boot.service",
    "50-companion.rules": "device/config/polkit-companion.rules",
    "companion-update.py": "device/updater/companion-update.py",
    "companion-usb.service": "device/systemd/companion-usb.service",
    "companion-usb-dhcp.service": "device/systemd/companion-usb-dhcp.service",
    "99-companion-backlight.rules": "device/config/99-companion-backlight.rules",
    "companion-bluetooth.conf": "device/config/companion-bluetooth.conf",
    "companion-usb.nmconnection": "device/config/companion-usb.nmconnection",
    "companion-var-dirs.service": "device/readonly/companion-var-dirs.service",
    "companion-data-check.service": "device/readonly/companion-data-check.service",
    "companion-firstboot.service": "device/readonly/companion-firstboot.service",
}


class ReleaseError(Exception):
    pass


# ----- keys

def keygen(folder="~/companion-signing", public_key=PUBLIC_KEY):
    folder = os.path.expanduser(folder)
    private = os.path.join(folder, "update-key-private.pem")
    if os.path.exists(private):
        raise ReleaseError("%s already exists; a new key would lock out every device made with the old one" % private)
    os.makedirs(folder, exist_ok=True)
    os.chmod(folder, 0o700)
    data = ed25519.new_private_key()
    fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    public = ed25519.public_pem(ed25519.public_key(ed25519.read_private_key(data)))
    with open(os.path.join(folder, "update-key.pem"), "wb") as f:
        f.write(public)
    os.makedirs(os.path.dirname(public_key), exist_ok=True)
    with open(public_key, "wb") as f:
        f.write(public)
    print("Private key: %s  (keep it secret, back it up, never commit it)" % private)
    print("Public key:  %s  (commit this; every image and update carries it)" % public_key)
    return private


def read_key(path):
    """The private key in `path` (32 bytes). Raises ReleaseError saying what is wrong."""
    path = os.path.expanduser(path)
    try:
        with open(path, "rb") as f:
            return ed25519.read_private_key(f.read())
    except FileNotFoundError:
        raise ReleaseError("there is no private key at %s (give its place with --key)" % path)
    except OSError as error:
        raise ReleaseError("the private key at %s cannot be read (%s)" % (path, error))
    except ValueError as error:
        raise ReleaseError("%s: %s" % (path, error))


def read_public(path=PUBLIC_KEY):
    try:
        with open(path, "rb") as f:
            return ed25519.read_public_key(f.read())
    except FileNotFoundError:
        raise ReleaseError("there is no public key at %s: run `release.py keygen` first" % path)
    except ValueError as error:
        raise ReleaseError("%s: %s" % (path, error))


def update_address(path=UPDATE_ADDRESS):
    try:
        with open(path, encoding="utf-8") as f:
            return str(json.load(f).get("url") or "").strip()
    except (OSError, ValueError, AttributeError):
        return ""


def check(key=DEFAULT_KEY, public_key=PUBLIC_KEY):
    """Say whether the private key matches the project's public key. Returns True if it does."""
    seed = read_key(key)
    mine = ed25519.public_key(seed)
    project = read_public(public_key)
    if not ed25519.verify(mine, b"check", ed25519.sign(seed, b"check")):
        raise ReleaseError("the private key does not sign correctly")
    print("Your private key:     %s  (fingerprint %s)" % (os.path.expanduser(key), ed25519.fingerprint(mine)))
    print("The project's public key: %s  (fingerprint %s)" % (os.path.relpath(public_key, REPO), ed25519.fingerprint(project)))
    if mine != project:
        print("They do NOT match: devices made from this project would refuse updates signed with this key.")
        return False
    print("They match: devices made from this project accept updates you sign with this key.")
    address = update_address()
    print("Devices look for updates at: %s" % (address or "(nowhere: device/config/update.json has no url)"))
    return True


# ----- making an update

def _add(tar, name, data, mode=0o644):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(data))


def _add_tree(tar, source, prefix, skip=("__pycache__", "tests")):
    for root, dirs, files in os.walk(source):
        dirs[:] = sorted(d for d in dirs if d not in skip and not d.startswith("."))
        for name in sorted(files):
            if name.endswith((".pyc", ".pyo")) or name.startswith("."):
                continue
            path = os.path.join(root, name)
            if os.path.islink(path):
                continue
            rel = os.path.relpath(path, source).replace(os.sep, "/")
            with open(path, "rb") as f:
                data = f.read()
            _add(tar, "%s/%s" % (prefix, rel), data, 0o755 if os.access(path, os.X_OK) else 0o644)


def _is_arm64(path):
    with open(path, "rb") as f:
        head = f.read(20)
    return head[:4] == b"\x7fELF" and head[4] == 2 and int.from_bytes(head[18:20], "little") == 183


def _commit():
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        done = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _payload(version, stage_binary, requirements=None, wheels=None, models=None, public_key=PUBLIC_KEY):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as tar:
        _add_tree(tar, os.path.join(REPO, "core"), "core")
        _add(tar, "core/companion/VERSION", (version + "\n").encode())
        with open(stage_binary, "rb") as f:
            _add(tar, "bin/stage", f.read(), 0o755)
        for program in ("usb/companion-usb-gadget", "readonly/companion-data-check", "readonly/companion-firstboot"):
            with open(os.path.join(REPO, "device", program), "rb") as f:
                _add(tar, "bin/" + os.path.basename(program), f.read(), 0o755)
        vrma = os.path.join(REPO, "stage", "motions", "vrma")
        for name in sorted(os.listdir(vrma)):
            if name.endswith(".vrma"):
                with open(os.path.join(vrma, name), "rb") as f:
                    _add(tar, "share/vrma/" + name, f.read())
        with open(public_key, "rb") as f:
            _add(tar, "share/update-key.pem", f.read())
        with open(UPDATE_ADDRESS, "rb") as f:
            _add(tar, "share/update.json", f.read())
        third_party = os.path.join(REPO, "THIRD_PARTY.md")
        if os.path.isfile(third_party):
            with open(third_party, "rb") as f:
                _add(tar, "share/THIRD_PARTY.md", f.read())
        with open(os.path.join(REPO, "stage", "THIRD_PARTY_LICENSES.txt"), "rb") as f:
            _add(tar, "share/licenses/stage.txt", f.read())
        for name, source in SYSTEM_FILES.items():
            with open(os.path.join(REPO, source), "rb") as f:
                _add(tar, "system/" + name, f.read(), 0o755 if name.endswith(".py") else 0o644)
        if requirements:
            with open(requirements, "rb") as f:
                _add(tar, "requirements.txt", f.read())
            _add_tree(tar, wheels, "wheels", skip=())
        if models:
            _add_tree(tar, models, "models", skip=())
    return payload.getvalue()


def _write_update(path, manifest_bytes, payload_bytes, signature=None):
    with tarfile.open(path, "w:") as tar:
        _add(tar, "manifest.json", manifest_bytes)
        if signature is not None:
            _add(tar, "manifest.sig", signature)
        _add(tar, "payload.tar.gz", payload_bytes)


def _latest(path, version, notes):
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    latest = {"version": version, "url": os.path.basename(path), "sha256": digest, "size": os.path.getsize(path),
              "notes": notes}
    with open(os.path.join(os.path.dirname(path), "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, indent=1)


def build(version, stage_binary, key=None, out="dist", notes="", min_version="", requirements=None, wheels=None,
          models=None, any_arch=False, public_key=PUBLIC_KEY, unsigned=False):
    """Write OUT/companion-<version>.update and OUT/latest.json (or, unsigned, OUT/companion-<version>.unsigned.update,
    to sign with `sign`). Returns the update's path."""
    project = read_public(public_key)
    seed = None
    if not unsigned:
        seed = read_key(key or DEFAULT_KEY)
        if ed25519.public_key(seed) != project:
            raise ReleaseError("the private key does not match device/config/update-key.pem: devices would refuse "
                               "this update")
    if not update_address():
        raise ReleaseError("device/config/update.json has no update address: devices given this update would stop "
                           "looking for updates")
    if not os.path.isfile(stage_binary) or (not any_arch and not _is_arm64(stage_binary)):
        raise ReleaseError("the stage program must be the 64-bit ARM build (stage/README.md)")
    if not version or not all(p.isdigit() for p in version.split(".")):
        raise ReleaseError("a version is numbers with dots, such as 2026.12.1")
    payload_bytes = _payload(version, stage_binary, requirements, wheels, models, public_key)
    manifest = {"format": 1, "product": "companion", "version": version, "min_version": min_version or "",
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "notes": notes,
                "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(), "payload_size": len(payload_bytes)}
    commit = _commit()
    if commit:
        manifest["commit"] = commit
    manifest_bytes = json.dumps(manifest, indent=1).encode()
    os.makedirs(out, exist_ok=True)
    if unsigned:
        path = os.path.join(out, "companion-%s.unsigned.update" % version)
        _write_update(path, manifest_bytes, payload_bytes)
        print("Made %s (%.1f MB). Sign it with: python3 device/release.py sign %s" % (
            os.path.basename(path), os.path.getsize(path) / 1e6, os.path.basename(path)))
        return path
    path = os.path.join(out, "companion-%s.update" % version)
    _write_update(path, manifest_bytes, payload_bytes, ed25519.sign(seed, manifest_bytes))
    _latest(path, version, notes)
    print("Made %s (%.1f MB) and latest.json in %s" % (os.path.basename(path), os.path.getsize(path) / 1e6, out))
    return path


def sign(unsigned_path, key=DEFAULT_KEY, out=None, public_key=PUBLIC_KEY):
    """Sign an update built without a key. Checks it first: its contents match its description, and it
    carries your public key and an update address (or devices would be locked out after installing it).
    Returns the signed update's path."""
    seed = read_key(key)
    public = ed25519.public_key(seed)
    try:
        archive = tarfile.open(unsigned_path, "r:")
    except (OSError, tarfile.TarError):
        raise ReleaseError("%s is not an update file" % unsigned_path)
    with archive:
        names = {m.name: m for m in archive.getmembers()}
        if set(names) - {"manifest.json", "manifest.sig", "payload.tar.gz"} or \
                not {"manifest.json", "payload.tar.gz"} <= set(names):
            raise ReleaseError("%s is not laid out as an update" % unsigned_path)
        manifest_bytes = archive.extractfile(names["manifest.json"]).read()
        payload_bytes = archive.extractfile(names["payload.tar.gz"]).read()
    try:
        manifest = json.loads(manifest_bytes)
    except ValueError:
        raise ReleaseError("the update's description cannot be read")
    if not isinstance(manifest, dict) or manifest.get("product") != "companion" or manifest.get("format") != 1:
        raise ReleaseError("this is not an update for the character device")
    if hashlib.sha256(payload_bytes).hexdigest() != manifest.get("payload_sha256"):
        raise ReleaseError("the update's contents do not match its description; it was not signed")
    try:
        with tarfile.open(fileobj=io.BytesIO(payload_bytes), mode="r:gz") as payload:
            carried_key = payload.extractfile("share/update-key.pem").read()
            carried_address = json.loads(payload.extractfile("share/update.json").read()).get("url", "")
            files = len(payload.getmembers())
    except (KeyError, AttributeError, ValueError, tarfile.TarError):
        raise ReleaseError("the update does not carry an update key and address; it was not signed")
    try:
        carried = ed25519.read_public_key(carried_key)
    except ValueError:
        raise ReleaseError("the update carries a broken update key; it was not signed")
    if carried != public:
        raise ReleaseError("the update carries a different public key (fingerprint %s) from yours (%s): devices that "
                           "installed it would refuse your later updates. It was not signed." % (
                               ed25519.fingerprint(carried), ed25519.fingerprint(public)))
    if not str(carried_address).strip():
        raise ReleaseError("the update has no update address: devices that installed it would stop looking for "
                           "updates. It was not signed.")
    if os.path.isfile(public_key) and read_public(public_key) != public:
        print("Note: this copy of the project has a different public key; the update itself carries yours.")
    version = str(manifest.get("version", ""))
    print("Version:  %s" % version)
    print("Notes:    %s" % (manifest.get("notes") or "(none)"))
    print("Built:    %s%s" % (manifest.get("created", "?"), (" from commit " + manifest["commit"][:12]) if manifest.get("commit") else ""))
    print("Contents: %d files, %.1f MB" % (files, len(payload_bytes) / 1e6))
    print("Devices will next look for updates at: %s" % carried_address)
    out = out or os.path.dirname(os.path.abspath(unsigned_path))
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "companion-%s.update" % version)
    _write_update(path, manifest_bytes, payload_bytes, ed25519.sign(seed, manifest_bytes))
    _latest(path, version, str(manifest.get("notes") or ""))
    print("Signed: %s and latest.json in %s" % (os.path.basename(path), out))
    print("Publish both as a new release of your update repository (docs/32-updates.md).")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    k = sub.add_parser("keygen", help="make your update key pair (once)")
    k.add_argument("--folder", default="~/companion-signing")
    c = sub.add_parser("check", help="check your private key matches this project")
    c.add_argument("--key", default=DEFAULT_KEY)
    s = sub.add_parser("sign", help="sign an update built without a key")
    s.add_argument("unsigned")
    s.add_argument("--key", default=DEFAULT_KEY)
    s.add_argument("--out")
    b = sub.add_parser("build", help="make an update from this copy of the project")
    b.add_argument("--version", required=True)
    b.add_argument("--stage-binary", required=True)
    b.add_argument("--key", default=DEFAULT_KEY)
    b.add_argument("--unsigned", action="store_true", help="make it without signing (sign it later with `sign`)")
    b.add_argument("--notes", default="")
    b.add_argument("--out", default="dist")
    b.add_argument("--min-version", default="")
    b.add_argument("--requirements")
    b.add_argument("--wheels")
    b.add_argument("--models")
    b.add_argument("--any-arch", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "keygen":
            keygen(args.folder)
        elif args.command == "check":
            return 0 if check(args.key) else 1
        elif args.command == "sign":
            sign(args.unsigned, args.key, args.out)
        else:
            if bool(args.requirements) != bool(args.wheels):
                raise ReleaseError("--requirements and --wheels go together")
            build(args.version, args.stage_binary, None if args.unsigned else args.key, args.out, args.notes,
                  args.min_version, args.requirements, args.wheels, args.models, args.any_arch, unsigned=args.unsigned)
    except ReleaseError as error:
        print("release.py: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
