"""Software updates: checking for one, downloading it, checking its signature, and asking for it to be
installed (docs/32-updates.md).

An update is one file, `companion-<version>.update`: a tar holding `manifest.json`, `manifest.sig` (the
owner's Ed25519 signature of the manifest) and `payload.tar.gz` (the new software). The manifest names
the payload's SHA-256, so a signed manifest vouches for the whole update. The public half of the key is
part of the device's software (`share/update-key.pem`); the private half never leaves the owner.

This side runs as the service's own unprivileged user and cannot change the software. It finds updates
(at the address in `share/update.json`, or one the owner uploads), checks them, and asks the installer
(`device/updater/companion-update.py`, run as root by systemd when a request appears) to install one.
The installer checks the signature again itself, installs beside the running version, restarts, and
goes back if the new version does not answer.
"""
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
import time
import urllib.parse

from .store import write_atomic

APP = os.environ.get("COMPANION_APP", "/opt/companion")
PRODUCT = "companion"
MAX_UPDATE = 700 * 1024 * 1024        # bytes in one update file
MAX_MANIFEST = 64 * 1024
CHECK_TIMEOUT = 20
DOWNLOAD_TIMEOUT = 30 * 60


class UpdateError(Exception):
    pass


def current_version():
    """This software's version ("2026.11.21"); "0" for a development copy."""
    path = os.path.join(os.path.dirname(__file__), "VERSION")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or "0"
    except OSError:
        return "0"


def version_key(version):
    """A version as numbers to compare: "2026.11.21.2" -> (2026, 11, 21, 2); anything else counts as 0."""
    parts = []
    for piece in re.split(r"[.\-+]", str(version or "0")):
        parts.append(int(piece) if piece.isdigit() else 0)
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def newer(version, than):
    return version_key(version) > version_key(than)


def channel(app=APP):
    """Where to look for updates and with which key: {"url", "key"}; either may be missing."""
    share = os.path.join(app, "share")
    out = {"url": "", "key": ""}
    try:
        with open(os.path.join(share, "update.json"), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("url"), str):
            out["url"] = data["url"].strip()
    except (OSError, ValueError):
        pass
    key = os.path.join(share, "update-key.pem")
    if os.path.isfile(key):
        out["key"] = key
    return out


def verify_signature(data, signature, key_path):
    """Whether `signature` is the key's Ed25519 signature of `data` (OpenSSL does the checking)."""
    if not key_path or not os.path.isfile(key_path) or not signature:
        return False
    with tempfile.TemporaryDirectory() as d:
        message, sig = os.path.join(d, "message"), os.path.join(d, "signature")
        with open(message, "wb") as f:
            f.write(data)
        with open(sig, "wb") as f:
            f.write(signature)
        try:
            done = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", key_path, "-rawin",
                                   "-in", message, "-sigfile", sig], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return done.returncode == 0


