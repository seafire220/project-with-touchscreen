#!/usr/bin/env python3
"""Make signed software updates for sold devices (docs/32-updates.md). Run on your own computer.

    python3 device/release.py keygen [--folder ~/companion-signing]
    python3 device/release.py build --version 2026.11.21 --stage-binary PATH --key ~/companion-signing/update-key-private.pem
                                    [--notes "What changed"] [--out dist] [--min-version V]
                                    [--requirements FILE --wheels DIR] [--models DIR] [--any-arch]

keygen makes the key pair updates are signed with. The private key (update-key-private.pem) is the one
thing that lets anyone update every device you have sold: keep it off the repository, with a backup
somewhere safe (a password manager, an encrypted USB stick). The public key is copied to
device/config/update-key.pem, which goes into every device image and update.

build makes `companion-<version>.update` (the new software, its manifest and your signature) and
`latest.json` (what devices read to learn there is an update) in OUT. Put both on the update address
(device/config/update.json), latest.json last. The stage program must be the 64-bit ARM build
(stage/README.md); --any-arch skips that check, for tests only.
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_KEY = os.path.join(REPO, "device", "config", "update-key.pem")
SYSTEM_FILES = {
    "companion-core.service": "device/systemd/companion-core.service",
    "companion-stage.service": "device/systemd/companion-stage.service",
    "companion-update.service": "device/systemd/companion-update.service",
    "companion-update.path": "device/systemd/companion-update.path",
    "companion-update-boot.service": "device/systemd/companion-update-boot.service",
    "50-companion.rules": "device/config/polkit-companion.rules",
    "companion-update.py": "device/updater/companion-update.py",
}


def openssl(*args, **kwargs):
    done = subprocess.run(["openssl"] + list(args), capture_output=True, **kwargs)
    if done.returncode != 0:
        raise SystemExit("openssl failed: %s" % done.stderr.decode(errors="replace").strip())
    return done.stdout


def keygen(folder, public_key=PUBLIC_KEY):
    folder = os.path.expanduser(folder)
    private = os.path.join(folder, "update-key-private.pem")
    if os.path.exists(private):
        raise SystemExit("%s already exists; a new key would lock out every device made with the old one" % private)
    os.makedirs(folder, exist_ok=True)
    os.chmod(folder, 0o700)
    old = os.umask(0o077)
    try:
        openssl("genpkey", "-algorithm", "ed25519", "-out", private)
    finally:
        os.umask(old)
    public = openssl("pkey", "-in", private, "-pubout")
    with open(os.path.join(folder, "update-key.pem"), "wb") as f:
        f.write(public)
    os.makedirs(os.path.dirname(public_key), exist_ok=True)
    with open(public_key, "wb") as f:
        f.write(public)
    print("Private key: %s  (keep it secret, back it up, never commit it)" % private)
    print("Public key:  %s  (commit this; every image and update carries it)" % public_key)
    return private


def _public_of(private):
    return openssl("pkey", "-in", private, "-pubout")


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


def build(version, stage_binary, key, out, notes="", min_version="", requirements=None, wheels=None, models=None,
          any_arch=False, public_key=PUBLIC_KEY):
    """Write OUT/companion-<version>.update and OUT/latest.json. Returns the update's path."""
    if not os.path.isfile(public_key):
        raise SystemExit("no public key at %s: run `release.py keygen` first" % public_key)
    with open(public_key, "rb") as f:
        if f.read().strip() != _public_of(key).strip():
            raise SystemExit("the private key does not match device/config/update-key.pem: devices would refuse "
                             "this update")
    if not os.path.isfile(stage_binary) or (not any_arch and not _is_arm64(stage_binary)):
        raise SystemExit("the stage program must be the 64-bit ARM build (stage/README.md)")
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as tar:
        _add_tree(tar, os.path.join(REPO, "core"), "core")
        _add(tar, "core/companion/VERSION", (version + "\n").encode())
        with open(stage_binary, "rb") as f:
            _add(tar, "bin/stage", f.read(), 0o755)
        vrma = os.path.join(REPO, "stage", "motions", "vrma")
        for name in sorted(os.listdir(vrma)):
            if name.endswith(".vrma"):
                with open(os.path.join(vrma, name), "rb") as f:
                    _add(tar, "share/vrma/" + name, f.read())
        with open(public_key, "rb") as f:
            _add(tar, "share/update-key.pem", f.read())
        with open(os.path.join(REPO, "device", "config", "update.json"), "rb") as f:
            _add(tar, "share/update.json", f.read())
        third_party = os.path.join(REPO, "THIRD_PARTY.md")
        if os.path.isfile(third_party):
            with open(third_party, "rb") as f:
                _add(tar, "share/THIRD_PARTY.md", f.read())
        for name, source in SYSTEM_FILES.items():
            with open(os.path.join(REPO, source), "rb") as f:
                _add(tar, "system/" + name, f.read(), 0o755 if name.endswith(".py") else 0o644)
        if requirements:
            with open(requirements, "rb") as f:
                _add(tar, "requirements.txt", f.read())
            _add_tree(tar, wheels, "wheels", skip=())
        if models:
            _add_tree(tar, models, "models", skip=())
    payload_bytes = payload.getvalue()
    manifest = {"format": 1, "product": "companion", "version": version, "min_version": min_version or "",
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "notes": notes,
                "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(), "payload_size": len(payload_bytes)}
    manifest_bytes = json.dumps(manifest, indent=1).encode()
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "manifest.json"), "wb") as f:
            f.write(manifest_bytes)
        openssl("pkeyutl", "-sign", "-inkey", key, "-rawin", "-in", os.path.join(d, "manifest.json"),
                "-out", os.path.join(d, "manifest.sig"))
        with open(os.path.join(d, "manifest.sig"), "rb") as f:
            signature = f.read()
    os.makedirs(out, exist_ok=True)
    name = "companion-%s.update" % version
    path = os.path.join(out, name)
    with tarfile.open(path, "w:") as tar:
        _add(tar, "manifest.json", manifest_bytes)
        _add(tar, "manifest.sig", signature)
        _add(tar, "payload.tar.gz", payload_bytes)
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    latest = {"version": version, "url": name, "sha256": digest, "size": os.path.getsize(path), "notes": notes}
    with open(os.path.join(out, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, indent=1)
    print("Made %s (%.1f MB) and latest.json in %s" % (name, os.path.getsize(path) / 1e6, out))
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--folder", default="~/companion-signing")
    b = sub.add_parser("build")
    b.add_argument("--version", required=True)
    b.add_argument("--stage-binary", required=True)
    b.add_argument("--key", required=True)
    b.add_argument("--notes", default="")
    b.add_argument("--out", default="dist")
    b.add_argument("--min-version", default="")
    b.add_argument("--requirements")
    b.add_argument("--wheels")
    b.add_argument("--models")
    b.add_argument("--any-arch", action="store_true")
    args = parser.parse_args(argv)
    if shutil.which("openssl") is None:
        raise SystemExit("openssl is needed")
    if args.command == "keygen":
        keygen(args.folder)
    else:
        if bool(args.requirements) != bool(args.wheels):
            raise SystemExit("--requirements and --wheels go together")
        build(args.version, args.stage_binary, os.path.expanduser(args.key), args.out, args.notes, args.min_version,
              args.requirements, args.wheels, args.models, args.any_arch)


if __name__ == "__main__":
    sys.exit(main())
