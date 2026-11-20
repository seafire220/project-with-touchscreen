#!/usr/bin/python3
"""Install a software update, or go back to the version before (docs/32-updates.md).

Run as root by systemd (companion-update.service) when the device's service asks, by writing
/var/lib/companion/updates/request.json (and with --boot at each start, by companion-update-boot.service,
to finish or undo an update the power cut short):

    {"do": "install", "bundle": "/var/lib/companion/updates/companion-2026.11.21.update"}
    {"do": "rollback"}

The service that asks runs unprivileged, so nothing it says is trusted: the update's signature and
contents are checked again here, with the key in the installed software. Each version lives in
/opt/companion/releases/<version>; `current` and `previous` point at two of them, and `core`, `bin`
and `share` point into `current`. Installing puts the new version beside the running one, switches
`current` to it, restarts the services and waits for the new version to answer; if it does not, it
switches back. Characters, memories, keys and settings (in /var/lib/companion) are never touched.

On a device whose system partition is read-only (so a power cut cannot damage it: docs/33-finishing.md),
the partition is made writable just while an update changes it, and read-only again after.

Only Python's own library and the openssl program are used, so an update that breaks the device's
Python packages cannot break the updater. Paths can be moved for testing with COMPANION_APP,
COMPANION_DATA, COMPANION_ETC, COMPANION_SYSTEMCTL and COMPANION_HEALTH.
"""
import contextlib
import hashlib
import json
import os
import pwd
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

APP = os.environ.get("COMPANION_APP", "/opt/companion")
DATA = os.environ.get("COMPANION_DATA", "/var/lib/companion")
ETC = os.environ.get("COMPANION_ETC", "/")
SYSTEMCTL = os.environ.get("COMPANION_SYSTEMCTL", "systemctl")
HEALTH = os.environ.get("COMPANION_HEALTH", "http://127.0.0.1:80/api/health")
HEALTH_WAIT = float(os.environ.get("COMPANION_HEALTH_WAIT", "150"))
STAGE_WATCH = float(os.environ.get("COMPANION_STAGE_WATCH", "20"))
MOUNT = os.environ.get("COMPANION_MOUNT", "mount")
UPDATES = os.path.join(DATA, "updates")
SERVICES = ("companion-core", "companion-stage")
# The system files a version may carry, and where they go.
SYSTEM_FILES = {
    "companion-core.service": "etc/systemd/system/companion-core.service",
    "companion-stage.service": "etc/systemd/system/companion-stage.service",
    "companion-update.service": "etc/systemd/system/companion-update.service",
    "companion-update.path": "etc/systemd/system/companion-update.path",
    "companion-update-boot.service": "etc/systemd/system/companion-update-boot.service",
    "50-companion.rules": "etc/polkit-1/rules.d/50-companion.rules",
    "companion-usb.service": "etc/systemd/system/companion-usb.service",
    "companion-usb-dhcp.service": "etc/systemd/system/companion-usb-dhcp.service",
    "99-companion-backlight.rules": "etc/udev/rules.d/99-companion-backlight.rules",
    # NetworkManager reads only connection files that nobody but root can read (see below).
    "companion-usb.nmconnection": "usr/lib/NetworkManager/system-connections/companion-usb.nmconnection",
    # Power-cut protection's own units (installed by images built with it).
    "companion-var-dirs.service": "etc/systemd/system/companion-var-dirs.service",
    "companion-data-check.service": "etc/systemd/system/companion-data-check.service",
    "companion-firstboot.service": "etc/systemd/system/companion-firstboot.service",
}
MAX_UPDATE = 700 * 1024 * 1024


def log(message):
    print(message, flush=True)


