"""The screen's backlight, where Linux lets it be set (/sys/class/backlight).

A screen on the ribbon (DSI) connector usually has one; an HDMI screen usually doesn't, and is then
dimmed or darkened by the stage alone, drawing black (stage/src/overlay.rs). A rule installed with the
software (device/config/99-companion-backlight.rules) lets the service set it without being root.
"""
import os

ROOT = "/sys/class/backlight"


class Backlight:
    def __init__(self, root=ROOT):
        self.path = None
        self.max = 0
        try:
            names = sorted(os.listdir(root))
        except OSError:
            names = []
        for name in names:
            path = os.path.join(root, name)
            if os.access(os.path.join(path, "brightness"), os.W_OK):
                self.path = path
                self.max = self._read("max_brightness")
                break

    @property
    def available(self):
        return bool(self.path and self.max > 0)

    def _read(self, name):
        try:
            with open(os.path.join(self.path, name)) as f:
                return int(f.read().strip() or 0)
        except (OSError, ValueError):
            return 0

    def _write(self, name, value):
        path = os.path.join(self.path, name)
        if not os.access(path, os.W_OK):
            return False
        try:
            with open(path, "w") as f:
                f.write(str(int(value)))
            return True
        except OSError:
            return False

    def set(self, fraction):
        """Light the screen at `fraction` of full brightness (0 switches the backlight off). Returns
        whether the screen has a backlight that could be set."""
        if not self.available:
            return False
        if fraction <= 0:
            self._write("brightness", 0)
            self._write("bl_power", 4)            # FB_BLANK_POWERDOWN
        else:
            self._write("bl_power", 0)
            self._write("brightness", max(1, round(self.max * min(1.0, fraction))))
        return True

    def level(self):
        """The brightness now, 0 to 1 (None without a backlight)."""
        if not self.available:
            return None
        if self._read("bl_power") == 4:
            return 0.0
        return self._read("brightness") / self.max
