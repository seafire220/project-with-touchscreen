"""Settings, secrets and the console password, kept in files on the device.

Settings are ordinary choices (which provider, which voice, volume). Secrets
are API keys. They live in a separate file readable only by the service
user, are never returned by the web API (only whether each is set), and are
never written to logs or character packages.
"""
import copy
import hashlib
import hmac
import json
import os
import secrets as pysecrets
import tempfile
import threading

DEFAULT_SETTINGS = {
    "llm": {"provider": "", "model": "", "base_url": "", "temperature": 0.8, "max_tokens": 400},
    "stt": {"provider": "local", "model": "", "base_url": "", "language": "en"},
    "tts": {"provider": "", "model": "", "voice": "", "base_url": ""},
    "listening": {"mode": "auto", "end_silence": 0.8, "max_turn": 30.0, "voice_interrupt": False},
    "conversation": {"history_turns": 12, "memory": True, "web_search": True},
    "active_character": "",
    "volume": 0.8,
}

# The secret names the device accepts: one key per provider.
SECRET_NAMES = ("openai", "anthropic", "openai_compatible", "elevenlabs", "groq", "openrouter", "search")


def write_atomic(path, data, mode=0o644):
    """Write a file so that a power cut leaves either the old or the new file, never half of one."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Store:
    """Everything the device remembers apart from characters and memories."""

    def __init__(self, folder):
        self.folder = folder
        self._lock = threading.Lock()
        os.makedirs(folder, exist_ok=True)
        self.settings_path = os.path.join(folder, "settings.json")
        self.secrets_path = os.path.join(folder, "secrets.json")
        self.password_path = os.path.join(folder, "console-password")

    # --- settings
    def settings(self):
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        return _merge(DEFAULT_SETTINGS, saved)

    def update_settings(self, changes):
        """Merge changes into the settings. Unknown top-level names are refused."""
        unknown = set(changes) - set(DEFAULT_SETTINGS)
        if unknown:
            raise ValueError("unknown settings: %s" % ", ".join(sorted(unknown)))
        for key, value in changes.items():
            if isinstance(DEFAULT_SETTINGS[key], dict) and not isinstance(value, dict):
                raise ValueError("%s must be an object" % key)
        with self._lock:
            merged = _merge(self.settings(), changes)
            write_atomic(self.settings_path, json.dumps(merged, indent=1))
        return merged

    # --- secrets
    def _secrets(self):
        try:
            with open(self.secrets_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def secret(self, name):
        """The key itself, for the provider adapters only."""
        return self._secrets().get(name, "")

    def secret_status(self):
        """Which keys are set, without their values."""
        saved = self._secrets()
        return {name: bool(saved.get(name)) for name in SECRET_NAMES}

    def set_secret(self, name, value):
        if name not in SECRET_NAMES:
            raise ValueError("unknown key name: %s" % name)
        value = (value or "").strip()
        if len(value) > 500 or any(c in value for c in "\r\n\0"):
            raise ValueError("that does not look like an API key")
        with self._lock:
            saved = self._secrets()
            if value:
                saved[name] = value
            else:
                saved.pop(name, None)
            write_atomic(self.secrets_path, json.dumps(saved), mode=0o600)

    # --- console password
    def has_password(self):
        return os.path.exists(self.password_path)

    def set_password(self, password):
        if len(password) < 8:
            raise ValueError("the password must be at least 8 characters")
        salt = pysecrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1)
        write_atomic(self.password_path, (salt.hex() + ":" + digest.hex()), mode=0o600)

    def check_password(self, password):
        try:
            with open(self.password_path, encoding="utf-8") as f:
                salt_hex, digest_hex = f.read().strip().split(":")
        except (OSError, ValueError):
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), digest_hex)


def redact(text, store):
    """Remove any stored key from a piece of text before it is logged or shown."""
    if not text:
        return text
    for name in SECRET_NAMES:
        value = store.secret(name)
        if value and len(value) >= 6:
            text = text.replace(value, "[%s key]" % name)
    return text