def version_key(version):
    parts = []
    for piece in str(version or "0").replace("-", ".").replace("+", ".").split("."):
        parts.append(int(piece) if piece.isdigit() else 0)
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def installed_version():
    try:
        with open(os.path.join(APP, "core", "companion", "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "0"
    except OSError:
        return "0"


def set_status(state, **more):
    """What happened, for the settings page (written where the device's service can read it)."""
    os.makedirs(UPDATES, exist_ok=True)
    status = dict(more, state=state, time=int(time.time()))
    path = os.path.join(UPDATES, "status.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(status, f)
    os.replace(path + ".tmp", path)
    _give_to_service(path)
    log("%s: %s" % (state, more.get("message", "")))


def _give_to_service(path):
    try:
        user = pwd.getpwnam("companion")
        os.chown(path, user.pw_uid, user.pw_gid)
    except (KeyError, PermissionError, OSError):
        pass


# ----- checking an update
def verify(bundle):
    """The update's manifest, after checking everything; raises ValueError saying why not."""
    real = os.path.realpath(bundle)
    if os.path.dirname(real) != os.path.realpath(UPDATES) or not real.endswith(".update"):
        raise ValueError("the update is not where updates are kept")
    if os.path.islink(bundle) or not os.path.isfile(real) or os.path.getsize(real) > MAX_UPDATE:
        raise ValueError("the update file is missing or too large")
    key = os.path.join(APP, "share", "update-key.pem")
    if not os.path.isfile(key):
        raise ValueError("this software has no key to check updates with")
    with tarfile.open(real, "r:") as archive:
        members = {m.name: m for m in archive.getmembers()}
        if set(members) != {"manifest.json", "manifest.sig", "payload.tar.gz"} or \
                not all(m.isfile() for m in members.values()):
            raise ValueError("the update file is not laid out as an update")
        manifest_bytes = archive.extractfile(members["manifest.json"]).read(65536)
        signature = archive.extractfile(members["manifest.sig"]).read(1024)
        with tempfile.TemporaryDirectory() as d:
            for name, data in (("m", manifest_bytes), ("s", signature)):
                with open(os.path.join(d, name), "wb") as f:
                    f.write(data)
            done = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", key, "-rawin",
                                   "-in", os.path.join(d, "m"), "-sigfile", os.path.join(d, "s")],
                                  capture_output=True, timeout=60)
        if done.returncode != 0:
            raise ValueError("the update is not signed by this device's maker")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        if manifest.get("product") != "companion" or manifest.get("format") != 1:
            raise ValueError("the update is not for this device")
        if version_key(manifest.get("version")) <= version_key(installed_version()):
            raise ValueError("the update is not newer than the installed software")
        digest = hashlib.sha256()
        payload = archive.extractfile(members["payload.tar.gz"])
        for chunk in iter(lambda: payload.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != manifest.get("payload_sha256"):
            raise ValueError("the update's contents do not match its signature")
    return manifest


def unpack(bundle, target):
    """The payload into `target`, refusing anything that would land outside it."""
    with tarfile.open(bundle, "r:") as archive:
        payload = archive.extractfile("payload.tar.gz")
        with tempfile.TemporaryFile() as tmp:
            shutil.copyfileobj(payload, tmp)
            tmp.seek(0)
            with tarfile.open(fileobj=tmp, mode="r:gz") as inner:
                for member in inner.getmembers():
                    name = member.name
                    if name.startswith("/") or ".." in name.split("/") or member.isdev() or \
                            (member.issym() or member.islnk()):
                        raise ValueError("the update holds an unsafe path (%s)" % name)
                if hasattr(tarfile, "data_filter"):
                    inner.extractall(target, filter="data")
                else:
                    inner.extractall(target)
    if not os.path.isfile(os.path.join(target, "core", "companion", "__main__.py")):
        raise ValueError("the update has no core service in it")
    stage = os.path.join(target, "bin", "stage")
    if not os.path.isfile(stage):
        raise ValueError("the update has no stage program in it")
    os.chmod(stage, 0o755)


# ----- the layout of versions
def link(path, target):
    """Point `path` at `target`, replacing what was there in one step."""
    tmp = path + ".new-link"
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(target, tmp)
    os.replace(tmp, path)


def ensure_layout():
    """Software installed before updates existed (core, bin and share as plain folders) becomes the
    first version under releases/."""
    os.makedirs(os.path.join(APP, "releases"), exist_ok=True)
    if os.path.islink(os.path.join(APP, "current")):
        return
    version = installed_version()
    release = os.path.join(APP, "releases", version)
    os.makedirs(release, exist_ok=True)
    for part in ("core", "bin", "share"):
        here = os.path.join(APP, part)
        if os.path.isdir(here) and not os.path.islink(here):
            os.rename(here, os.path.join(release, part))
    link(os.path.join(APP, "current"), os.path.join("releases", version))
    for part in ("core", "bin", "share"):
        link(os.path.join(APP, part), os.path.join("current", part))


def release_of(name):
    path = os.path.join(APP, name)
    return os.path.realpath(path) if os.path.islink(path) else None


def install_system_files(release):
    """The version's own system files (services, permissions, the updater), where they belong."""
    folder = os.path.join(release, "system")
    changed = False
    if os.path.isdir(folder):
        for name, destination in SYSTEM_FILES.items():
            source = os.path.join(folder, name)
            if not os.path.isfile(source):
                continue
            target = os.path.join(ETC, destination)
            if os.path.isfile(target) and _same(source, target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(source, target + ".new")
            os.chmod(target + ".new", 0o600 if name.endswith(".nmconnection") else 0o644)
            os.replace(target + ".new", target)
            changed = True
        updater = os.path.join(folder, "companion-update.py")
        if os.path.isfile(updater):
            own = os.path.join(APP, "updater", "companion-update.py")
            os.makedirs(os.path.dirname(own), exist_ok=True)
            if not (os.path.isfile(own) and _same(updater, own)):
                shutil.copyfile(updater, own + ".new")
                os.chmod(own + ".new", 0o755)
                os.replace(own + ".new", own)
    if changed:
        systemctl("daemon-reload")


def _same(a, b):
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read() == fb.read()


def install_wheels(release):
    """Python packages the version needs, from wheels it carries (never from the internet)."""
    requirements = os.path.join(release, "requirements.txt")
    wheels = os.path.join(release, "wheels")
    if not (os.path.isfile(requirements) and os.path.isdir(wheels)):
        return
    pip = os.path.join(APP, "venv", "bin", "pip")
    done = subprocess.run([pip, "install", "--no-index", "--find-links", wheels, "-r", requirements],
                          capture_output=True, text=True, timeout=1800)
    if done.returncode != 0:
        raise ValueError("its Python packages did not install: %s" % done.stderr.strip()[-300:])


def install_models(release):
    """Models a version brings (models/<name>), for devices made before it needed them: put where the
    device keeps its models, if not there already, and given to the service's user."""
    folder = os.path.join(release, "models")
    if not os.path.isdir(folder):
        return
    target_root = os.path.join(DATA, "models")
    os.makedirs(target_root, exist_ok=True)
    for name in sorted(os.listdir(folder)):
        source, target = os.path.join(folder, name), os.path.join(target_root, name)
        if os.path.isdir(source) and not os.path.exists(target):
            shutil.copytree(source, target + ".new")
            os.replace(target + ".new", target)
            for root, dirs, files in os.walk(target):
                for item in [root] + [os.path.join(root, f) for f in files]:
                    _give_to_service(item)
    shutil.rmtree(folder, ignore_errors=True)             # kept once, in the data folder


def systemctl(*args):
    return subprocess.run([SYSTEMCTL] + list(args), capture_output=True, text=True, timeout=120)


def switch_to(release):
    """Make `release` the running version: its system files, `current`, the services restarted."""
    install_system_files(release)
    link(os.path.join(APP, "current"), os.path.relpath(release, APP))
    for part in ("core", "bin", "share"):
        if not os.path.islink(os.path.join(APP, part)):
            link(os.path.join(APP, part), os.path.join("current", part))
    systemctl("restart", *SERVICES)


def healthy(version):
    """Whether the version answers: the core says it is that version, and the screen program stays up."""
    deadline = time.time() + HEALTH_WAIT
    answered = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
            if data.get("ok") and data.get("version") == version:
                answered = True
                break
        except Exception:
            pass
        time.sleep(2)
    if not answered:
        return False, "the new version's service did not answer"
    before = _restarts("companion-stage")
    time.sleep(STAGE_WATCH)
    after = _restarts("companion-stage")
    active = systemctl("is-active", "companion-stage").stdout.strip()
    if active != "active" or after - before > 1:
        return False, "the new version's screen program kept stopping"
    return True, ""


def _restarts(unit):
    out = systemctl("show", "-p", "NRestarts", "--value", unit).stdout.strip()
    return int(out) if out.isdigit() else 0


def prune(keep):
    """Remove versions other than those kept (the running one and the one before)."""
    folder = os.path.join(APP, "releases")
    keep = {os.path.realpath(k) for k in keep if k}
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.realpath(path) not in keep and os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def _read_only(path="/", mounts="/proc/mounts"):
    """Whether the file system mounted at `path` is mounted read-only."""
    read_only = False
    try:
        with open(mounts, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[1] == path:
                    read_only = "ro" in parts[3].split(",")      # the last mount there counts
    except OSError:
        pass
    return read_only


@contextlib.contextmanager
def system_writable():
    """The system partition writable while an update changes it, if it is read-only, and read-only again
    after. (Only for the real system: tests move ETC elsewhere.)"""
    was = ETC == "/" and _read_only("/")
    if was:
        subprocess.run([MOUNT, "-o", "remount,rw", "/"], check=True)
        log("made the system partition writable for the update")
    try:
        yield
    finally:
        if was:
            os.sync()
            if subprocess.run([MOUNT, "-o", "remount,ro", "/"]).returncode == 0:
                log("the system partition is read-only again")
            else:
                log("the system partition stays writable until the next start")


# ----- what is asked
def install(request):
    bundle = request.get("bundle", "")
    try:
        manifest = verify(bundle)
    except Exception as error:
        set_status("failed", message="the update was refused: %s" % error)
        return 1
    version, before = manifest["version"], installed_version()
    set_status("installing", version=version, previous=before, previous_release=release_of("current") or "")
    release = os.path.join(APP, "releases", version)
    staging = release + ".new"
    try:
        ensure_layout()
        old = release_of("current")
        for path in (staging, release):
            if os.path.isdir(path) and os.path.realpath(path) != old:
                shutil.rmtree(path)
        os.makedirs(staging)
        unpack(bundle, staging)
        install_wheels(staging)
        install_models(staging)
        os.rename(staging, release)
    except Exception as error:
        shutil.rmtree(staging, ignore_errors=True)
        set_status("failed", version=version, message="the update could not be installed: %s" % error)
        return 1
    switch_to(release)
    ok, why = healthy(version)
    if ok:
        if old:
            link(os.path.join(APP, "previous"), os.path.relpath(old, APP))
        prune([release, old])
        _remove(bundle)
        set_status("installed", version=version, previous=before,
                   message="Updated from %s to %s." % (before, version))
        return 0
    if old:
        switch_to(old)
    set_status("rolled back", version=version, previous=before,
               message="Version %s did not start properly (%s), so the device went back to %s." % (version, why, before))
    return 1


def rollback():
    previous, current = release_of("previous"), release_of("current")
    if not previous or not os.path.isdir(previous):
        set_status("failed", message="there is no earlier version to go back to")
        return 1
    with open(os.path.join(previous, "core", "companion", "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()
    switch_to(previous)
    ok, why = healthy(version)
    if not ok:
        switch_to(current)
        set_status("failed", message="the earlier version did not start properly (%s); kept this one" % why)
        return 1
    link(os.path.join(APP, "previous"), os.path.relpath(current, APP))
    set_status("installed", version=version, message="Went back to version %s." % version)
    return 0


def _interrupted():
    """Whether an update was under way when the device stopped (most starts: no)."""
    try:
        with open(os.path.join(UPDATES, "status.json"), encoding="utf-8") as f:
            return json.load(f).get("state") == "installing"
    except (OSError, ValueError, AttributeError):
        return False


def after_boot():
    """At start: an update the power cut short is finished (if the new version answers) or undone."""
    try:
        with open(os.path.join(UPDATES, "status.json"), encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, ValueError):
        return 0
    if status.get("state") != "installing":
        return 0
    version, before = status.get("version", ""), status.get("previous", "")
    old = status.get("previous_release") or ""
    if installed_version() != version:
        set_status("failed", version=version, previous=before,
                   message="The update to %s was cut short (the power went off?), so the device kept %s." % (version, before))
        return 0
    ok, why = healthy(version)
    if ok:
        if old and os.path.isdir(old):
            link(os.path.join(APP, "previous"), os.path.relpath(old, APP))
        prune([release_of("current"), old])
        set_status("installed", version=version, previous=before, message="Updated from %s to %s." % (before, version))
        return 0
    if old and os.path.isdir(old):
        switch_to(old)
    set_status("rolled back", version=version, previous=before,
               message="Version %s did not start properly (%s), so the device went back to %s." % (version, why, before))
    return 1


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def main():
    if "--boot" in sys.argv[1:]:
        if not _interrupted():
            return 0
        with system_writable():
            return after_boot()
    request_path = os.path.join(UPDATES, "request.json")
    taken = request_path + ".taken"
    try:
        os.replace(request_path, taken)          # taken at once, so the request cannot start this twice
    except OSError:
        return 0
    try:
        with open(taken, encoding="utf-8") as f:
            request = json.load(f)
    except (OSError, ValueError):
        request = {}
    finally:
        _remove(taken)
    if request.get("do") == "install":
        with system_writable():
            return install(request)
    if request.get("do") == "rollback":
        with system_writable():
            return rollback()
    set_status("failed", message="an update request that was not understood")
    return 1


if __name__ == "__main__":
    sys.exit(main())
