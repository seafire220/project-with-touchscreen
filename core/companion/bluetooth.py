"""Bluetooth audio device discovery and pairing via `bluetoothctl`.

Zero extra Python packages: wraps the standard Linux BlueZ `bluetoothctl` CLI so owners
can pair Bluetooth desk speakers or headphones directly on the touchscreen or web console.
"""
import asyncio
import re
import shutil

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")
DEVICE_LINE = re.compile(r"^Device\s+([0-9A-Fa-f:]{17})\s+(.+)$")


class BluetoothError(RuntimeError):
    """A Bluetooth pairing or scanning error shown directly to the owner."""


async def _run(*args, timeout=15):
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise BluetoothError("bluetoothctl is not installed on this device")
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise BluetoothError("Bluetooth command timed out")
    text = out.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        msg = err.decode("utf-8", errors="replace").strip() or text or "Bluetooth command failed"
        raise BluetoothError(msg)
    return text


def _valid_mac(mac):
    mac = str(mac or "").strip().upper()
    if not MAC_RE.match(mac):
        raise BluetoothError("invalid Bluetooth address")
    return mac


def _parse_devices(text):
    out = {}
    for line in (text or "").splitlines():
        m = DEVICE_LINE.match(line.strip())
        if not m:
            continue
        mac = m.group(1).upper()
        name = m.group(2).strip()
        if not name or name.replace("-", ":") == mac:
            continue
        out[mac] = name
    return out


class Bluetooth:
    """Discover, pair, connect and disconnect Bluetooth speakers/headphones."""

    def __init__(self, run=None):
        self._custom_run = run is not None
        self.run = run or _run

    def available(self):
        return self._custom_run or shutil.which("bluetoothctl") is not None

    async def _list_set(self, *subcmd):
        try:
            text = await self.run("bluetoothctl", *subcmd, timeout=8)
        except BluetoothError:
            return {}
        return _parse_devices(text)

    async def devices(self):
        """Return known/nearby Bluetooth devices sorted with connected first, then paired, then name."""
        if not self.available():
            raise BluetoothError("Bluetooth is unavailable on this machine")
        all_devs = await self._list_set("devices")
        paired = await self._list_set("devices", "Paired")
        connected = await self._list_set("devices", "Connected")
        merged = dict(all_devs)
        merged.update(paired)
        merged.update(connected)
        items = [
            {
                "mac": mac,
                "name": name,
                "paired": mac in paired or mac in connected,
                "connected": mac in connected,
            }
            for mac, name in merged.items()
        ]
        items.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
        return items

    async def scan(self, seconds=4.0):
        """Briefly scan for nearby Bluetooth devices, then return the refreshed device list."""
        if not self.available():
            raise BluetoothError("Bluetooth is unavailable on this machine")
        secs = max(2, min(10, int(round(seconds))))
        try:
            await self.run("bluetoothctl", "--timeout", str(secs), "scan", "on", timeout=secs + 6)
        except BluetoothError:
            # Some bluetoothctl builds exit non-zero when --timeout stops scan; still read discovered devices.
            pass
        return await self.devices()

    async def connect(self, mac):
        mac = _valid_mac(mac)
        if not self.available():
            raise BluetoothError("Bluetooth is unavailable on this machine")
        try:
            await self.run("bluetoothctl", "pair", mac, timeout=15)
        except BluetoothError:
            # Already paired devices return an error on pair; proceed to trust + connect.
            pass
        try:
            await self.run("bluetoothctl", "trust", mac, timeout=8)
        except BluetoothError:
            pass
        await self.run("bluetoothctl", "connect", mac, timeout=18)
        return True

    async def disconnect(self, mac):
        mac = _valid_mac(mac)
        if not self.available():
            raise BluetoothError("Bluetooth is unavailable on this machine")
        await self.run("bluetoothctl", "disconnect", mac, timeout=10)
        return True

    async def remove(self, mac):
        mac = _valid_mac(mac)
        if not self.available():
            raise BluetoothError("Bluetooth is unavailable on this machine")
        await self.run("bluetoothctl", "remove", mac, timeout=10)
        return True