def read_update(path, key_path, installed=None):
    """Check an update file: its manifest signed by the key, its payload the one the manifest names, for
    this product and newer than what is installed. Returns the manifest. Raises UpdateError saying why."""
    installed = installed or current_version()
    try:
        size = os.path.getsize(path)
    except OSError:
        raise UpdateError("the update file is missing")
    if size > MAX_UPDATE:
        raise UpdateError("the update file is too large")
    try:
        archive = tarfile.open(path, "r:")
    except (tarfile.TarError, OSError):
        raise UpdateError("this is not an update file")
    with archive:
        members = {}
        for info in archive.getmembers():
            if info.name not in ("manifest.json", "manifest.sig", "payload.tar.gz") or not info.isfile():
                raise UpdateError("the update file holds something it should not (%s)" % info.name)
            members[info.name] = info
        if set(members) != {"manifest.json", "manifest.sig", "payload.tar.gz"}:
            raise UpdateError("the update file is incomplete")
        if members["manifest.json"].size > MAX_MANIFEST or members["manifest.sig"].size > 1024:
            raise UpdateError("the update file is not laid out as an update")
        manifest_bytes = archive.extractfile(members["manifest.json"]).read()
        signature = archive.extractfile(members["manifest.sig"]).read()
        if not verify_signature(manifest_bytes, signature, key_path):
            raise UpdateError("the update is not signed by this device's maker; it was refused")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise UpdateError("the update's description cannot be read")
        if not isinstance(manifest, dict) or manifest.get("product") != PRODUCT or manifest.get("format") != 1:
            raise UpdateError("the update is not for this device")
        version = str(manifest.get("version", ""))
        if not version_key(version) or not newer(version, installed):
            raise UpdateError("the update (%s) is not newer than this software (%s)" % (version or "?", installed))
        if manifest.get("min_version") and newer(manifest["min_version"], installed):
            raise UpdateError("this update needs version %s or later installed first" % manifest["min_version"])
        digest = hashlib.sha256()
        payload = archive.extractfile(members["payload.tar.gz"])
        for chunk in iter(lambda: payload.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != manifest.get("payload_sha256"):
            raise UpdateError("the update's contents do not match its signed description; it was refused")
    return manifest


class Updates:
    """The device's side of updates, keeping its files in DATA/updates."""

    def __init__(self, data_dir, app=APP):
        self.folder = os.path.join(data_dir, "updates")
        self.app = app
        os.makedirs(self.folder, exist_ok=True)
        self.state_path = os.path.join(self.folder, "state.json")

    # ----- what is known
    def _state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                state = json.load(f)
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, **changes):
        state = self._state()
        state.update(changes)
        write_atomic(self.state_path, json.dumps(state))
        return state

    def installer_status(self):
        """What the installer last did ({"state": "installed" | "rolled back" | "failed" | "installing", ...})."""
        try:
            with open(os.path.join(self.folder, "status.json"), encoding="utf-8") as f:
                status = json.load(f)
            return status if isinstance(status, dict) else {}
        except (OSError, ValueError):
            return {}

    def status(self):
        state = self._state()
        ready = state.get("ready")
        if ready and not (os.path.isfile(ready.get("path", "")) and newer(ready.get("version"), current_version())):
            ready = None
        found = state.get("found")
        if found and not newer(found.get("version"), current_version()):
            found = None
        where = channel(self.app)
        return {"version": current_version(), "can_update": bool(where["key"]), "online": bool(where["url"] and where["key"]),
                "checked": state.get("checked"), "found": found, "ready": ready and {k: ready[k] for k in ("version", "notes")},
                "error": state.get("error"), "installer": self.installer_status(),
                "previous": os.path.islink(os.path.join(self.app, "previous"))}

    # ----- finding and fetching
    async def check(self, session=None):
        """Ask the update address for the latest version. Returns what was found (or None if up to date)."""
        where = channel(self.app)
        if not where["url"] or not where["key"]:
            raise UpdateError("this software has no update address set")
        import aiohttp
        own = session is None
        session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=CHECK_TIMEOUT))
        try:
            async with session.get(where["url"]) as r:
                if r.status != 200:
                    raise UpdateError("the update address answered %d" % r.status)
                text = await r.text()
        except UpdateError:
            raise
        except Exception as error:
            raise UpdateError("the update address could not be reached (%s)" % type(error).__name__)
        finally:
            if own:
                await session.close()
        try:
            latest = json.loads(text)
            version, url = str(latest["version"]), str(latest["url"])
        except (ValueError, KeyError, TypeError):
            raise UpdateError("the update address did not describe an update")
        found = None
        if newer(version, current_version()):
            found = {"version": version, "url": urllib.parse.urljoin(where["url"], url),
                     "sha256": str(latest.get("sha256", "")), "size": int(latest.get("size") or 0),
                     "notes": str(latest.get("notes", ""))[:2000]}
        self._save(checked=int(time.time()), found=found, error=None)
        return found

    async def download(self, found, session=None):
        """Fetch a found update and check it. Returns its manifest; it is then ready to install."""
        if found.get("size") and found["size"] > MAX_UPDATE:
            raise UpdateError("the update is too large")
        import aiohttp
        part = os.path.join(self.folder, "download.part")
        own = session is None
        session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT))
        digest, size = hashlib.sha256(), 0
        try:
            async with session.get(found["url"]) as r:
                if r.status != 200:
                    raise UpdateError("the update could not be downloaded (%d)" % r.status)
                with open(part, "wb") as f:
                    async for chunk in r.content.iter_chunked(256 * 1024):
                        size += len(chunk)
                        if size > MAX_UPDATE:
                            raise UpdateError("the update is too large")
                        digest.update(chunk)
                        f.write(chunk)
        except UpdateError:
            _remove(part)
            raise
        except Exception as error:
            _remove(part)
            raise UpdateError("the download failed (%s)" % type(error).__name__)
        finally:
            if own:
                await session.close()
        if found.get("sha256") and digest.hexdigest() != found["sha256"]:
            _remove(part)
            raise UpdateError("the downloaded update is damaged")
        return self.accept(part)

    def accept(self, path):
        """Check an update file (downloaded, or uploaded by the owner) and keep it, ready to install.
        Returns its manifest. Raises UpdateError (and removes the file) if it is not a good update."""
        try:
            manifest = read_update(path, channel(self.app)["key"])
        except UpdateError as error:
            _remove(path)
            self._save(error=str(error))
            raise
        target = os.path.join(self.folder, "companion-%s.update" % re.sub(r"[^0-9A-Za-z.\-]", "", manifest["version"]))
        for name in os.listdir(self.folder):                   # one waiting update at a time
            if name.endswith(".update") and os.path.join(self.folder, name) != target:
                _remove(os.path.join(self.folder, name))
        os.replace(path, target)
        self._save(ready={"path": target, "version": manifest["version"], "notes": str(manifest.get("notes", ""))[:2000]},
                   error=None)
        return manifest

    # ----- asking the installer
    def request_install(self):
        """Ask the installer to install the update that is ready. Returns its version."""
        ready = self._state().get("ready")
        if not ready or not os.path.isfile(ready.get("path", "")):
            raise UpdateError("no update is ready to install")
        self._request({"do": "install", "bundle": ready["path"], "version": ready["version"]})
        return ready["version"]

    def request_rollback(self):
        if not os.path.islink(os.path.join(self.app, "previous")):
            raise UpdateError("there is no earlier version to go back to")
        self._request({"do": "rollback"})

    def _request(self, request):
        request["asked"] = int(time.time())
        write_atomic(os.path.join(self.folder, "request.json"), json.dumps(request))


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
