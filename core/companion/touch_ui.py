"""Polished on-screen touchscreen interface for the companion device (docs/35-touchscreen.md).

The core renders crisp 2x-supersampled frosted-glass overlays (floating bottom pill, auto-hiding
quick controls dock, character switcher, timers & clock, moods & console QR, on-screen Wi-Fi
picker, and a full QWERTY touch keyboard) into the stage's RAM overlay folder, and tells the stage
which screen rectangles capture touch input. The stage draws them at 60 fps with cubic slide-in
transitions, backdrop scrims and procedural tap ripples, and forwards UI touch events back here.

Every interactive control registers its hitbox from the exact pixel coordinates used to draw it,
guaranteeing 1:1 visual-to-touch alignment at any display resolution.
"""
import asyncio
import datetime
import io
import logging
import math
import os
import time

from PIL import Image, ImageDraw, ImageOps

from . import overlays as ov
from . import screen as screen_mod
from . import updates as updates_mod

log = logging.getLogger("companion.touch")

# ----- Frosted-glass dark palette
GLASS_BG = (17, 19, 30, 234)
GLASS_CARD = (28, 32, 48, 232)
GLASS_CARD_HI = (40, 46, 68, 240)
GLASS_BORDER = (255, 255, 255, 36)
GLASS_SHEEN = (255, 255, 255, 20)
KEY_BG = (42, 46, 64, 240)
KEY_MOD = (31, 35, 50, 240)

TEXT_PRIMARY = (245, 247, 252, 255)
TEXT_MUTED = (164, 172, 196, 255)
TEXT_DIM = (118, 126, 150, 255)

ACCENT = (102, 134, 255, 255)
ACCENT_BG = (84, 114, 242, 235)
ACCENT_SOFT = (102, 134, 255, 52)
CYAN = (56, 198, 255, 255)
CYAN_BG = (34, 154, 214, 236)
VIOLET = (167, 139, 250, 255)
VIOLET_BG = (128, 96, 224, 236)
CORAL = (240, 92, 108, 255)
CORAL_BG = (212, 68, 86, 238)
EMERALD = (52, 211, 153, 255)
AMBER = (251, 191, 36, 255)
ROSE = (255, 126, 182, 255)

# Keyboard layouts (each row is a list of (key_id, label, weight)).
KB_ALPHA_ROWS = (
    tuple((c, c, 1.0) for c in "qwertyuiop"),
    tuple((c, c, 1.0) for c in "asdfghjkl"),
    (("shift", "shift", 1.45),) + tuple((c, c, 1.0) for c in "zxcvbnm") + (("back", "back", 1.45),),
    (("mode_num", "123", 1.6), ("space", "space", 4.1), ("clear", "Clear", 1.5), ("submit", "Connect", 2.4)),
)
KB_NUM_ROWS = (
    tuple((c, c, 1.0) for c in "1234567890"),
    tuple((c, c, 1.0) for c in "-/:;()$&@\""),
    (("mode_sym", "#+=", 1.45),) + tuple((c, c, 1.0) for c in ".,?!'_*") + (("back", "back", 1.45),),
    (("mode_abc", "abc", 1.6), ("space", "space", 4.1), ("clear", "Clear", 1.5), ("submit", "Connect", 2.4)),
)
KB_SYM_ROWS = (
    tuple((c, c, 1.0) for c in "[]{}#%^*+="),
    tuple((c, c, 1.0) for c in "_\\|~<>!@#$"),
    (("mode_num", "123", 1.45),) + tuple((c, c, 1.0) for c in ".,?!'`~") + (("back", "back", 1.45),),
    (("mode_abc", "abc", 1.6), ("space", "space", 4.1), ("clear", "Clear", 1.5), ("submit", "Connect", 2.4)),
)

QUICK_TIMERS = (
    (60, "1m"),
    (300, "5m"),
    (600, "10m"),
    (900, "15m"),
    (1800, "30m"),
)

QUICK_MOODS = (
    ("happy", "Happy"),
    ("neutral", "Calm"),
    ("surprised", "Wow"),
    ("embarrassed", "Shy"),
    ("wave", "Wave"),
)


def place_overlay(w, h, sw, sh, anchor="bottom"):
    """Exact screen top-left pixel matching stage/src/overlay.rs::Anchor::place."""
    fit = min(sw * 0.96 / max(1, w), sh * 0.96 / max(1, h), 1.0)
    dw, dh = w * fit, h * fit
    m = round(min(sw, sh) * 0.03)
    cx = round((sw - dw) * 0.5)
    cy = round((sh - dh) * 0.5)
    if anchor == "top":
        return cx, m, dw, dh
    if anchor == "center":
        return cx, cy, dw, dh
    if anchor == "top_left":
        return m, m, dw, dh
    if anchor == "top_right":
        return sw - dw - m, m, dw, dh
    if anchor == "bottom_left":
        return m, sh - dh - m, dw, dh
    if anchor == "bottom_right":
        return sw - dw - m, sh - dh - m, dw, dh
    return cx, sh - dh - m, dw, dh


def _fit_text(draw, text, font, max_w):
    """Trim text with an ellipsis so it never overflows its box."""
    text = str(text or "")
    if max_w <= 8 or draw.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw.textlength(text[:mid].rstrip() + ell, font=font) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo].rstrip() + ell) if lo > 0 else ell


def _fmt_remaining(seconds):
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)


# ----- Vector icon drawing (drawn on the 2x supersampled canvas, zero emoji fonts required)

def _icon_mic(draw, cx, cy, r, color, muted=False):
    w = max(2, round(r * 0.16))
    draw.rounded_rectangle((cx - r * 0.3, cy - r * 0.72, cx + r * 0.3, cy + r * 0.14), radius=r * 0.3, fill=color)
    draw.arc((cx - r * 0.54, cy - r * 0.42, cx + r * 0.54, cy + r * 0.42), start=0, end=180, fill=color, width=w)
    draw.line((cx, cy + r * 0.42, cx, cy + r * 0.74), fill=color, width=w)
    draw.line((cx - r * 0.34, cy + r * 0.74, cx + r * 0.34, cy + r * 0.74), fill=color, width=w)
    if muted:
        draw.line((cx - r * 0.68, cy - r * 0.62, cx + r * 0.68, cy + r * 0.66), fill=CORAL, width=max(3, round(w * 1.4)))


def _icon_speaker(draw, cx, cy, r, color, level=1.0):
    w = max(2, round(r * 0.15))
    poly = [
        (cx - r * 0.68, cy - r * 0.28),
        (cx - r * 0.32, cy - r * 0.28),
        (cx + r * 0.08, cy - r * 0.64),
        (cx + r * 0.08, cy + r * 0.64),
        (cx - r * 0.32, cy + r * 0.28),
        (cx - r * 0.68, cy + r * 0.28),
    ]
    draw.polygon(poly, fill=color)
    if level > 0.05:
        draw.arc((cx - r * 0.14, cy - r * 0.38, cx + r * 0.5, cy + r * 0.38), start=-52, end=52, fill=color, width=w)
    if level > 0.45:
        draw.arc((cx - r * 0.04, cy - r * 0.66, cx + r * 0.78, cy + r * 0.66), start=-52, end=52, fill=color, width=w)
    if level <= 0.05:
        draw.line((cx + r * 0.28, cy - r * 0.28, cx + r * 0.72, cy + r * 0.28), fill=CORAL, width=w)
        draw.line((cx + r * 0.72, cy - r * 0.28, cx + r * 0.28, cy + r * 0.28), fill=CORAL, width=w)


def _icon_sun(draw, cx, cy, r, color):
    w = max(2, round(r * 0.14))
    cr = r * 0.34
    draw.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=color)
    for k in range(8):
        ang = k * math.pi / 4.0
        x0, y0 = cx + math.cos(ang) * r * 0.54, cy + math.sin(ang) * r * 0.54
        x1, y1 = cx + math.cos(ang) * r * 0.8, cy + math.sin(ang) * r * 0.8
        draw.line((x0, y0, x1, y1), fill=color, width=w)


def _icon_people(draw, cx, cy, r, color):
    hr = r * 0.28
    draw.ellipse((cx - hr - r * 0.12, cy - r * 0.66, cx + hr - r * 0.12, cy - r * 0.66 + hr * 2), fill=color)
    draw.pieslice((cx - r * 0.68, cy - r * 0.04, cx + r * 0.44, cy + r * 0.96), start=180, end=360, fill=color)
    dim = (color[0], color[1], color[2], int(color[3] * 0.55))
    sr = r * 0.21
    draw.ellipse((cx + r * 0.24, cy - r * 0.52, cx + r * 0.24 + sr * 2, cy - r * 0.52 + sr * 2), fill=dim)
    draw.pieslice((cx + r * 0.08, cy + r * 0.06, cx + r * 0.82, cy + r * 0.86), start=180, end=360, fill=dim)


def _icon_captions(draw, cx, cy, r, color):
    w = max(2, round(r * 0.13))
    draw.rounded_rectangle((cx - r * 0.78, cy - r * 0.56, cx + r * 0.78, cy + r * 0.56), radius=r * 0.24, outline=color, width=w)
    draw.line((cx - r * 0.48, cy - r * 0.14, cx + r * 0.48, cy - r * 0.14), fill=color, width=w)
    draw.line((cx - r * 0.48, cy + r * 0.18, cx + r * 0.24, cy + r * 0.18), fill=color, width=w)


def _icon_moon(draw, cx, cy, r, color, bg=GLASS_CARD):
    draw.ellipse((cx - r * 0.66, cy - r * 0.66, cx + r * 0.66, cy + r * 0.66), fill=color)
    draw.ellipse((cx - r * 0.22, cy - r * 0.78, cx + r * 0.96, cy + r * 0.44), fill=bg)


def _icon_timer(draw, cx, cy, r, color):
    w = max(2, round(r * 0.14))
    draw.ellipse((cx - r * 0.66, cy - r * 0.54, cx + r * 0.66, cy + r * 0.78), outline=color, width=w)
    draw.line((cx - r * 0.24, cy - r * 0.76, cx + r * 0.24, cy - r * 0.76), fill=color, width=w)
    draw.line((cx, cy - r * 0.76, cx, cy - r * 0.54), fill=color, width=w)
    draw.line((cx, cy + r * 0.12, cx, cy - r * 0.26), fill=color, width=w)
    draw.line((cx, cy + r * 0.12, cx + r * 0.3, cy + r * 0.22), fill=color, width=w)


def _icon_wifi(draw, cx, cy, r, color, strength=100, locked=False):
    w = max(2, round(r * 0.14))
    dim = (color[0], color[1], color[2], 70)
    by = cy + r * 0.54
    for idx, (rad, thresh) in enumerate(((r * 0.92, 66), (r * 0.62, 33), (r * 0.34, 1))):
        col = color if strength >= thresh else dim
        draw.arc((cx - rad, by - rad, cx + rad, by + rad), start=225, end=315, fill=col, width=w)
    dot = r * 0.12
    draw.ellipse((cx - dot, by - dot, cx + dot, by + dot), fill=color if strength > 0 else dim)
    if locked:
        lx, ly = cx + r * 0.56, cy + r * 0.34
        draw.rounded_rectangle((lx - r * 0.22, ly, lx + r * 0.22, ly + r * 0.32), radius=r * 0.06, fill=AMBER)
        draw.arc((lx - r * 0.14, ly - r * 0.18, lx + r * 0.14, ly + r * 0.12), start=180, end=360, fill=AMBER, width=max(2, round(w * 0.8)))


def _icon_qr(draw, cx, cy, r, color):
    w = max(2, round(r * 0.12))
    s = r * 0.52
    for ox, oy in ((-r * 0.68, -r * 0.68), (r * 0.16, -r * 0.68), (-r * 0.68, r * 0.16)):
        draw.rounded_rectangle((cx + ox, cy + oy, cx + ox + s, cy + oy + s), radius=r * 0.08, outline=color, width=w)
        p = s * 0.28
        draw.rectangle((cx + ox + p, cy + oy + p, cx + ox + s - p, cy + oy + s - p), fill=color)
    draw.rectangle((cx + r * 0.22, cy + r * 0.22, cx + r * 0.44, cy + r * 0.44), fill=color)
    draw.rectangle((cx + r * 0.48, cy + r * 0.48, cx + r * 0.70, cy + r * 0.70), fill=color)


def _icon_close(draw, cx, cy, r, color):
    w = max(2, round(r * 0.18))
    d = r * 0.52
    draw.line((cx - d, cy - d, cx + d, cy + d), fill=color, width=w)
    draw.line((cx + d, cy - d, cx - d, cy + d), fill=color, width=w)


def _icon_chevron(draw, cx, cy, r, color, direction="up"):
    w = max(2, round(r * 0.18))
    d = r * 0.46
    if direction == "up":
        pts = [(cx - d, cy + d * 0.4), (cx, cy - d * 0.5), (cx + d, cy + d * 0.4)]
    elif direction == "down":
        pts = [(cx - d, cy - d * 0.4), (cx, cy + d * 0.5), (cx + d, cy - d * 0.4)]
    elif direction == "left":
        pts = [(cx + d * 0.4, cy - d), (cx - d * 0.5, cy), (cx + d * 0.4, cy + d)]
    else:
        pts = [(cx - d * 0.4, cy - d), (cx + d * 0.5, cy), (cx - d * 0.4, cy + d)]
    draw.line(pts, fill=color, width=w, joint="curve")


def _icon_eye(draw, cx, cy, r, color, shown=True):
    w = max(2, round(r * 0.14))
    draw.arc((cx - r * 0.74, cy - r * 0.46, cx + r * 0.74, cy + r * 0.46), start=200, end=340, fill=color, width=w)
    draw.arc((cx - r * 0.74, cy - r * 0.46, cx + r * 0.74, cy + r * 0.46), start=20, end=160, fill=color, width=w)
    draw.ellipse((cx - r * 0.22, cy - r * 0.22, cx + r * 0.22, cy + r * 0.22), fill=color)
    if not shown:
        draw.line((cx - r * 0.62, cy - r * 0.52, cx + r * 0.62, cy + r * 0.52), fill=CORAL, width=max(2, round(w * 1.2)))


def _icon_backspace(draw, cx, cy, r, color):
    w = max(2, round(r * 0.14))
    pts = [
        (cx - r * 0.74, cy),
        (cx - r * 0.34, cy - r * 0.46),
        (cx + r * 0.68, cy - r * 0.46),
        (cx + r * 0.68, cy + r * 0.46),
        (cx - r * 0.34, cy + r * 0.46),
    ]
    draw.polygon(pts, outline=color, width=w)
    d = r * 0.22
    draw.line((cx + r * 0.14 - d, cy - d, cx + r * 0.14 + d, cy + d), fill=color, width=w)
    draw.line((cx + r * 0.14 + d, cy - d, cx + r * 0.14 - d, cy + d), fill=color, width=w)


def _icon_shift(draw, cx, cy, r, color, filled=False, locked=False):
    w = max(2, round(r * 0.14))
    pts = [
        (cx, cy - r * 0.62),
        (cx + r * 0.62, cy + r * 0.04),
        (cx + r * 0.26, cy + r * 0.04),
        (cx + r * 0.26, cy + r * 0.52),
        (cx - r * 0.26, cy + r * 0.52),
        (cx - r * 0.26, cy + r * 0.04),
        (cx - r * 0.62, cy + r * 0.04),
    ]
    if filled:
        draw.polygon(pts, fill=color)
    else:
        draw.polygon(pts, outline=color, width=w)
    if locked:
        draw.line((cx - r * 0.34, cy + r * 0.72, cx + r * 0.34, cy + r * 0.72), fill=color, width=w)


# ----- 2x supersampled glass canvas helper

class _Canvas:
    """Draws anti-aliased rounded glass shapes & vector icons at 2x, then crisp text at 1x."""

    def __init__(self, width, height, screen, anchor="bottom", scale=2):
        self.w = int(width)
        self.h = int(height)
        self.screen = screen
        self.anchor = anchor
        self.s = scale
        self.hi = Image.new("RGBA", (self.w * scale, self.h * scale), (0, 0, 0, 0))
        self.g = ImageDraw.Draw(self.hi)
        self._texts = []
        self._pastes = []
        self.hits = []      # (x0, y0, x1, y1, action, payload) in local pixels

    def hit(self, rect, action, payload=None):
        x0, y0, x1, y1 = rect
        self.hits.append((float(x0), float(y0), float(x1), float(y1), action, payload))

    def panel(self, radius=32, fill=GLASS_BG):
        s = self.s
        self.g.rounded_rectangle((0, 0, self.w * s - 1, self.h * s - 1), radius=radius * s, fill=fill,
                                 outline=GLASS_BORDER, width=max(2, s))
        # Subtle luminous top specular hairline inside the glass edge.
        self.g.line((radius * s, s * 2, (self.w - radius) * s, s * 2), fill=GLASS_SHEEN, width=max(2, s))

    def rect(self, box, radius=18, fill=GLASS_CARD, outline=None, width=1):
        s = self.s
        x0, y0, x1, y1 = (v * s for v in box)
        self.g.rounded_rectangle((x0, y0, x1, y1), radius=radius * s, fill=fill,
                                 outline=outline, width=max(1, round(width * s)) if outline else 0)

    def circle(self, cx, cy, r, fill, outline=None, width=1):
        s = self.s
        self.g.ellipse(((cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s), fill=fill,
                       outline=outline, width=max(1, round(width * s)) if outline else 0)

    def icon(self, fn, cx, cy, r, *args, **kwargs):
        fn(self.g, cx * self.s, cy * self.s, r * self.s, *args, **kwargs)

    def paste_rounded(self, img, box, radius=14, sharp=False):
        s = self.s
        x0, y0, x1, y1 = (v * s for v in box)
        tw, th = max(1, int(round(x1 - x0))), max(1, int(round(y1 - y0)))
        fitted = ImageOps.fit(img.convert("RGBA"), (tw, th), method=Image.NEAREST if sharp else Image.LANCZOS)
        mask = Image.new("L", (tw, th), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw - 1, th - 1), radius=radius * s, fill=255)
        self.hi.paste(fitted, (int(round(x0)), int(round(y0))), mask)

    def text(self, pos, value, size, color=TEXT_PRIMARY, bold=True, anchor="la", max_w=None):
        self._texts.append((pos, str(value), max(10, round(size)), color, bold, anchor, max_w))

    def finish(self):
        img = self.hi.resize((self.w, self.h), Image.LANCZOS)
        draw = ImageDraw.Draw(img)
        for (x, y), value, size, color, bold, anchor, max_w in self._texts:
            font = ov._font(size, bold=bold)
            shown = _fit_text(draw, value, font, max_w) if max_w is not None else value
            draw.text((x, y), shown, font=font, fill=color, anchor=anchor)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def screen_rect(self):
        sw, sh = self.screen
        ox, oy, dw, dh = place_overlay(self.w, self.h, sw, sh, self.anchor)
        return [round(ox / sw, 4), round(oy / sh, 4), round((ox + dw) / sw, 4), round((oy + dh) / sh, 4)]

    def screen_hits(self):
        sw, sh = self.screen
        ox, oy, dw, dh = place_overlay(self.w, self.h, sw, sh, self.anchor)
        sx, sy = dw / max(1, self.w), dh / max(1, self.h)
        out = []
        for x0, y0, x1, y1, action, payload in self.hits:
            out.append((
                (ox + x0 * sx) / sw,
                (oy + y0 * sy) / sh,
                (ox + x1 * sx) / sw,
                (oy + y1 * sy) / sh,
                action,
                payload,
            ))
        return out


# ----- Main TouchUI controller

class TouchUI:
    """Manages on-screen glass controls, character switcher, timers, status/QR, Wi-Fi setup & keyboard."""

    def __init__(self, device):
        self.device = device
        self.view = "pill"              # "pill", "dock", "characters", "timers", "status", "wifi", "keyboard"
        self.hits = []                  # [(nx0, ny0, nx1, ny1, action, payload)] for active view
        self.panel_rect = None          # normalized [x0, y0, x1, y1] of open dock/sheet
        self.pill_rect = None           # normalized [x0, y0, x1, y1] of floating pill
        self._dragging = None           # "volume" | "brightness" | None
        self._auto_hide_handle = None
        self._tick_task = None
        self._caption_visible = False
        self._setup_card_showing = False

        # Character switcher pagination
        self.char_page = 0

        # Wi-Fi picker & touch keyboard state
        self.wifi_networks = []
        self.wifi_scanning = False
        self.wifi_connected = False
        self.wifi_address = ""
        self.wifi_error = ""
        self.wifi_page = 0
        self.kb_target = "wifi_password"   # "wifi_password" or "wifi_ssid"
        self.kb_ssid = ""
        self.kb_text = ""
        self.kb_layout = "abc"             # "abc", "num", "sym"
        self.kb_shift = False
        self.kb_caps = False
        self.kb_show_text = False
        self.kb_error = ""
        self.kb_busy = False
        self._last_shift_tap = 0.0

        # Listen for caption show/hide so the floating pill yields cleanly to captions.
        self.device.overlays.on_caption_change = self._on_caption_change

    # ----- lifecycle & settings sync

    def enabled(self):
        return bool(self.device.store.settings().get("touch", {}).get("enabled", True))

    def sync_stage_config(self):
        """Push touchscreen settings and current hit-capture regions to the stage."""
        cfg = self.device.store.settings().get("touch", {})
        self.device.stage.send({
            "touch_config": {
                "enabled": bool(cfg.get("enabled", True)),
                "character_touch": bool(cfg.get("character_touch", True)),
                "effects": bool(cfg.get("effects", True)),
            }
        })
        self._push_capture()

    def set_setup_mode(self, active):
        """Called when a setup/hotspot card is shown (or replaced by a character)."""
        self._setup_card_showing = bool(active)
        if self.device.touch_ready and self.view == "pill":
            self.render()

    def on_stage_ready(self):
        """Stage just started or reconnected: restore config, pill or open sheet."""
        self.sync_stage_config()
        if self.enabled():
            self.render()
        else:
            self.hide_all()

    def on_screen_resized(self):
        if self.device.touch_ready and self.enabled():
            self.render()

    def _on_caption_change(self, visible):
        self._caption_visible = bool(visible)
        if self.device.touch_ready and self.view == "pill":
            self.render()

    def on_state_changed(self):
        """Refresh the pill or dock whenever listening/speaking/muted/timer state changes."""
        if not self.enabled():
            return
        if self.view in ("pill", "dock", "timers", "status"):
            self.render()

    def hide_all(self):
        self._cancel_auto_hide()
        self._stop_tick()
        self.view = "pill"
        self.hits = []
        self.panel_rect = None
        self.pill_rect = None
        self.device.overlays.hide(ov.TOUCH_PILL)
        self.device.overlays.hide(ov.TOUCH_DOCK)
        self.device.overlays.hide(ov.TOUCH_SHEET)
        self._push_capture()

    def _push_capture(self):
        if not self.enabled():
            self.device.stage.send({"touch_capture": {"modal": False, "panel": None, "pill": None, "edge_swipe": False}})
            return
        modal = self.view != "pill"
        self.device.stage.send({
            "touch_capture": {
                "modal": modal,
                "panel": self.panel_rect if modal else None,
                "pill": self.pill_rect if not modal else None,
                "edge_swipe": not modal,
            }
        })

    # ----- auto-hide & live ticking

    def _arm_auto_hide(self):
        self._cancel_auto_hide()
        if self.view != "dock":
            return
        seconds = float(self.device.store.settings().get("touch", {}).get("auto_hide", 8.0))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._auto_hide_handle = loop.call_later(max(3.0, seconds), self.dismiss)

    def _cancel_auto_hide(self):
        if self._auto_hide_handle is not None:
            self._auto_hide_handle.cancel()
            self._auto_hide_handle = None

    def _ensure_tick(self):
        """Refresh clock/countdowns every second while timers view (or pill with active timer) is shown."""
        need = self.view == "timers" or (self.view == "pill" and bool(self.device.timers))
        if not need:
            self._stop_tick()
            return
        if self._tick_task is not None and not self._tick_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def tick():
            try:
                while True:
                    await asyncio.sleep(1.0)
                    if not self.enabled():
                        return
                    if self.view == "timers" or (self.view == "pill" and bool(self.device.timers)):
                        self.render()
                    else:
                        return
            except asyncio.CancelledError:
                pass

        self._tick_task = loop.create_task(tick())

    def _stop_tick(self):
        if self._tick_task is not None and not self._tick_task.done():
            self._tick_task.cancel()
        self._tick_task = None

    # ----- view navigation

    def open_view(self, view):
        if not self.enabled():
            return
        self._dragging = None
        self.view = view
        self.device.activity()
        if view == "dock":
            self.device.overlays.hide(ov.TOUCH_PILL)
            self.device.overlays.hide(ov.TOUCH_SHEET)
            self._arm_auto_hide()
        elif view == "pill":
            self._cancel_auto_hide()
            self.device.overlays.hide(ov.TOUCH_DOCK)
            self.device.overlays.hide(ov.TOUCH_SHEET)
        else:
            self._cancel_auto_hide()
            self.device.overlays.hide(ov.TOUCH_PILL)
            self.device.overlays.hide(ov.TOUCH_DOCK)
        if view == "wifi":
            self.wifi_page = 0
            self.wifi_error = ""
            self._start_wifi_scan()
        elif view == "status":
            self._refresh_wifi_address()
        elif view == "characters":
            self.char_page = 0
        self.render()
        self._ensure_tick()

    def dismiss(self):
        """Return smoothly to the clean character-first view with the minimal floating pill."""
        if self.view != "pill":
            self.open_view("pill")

    # ----- incoming touch events from the stage

    def handle_ui_event(self, event):
        """Handle one `ui_touch` JSON event forwarded from the stage."""
        if not self.enabled():
            return
        self.device.activity()
        phase = event.get("phase")
        target = event.get("target")
        x = float(event.get("x", 0.5))
        y = float(event.get("y", 0.5))
        direction = event.get("dir", "")

        if self.view == "dock" and phase in ("down", "move", "up", "tap"):
            self._arm_auto_hide()

        # Backdrop tap/swipe dismisses any open dock or modal sheet cleanly.
        if target == "backdrop" and phase == "tap":
            self.dismiss()
            return

        # Bottom edge swipe-up opens the Quick Controls Dock; top edge swipe-down opens Timers.
        if target == "edge" and phase == "swipe":
            if direction == "up":
                if self._setup_card_showing and not self.device.active_id():
                    self.open_view("wifi")
                else:
                    self.open_view("dock")
            elif direction == "down":
                self.open_view("timers")
            return

        # Floating pill interactions.
        if target == "pill":
            if phase == "swipe" and direction == "up":
                self.open_view("wifi" if (self._setup_card_showing and not self.device.active_id()) else "dock")
            elif phase == "tap":
                self._tap_pill()
            elif phase == "long_press":
                self.device.button()
                self.render()
            return

        # Panel / sheet interactions (including smooth slider dragging & swipe pagination/dismiss).
        if target == "panel":
            if phase == "down":
                hit = self._find_hit(x, y)
                if hit and hit[4] in ("slider_volume", "slider_brightness"):
                    self._dragging = hit[4]
                    self._apply_slider(hit, x)
            elif phase == "move":
                if self._dragging:
                    hit = self._find_action(self._dragging)
                    if hit:
                        self._apply_slider(hit, x)
            elif phase == "up":
                self._dragging = None
            elif phase == "tap":
                hit = self._find_hit(x, y)
                if hit:
                    self._run_action(hit[4], hit[5], hit, x)
            elif phase == "swipe":
                if direction == "down" and self.view in ("dock", "characters", "timers", "status", "wifi"):
                    self.dismiss()
                elif direction in ("left", "right") and self.view == "characters":
                    self._step_char_page(1 if direction == "left" else -1)
                elif direction in ("left", "right") and self.view == "wifi":
                    self._step_wifi_page(1 if direction == "left" else -1)

    def _tap_pill(self):
        if self._setup_card_showing and not self.device.active_id():
            self.open_view("wifi")
            return
        busy = self.device.conversation is not None and self.device.conversation.busy
        if busy or self.device.listening or self.device.recording is not None:
            # One tap on the active pill interrupts speech or stops/sends listening immediately.
            self.device.button()
            self.render()
            return
        self.open_view("dock")

    def _find_hit(self, x, y):
        for item in reversed(self.hits):
            if item[0] <= x <= item[2] and item[1] <= y <= item[3]:
                return item
        return None

    def _find_action(self, action):
        for item in self.hits:
            if item[4] == action:
                return item
        return None

    def _apply_slider(self, hit, x):
        x0, _, x1, _, action, _ = hit
        frac = max(0.0, min(1.0, (x - x0) / max(1e-4, x1 - x0)))
        if action == "slider_volume":
            vol = round(frac * 20) / 20.0
            if abs(vol - float(self.device.store.settings().get("volume", 0.8))) >= 0.04 or frac in (0.0, 1.0):
                self.device.store.update_settings({"volume": vol})
                self.device.speaker.volume = vol
                self.device.emit("touch_ui", {"action": "volume", "value": vol})
                self.render()
        elif action == "slider_brightness":
            pct = max(10, min(100, int(round((10 + frac * 90) / 5.0) * 5)))
            cur = int(self.device.store.settings().get("screen", {}).get("brightness", 100))
            if pct != cur:
                self.device.store.update_settings({"screen": {"brightness": pct}})
                self.device.backlight.set(pct / 100.0)
                self.device.emit("touch_ui", {"action": "brightness", "value": pct})
                self.render()

    def _run_action(self, action, payload, hit, x):
        if action in ("slider_volume", "slider_brightness"):
            self._apply_slider(hit, x)
            return
        if action == "close":
            self.dismiss()
        elif action == "talk":
            self.device.button()
            # Keep dock open briefly when starting push-to-talk, else let the character shine!
            if self.device.listening or (self.device.conversation and self.device.conversation.busy):
                self.dismiss()
            else:
                self.render()
        elif action == "mute":
            if self.device.mic_switch:
                self.device.overlays.hint("The mute switch is on: slide it to turn the microphone on", seconds=3.5)
            else:
                self.device.set_muted(not self.device._mute_choice)
                self.device.overlays.hint("Microphone off" if self.device.muted else "Microphone on", seconds=1.8)
            self.render()
        elif action == "captions":
            cur = bool(self.device.store.settings().get("captions", {}).get("on"))
            old = self.device.store.settings()
            new = self.device.store.update_settings({"captions": {"on": not cur}})
            self.device.settings_changed(old, new)
            self.device.emit("touch_ui", {"action": "captions", "on": not cur})
            self.render()
        elif action == "sleep":
            self.dismiss()
            how = self.device.store.settings().get("screen", {}).get("how", "off")
            self.device.set_screen(how)
            self.device.emit("touch_ui", {"action": "sleep", "screen": how})
        elif action == "open_characters":
            self.open_view("characters")
        elif action == "open_timers":
            self.open_view("timers")
        elif action == "open_wifi":
            self.open_view("wifi")
        elif action == "open_status":
            self.open_view("status")
        elif action == "select_character":
            cid = str(payload)
            if cid != self.device.active_id():
                try:
                    name = self.device.characters.manifest(cid).get("name", cid)
                    self.dismiss()
                    self.device.overlays.hint("Switching to %s…" % name, seconds=2.0)
                    self.device.activate(cid)
                    self.device.emit("touch_ui", {"action": "character", "id": cid})
                except KeyError:
                    pass
            else:
                self.dismiss()
        elif action == "char_prev":
            self._step_char_page(-1)
        elif action == "char_next":
            self._step_char_page(1)
        elif action == "quick_timer":
            secs, label = payload
            self.device.action({"kind": "timer", "seconds": secs, "label": "%s timer" % label})
            self.device.overlays.hint("%s timer set" % label, seconds=1.8)
            self.render()
            self._ensure_tick()
        elif action == "cancel_timer":
            self.device.action({"kind": "cancel", "label": str(payload)})
            self.render()
        elif action == "mood":
            if payload == "wave":
                if hasattr(self.device.stage, "gesture"):
                    self.device.stage.gesture("wave")
            else:
                self.device.stage.express(str(payload))
            self.device.emit("touch_ui", {"action": "mood", "name": str(payload)})
            self.render()
        elif action == "toggle_spoken_touch":
            cur = bool(self.device.store.settings().get("touch", {}).get("spoken_reactions", True))
            self.device.store.update_settings({"touch": {"spoken_reactions": not cur}})
            self.device.emit("touch_ui", {"action": "spoken_reactions", "on": not cur})
            self.render()
        elif action == "toggle_wake_word":
            old = self.device.store.settings()
            cur = bool(old.get("wake_word", {}).get("on"))
            new = self.device.store.update_settings({"wake_word": {"on": not cur}})
            self.device.settings_changed(old, new)
            self.device.emit("touch_ui", {"action": "wake_word", "on": not cur})
            self.render()
        elif action == "toggle_heard_captions":
            old = self.device.store.settings()
            cur = bool(old.get("captions", {}).get("heard"))
            new = self.device.store.update_settings({"captions": {"on": True if not cur else old.get("captions", {}).get("on", False), "heard": not cur}})
            self.device.settings_changed(old, new)
            self.render()
        elif action == "wifi_scan":
            self._start_wifi_scan()
        elif action == "wifi_prev":
            self._step_wifi_page(-1)
        elif action == "wifi_next":
            self._step_wifi_page(1)
        elif action == "wifi_pick":
            net = payload
            if net.get("secure"):
                self._open_keyboard("wifi_password", ssid=net["ssid"])
            else:
                self._join_wifi_async(net["ssid"], "")
        elif action == "wifi_hidden":
            self._open_keyboard("wifi_ssid", ssid="")
        elif action == "kb_back_view":
            self.open_view("wifi")
        elif action == "kb_toggle_show":
            self.kb_show_text = not self.kb_show_text
            self.render()
        elif action == "kb_key":
            self._handle_key(str(payload))

    def _step_char_page(self, delta):
        total = max(1, (len(self.device.characters.list()) + 3) // 4)
        self.char_page = (self.char_page + delta) % total
        self.render()

    def _step_wifi_page(self, delta):
        total = max(1, (len(self.wifi_networks) + 4) // 5)
        self.wifi_page = (self.wifi_page + delta) % total
        self.render()

    # ----- Wi-Fi helpers & touch keyboard logic

    def _open_keyboard(self, target, ssid=""):
        self.kb_target = target
        self.kb_ssid = ssid
        self.kb_text = ""
        self.kb_layout = "abc"
        self.kb_shift = False
        self.kb_caps = False
        self.kb_show_text = target == "wifi_ssid"
        self.kb_error = ""
        self.kb_busy = False
        self.open_view("keyboard")

    def _handle_key(self, key):
        if self.kb_busy:
            return
        self.kb_error = ""
        if key == "back":
            self.kb_text = self.kb_text[:-1]
        elif key == "clear":
            self.kb_text = ""
        elif key == "space":
            if len(self.kb_text) < 63:
                self.kb_text += " "
        elif key == "shift":
            now = time.monotonic()
            if self.kb_shift and not self.kb_caps and now - self._last_shift_tap < 0.45:
                self.kb_caps = True
            elif self.kb_caps:
                self.kb_caps = False
                self.kb_shift = False
            else:
                self.kb_shift = not self.kb_shift
            self._last_shift_tap = now
        elif key == "mode_num":
            self.kb_layout = "num"
        elif key == "mode_sym":
            self.kb_layout = "sym"
        elif key == "mode_abc":
            self.kb_layout = "abc"
        elif key == "submit":
            self._submit_keyboard()
            return
        else:
            max_len = 32 if self.kb_target == "wifi_ssid" else 63
            if len(self.kb_text) < max_len:
                ch = key.upper() if (self.kb_layout == "abc" and (self.kb_shift or self.kb_caps)) else key
                self.kb_text += ch
                if self.kb_shift and not self.kb_caps:
                    self.kb_shift = False
        self.render()

    def _submit_keyboard(self):
        if self.kb_target == "wifi_ssid":
            ssid = self.kb_text.strip()
            if not ssid:
                self.kb_error = "Enter a Wi-Fi network name"
                self.render()
                return
            self._open_keyboard("wifi_password", ssid=ssid)
            return
        pw = self.kb_text
        if pw and len(pw) < 8:
            self.kb_error = "Wi-Fi passwords need at least 8 characters"
            self.render()
            return
        self._join_wifi_async(self.kb_ssid, pw)

    def _start_wifi_scan(self):
        if self.device.wifi is None:
            self.wifi_error = "Wi-Fi management is unavailable on this machine"
            self.wifi_scanning = False
            self.render()
            return
        if self.wifi_scanning:
            return
        self.wifi_scanning = True
        self.wifi_error = ""
        self.render()

        async def scan():
            try:
                self.wifi_connected = await self.device.wifi.connected()
                self.wifi_address = await self.device.wifi.address() if self.wifi_connected else ""
                self.wifi_networks = await self.device.wifi.networks()
            except Exception as err:
                self.wifi_error = str(err)
            finally:
                self.wifi_scanning = False
                if self.view in ("wifi", "status", "dock"):
                    self.render()

        try:
            asyncio.ensure_future(scan())
        except RuntimeError:
            self.wifi_scanning = False

    def _refresh_wifi_address(self):
        if self.device.wifi is None:
            return

        async def fetch():
            try:
                self.wifi_connected = await self.device.wifi.connected()
                self.wifi_address = await self.device.wifi.address() if self.wifi_connected else ""
                if self.view == "status":
                    self.render()
            except Exception:
                pass

        try:
            asyncio.ensure_future(fetch())
        except RuntimeError:
            pass

    def _join_wifi_async(self, ssid, password):
        if self.device.wifi is None:
            self.kb_error = "Wi-Fi is unavailable on this machine"
            self.render()
            return
        self.kb_busy = True
        self.kb_error = ""
        self.render()

        async def connect():
            try:
                await self.device.join_wifi(ssid, password)
                self.wifi_connected = True
                try:
                    self.wifi_address = await self.device.wifi.address()
                except Exception:
                    pass
                self.kb_busy = False
                self.dismiss()
                msg = "Connected to %s" % ssid
                if self.wifi_address:
                    msg += " (%s)" % self.wifi_address
                self.device.overlays.hint(msg, seconds=3.5)
                self.device.emit("touch_ui", {"action": "wifi_joined", "ssid": ssid})
            except Exception as err:
                self.kb_busy = False
                self.kb_error = str(err)
                if self.view != "keyboard":
                    self.wifi_error = str(err)
                self.render()

        try:
            asyncio.ensure_future(connect())
        except RuntimeError:
            self.kb_busy = False

    # ----- Rendering dispatch

    def render(self):
        """Render the current view into a PNG and push both overlay + touch capture bounds to stage."""
        if not self.enabled():
            self.hide_all()
            return
        screen = self.device.overlays.screen
        if self.view == "pill":
            if self._caption_visible:
                # Yield cleanly while captions sit at the bottom edge.
                self.pill_rect = None
                self.panel_rect = None
                self.hits = []
                self.device.overlays.hide(ov.TOUCH_PILL)
                self._push_capture()
                return
            canvas = self._render_pill(screen)
            self.pill_rect = canvas.screen_rect()
            self.panel_rect = None
            self.hits = canvas.screen_hits()
            self.device.overlays.show(ov.TOUCH_PILL, canvas.finish(), anchor="bottom", layer=10, slide="up")
        elif self.view == "dock":
            canvas = self._render_dock(screen)
            self.panel_rect = canvas.screen_rect()
            self.pill_rect = None
            self.hits = canvas.screen_hits()
            self.device.overlays.show(ov.TOUCH_DOCK, canvas.finish(), anchor="bottom", layer=30, slide="up", scrim=0.28)
        else:
            builder = {
                "characters": self._render_characters,
                "timers": self._render_timers,
                "status": self._render_status,
                "wifi": self._render_wifi,
                "keyboard": self._render_keyboard,
            }[self.view]
            canvas = builder(screen)
            self.panel_rect = canvas.screen_rect()
            self.pill_rect = None
            self.hits = canvas.screen_hits()
            self.device.overlays.show(ov.TOUCH_SHEET, canvas.finish(), anchor="bottom", layer=40, slide="up", scrim=0.52)
        self._push_capture()

    # ----- View 1: Minimal Floating Bottom Pill

    def _render_pill(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        state = self.device.state
        busy = self.device.conversation is not None and self.device.conversation.busy
        setup = self._setup_card_showing and not self.device.active_id()

        if setup:
            w, h = min(round(sw * 0.78), 460), max(60, round(side * 0.095))
            c = _Canvas(w, h, screen, anchor="bottom")
            c.rect((0, 0, w, h), radius=h // 2, fill=ACCENT_BG, outline=(255, 255, 255, 70), width=1.5)
            c.icon(_icon_wifi, 36, h / 2, 16, TEXT_PRIMARY, strength=100)
            c.text((w / 2 + 12, h / 2), "Set up Wi-Fi on screen", round(side * 0.036), TEXT_PRIMARY, bold=True, anchor="mm", max_w=w - 92)
            c.hit((0, 0, w, h), "pill")
            return c

        if state == "listening" or self.device.listening or self.device.recording is not None:
            label = "Listening · Tap to send" if self.device.recording is not None else "Listening · Tap to stop"
            w, h = min(round(sw * 0.76), 440), max(54, round(side * 0.082))
            c = _Canvas(w, h, screen, anchor="bottom")
            c.rect((0, 0, w, h), radius=h // 2, fill=(16, 42, 62, 232), outline=CYAN, width=2)
            c.circle(32, h / 2, 8, CYAN)
            c.text((w / 2 + 8, h / 2), label, round(side * 0.033), TEXT_PRIMARY, bold=True, anchor="mm", max_w=w - 76)
            c.hit((0, 0, w, h), "pill")
            return c

        if state == "speaking" or busy:
            label = "Thinking…" if state == "thinking" else "Speaking · Tap to stop"
            accent = ACCENT if state == "thinking" else VIOLET
            w, h = min(round(sw * 0.72), 410), max(54, round(side * 0.082))
            c = _Canvas(w, h, screen, anchor="bottom")
            c.rect((0, 0, w, h), radius=h // 2, fill=(30, 24, 52, 232), outline=accent, width=2)
            c.circle(32, h / 2, 8, accent)
            c.text((w / 2 + 8, h / 2), label, round(side * 0.033), TEXT_PRIMARY, bold=True, anchor="mm", max_w=w - 76)
            c.hit((0, 0, w, h), "pill")
            return c

        # Idle: ultra-clean minimal translucent capsule so the character owns the screen.
        now_str = time.strftime("%H:%M")
        next_timer = self._next_timer_label()
        h = max(48, round(side * 0.072))
        w = max(230, round(side * (0.48 if next_timer else 0.34)))
        c = _Canvas(w, h, screen, anchor="bottom")
        c.rect((0, 0, w, h), radius=h // 2, fill=(16, 18, 28, 198), outline=(255, 255, 255, 42), width=1.2)
        dot_color = CORAL if self.device.muted else EMERALD
        c.circle(26, h / 2, 6, dot_color)
        txt = "%s  ·  %s" % (now_str, next_timer) if next_timer else now_str
        c.text((46, h / 2), txt, round(side * 0.032), TEXT_PRIMARY, bold=True, anchor="lm", max_w=w - 92)
        c.icon(_icon_chevron, w - 26, h / 2, 11, TEXT_MUTED, direction="up")
        c.hit((0, 0, w, h), "pill")
        return c

    def _next_timer_label(self):
        if not self.device.timers:
            return ""
        soonest = min(v[0] for v in self.device.timers.values())
        return _fmt_remaining(soonest - time.time())

    # ----- View 2: Frosted-Glass Quick Controls Dock

    def _render_dock(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        w = min(sw - 2 * round(side * 0.03), round(sw * 0.94))
        pad = round(side * 0.036)
        gap = round(side * 0.022)
        settings = self.device.store.settings()
        volume = float(settings.get("volume", 0.8))
        brightness = int(settings.get("screen", {}).get("brightness", 100))
        captions_on = bool(settings.get("captions", {}).get("on"))
        muted = self.device.muted
        state = self.device.state
        busy = self.device.conversation is not None and self.device.conversation.busy

        # Layout vertical rhythm.
        handle_h = 26
        header_h = 56
        hero_h = 84
        slider_h = 68
        tile_h = 104
        h = pad + handle_h + header_h + gap + hero_h + gap + slider_h + gap + slider_h + gap + tile_h * 2 + gap + pad
        c = _Canvas(w, h, screen, anchor="bottom")
        c.panel(radius=34)

        y = pad
        # Grab handle pill at top center.
        c.rect((w / 2 - 34, y, w / 2 + 34, y + 7), radius=4, fill=(255, 255, 255, 72))
        y += handle_h

        # Header: active character name + mood chip on left, live time + close button on right.
        cid = self.device.active_id()
        char_name = self.device.characters.manifest(cid).get("name", cid) if cid else "No character"
        mood = (self.device.animation or {}).get("mood") or getattr(self.device.stage, "expression", None) or "neutral"
        c.text((pad, y + 18), char_name, round(side * 0.044), TEXT_PRIMARY, bold=True, anchor="lm", max_w=w * 0.52)
        c.text((pad, y + 44), "%s · %s" % (mood.capitalize(), state), round(side * 0.027), TEXT_MUTED, bold=False, anchor="lm", max_w=w * 0.52)

        # Clock + close pill.
        close_r = 22
        close_cx, close_cy = w - pad - close_r, y + 26
        c.circle(close_cx, close_cy, close_r, GLASS_CARD_HI, outline=GLASS_BORDER)
        c.icon(_icon_close, close_cx, close_cy, 11, TEXT_PRIMARY)
        c.hit((close_cx - close_r - 8, close_cy - close_r - 8, close_cx + close_r + 8, close_cy + close_r + 8), "close")
        c.text((close_cx - close_r - 18, close_cy), time.strftime("%H:%M"), round(side * 0.036), TEXT_PRIMARY, bold=True, anchor="rm")
        y += header_h + gap

        # Hero Row: Talk / Stop button + Mute button.
        mute_w = round((w - 2 * pad - gap) * 0.29)
        talk_w = (w - 2 * pad - gap) - mute_w
        if busy or state == "speaking":
            talk_bg, talk_txt = CORAL_BG, "Stop Speaking"
        elif self.device.recording is not None:
            talk_bg, talk_txt = CYAN_BG, "Tap to Send"
        elif self.device.listening or state == "listening":
            talk_bg, talk_txt = CYAN_BG, "Listening · Stop"
        else:
            talk_bg, talk_txt = ACCENT_BG, "Tap to Talk"
        talk_box = (pad, y, pad + talk_w, y + hero_h)
        c.rect(talk_box, radius=24, fill=talk_bg, outline=(255, 255, 255, 65), width=1.5)
        c.icon(_icon_mic, pad + 38, y + hero_h / 2, 18, TEXT_PRIMARY, muted=muted and talk_txt == "Tap to Talk")
        c.text((pad + 70, y + hero_h / 2), talk_txt, round(side * 0.038), TEXT_PRIMARY, bold=True, anchor="lm", max_w=talk_w - 86)
        c.hit(talk_box, "talk")

        mute_x = pad + talk_w + gap
        mute_box = (mute_x, y, mute_x + mute_w, y + hero_h)
        c.rect(mute_box, radius=24, fill=CORAL_BG if muted else GLASS_CARD,
               outline=CORAL if muted else GLASS_BORDER, width=1.5)
        c.icon(_icon_mic, mute_x + mute_w / 2, y + hero_h * 0.36, 15, TEXT_PRIMARY, muted=muted)
        c.text((mute_x + mute_w / 2, y + hero_h * 0.74), "Muted" if muted else "Mute",
               round(side * 0.028), TEXT_PRIMARY if muted else TEXT_MUTED, bold=True, anchor="mm")
        c.hit(mute_box, "mute")
        y += hero_h + gap

        # Interactive Sliders: Volume & Brightness.
        self._draw_slider(c, (pad, y, w - pad, y + slider_h), "Volume", volume, "%d%%" % round(volume * 100),
                          _icon_speaker, {"level": volume}, "slider_volume", side)
        y += slider_h + gap
        self._draw_slider(c, (pad, y, w - pad, y + slider_h), "Brightness", (brightness - 10) / 90.0, "%d%%" % brightness,
                          _icon_sun, {}, "slider_brightness", side)
        y += slider_h + gap

        # 2x3 Quick Action Tile Grid.
        chars_count = len(self.device.characters.ids())
        next_t = self._next_timer_label()
        timers_sub = next_t if next_t else ("%d active" % len(self.device.timers) if self.device.timers else "Set timer")
        wifi_sub = self.wifi_address if self.wifi_connected and self.wifi_address else ("Connected" if self.wifi_connected else "Setup")
        tiles = [
            ("Characters", "%d installed" % chars_count, _icon_people, {}, "open_characters", False),
            ("Captions", "On" if captions_on else "Off", _icon_captions, {}, "captions", captions_on),
            ("Sleep", "Tap to wake", _icon_moon, {"bg": GLASS_CARD}, "sleep", False),
            ("Timers", timers_sub, _icon_timer, {}, "open_timers", bool(self.device.timers)),
            ("Wi-Fi", wifi_sub, _icon_wifi, {"strength": 100 if self.wifi_connected else 40}, "open_wifi", self.wifi_connected),
            ("More & QR", "Moods · Web", _icon_qr, {}, "open_status", False),
        ]
        col_w = (w - 2 * pad - 2 * gap) / 3.0
        for idx, (title, sub, icon_fn, icon_kw, act, active) in enumerate(tiles):
            row, col = divmod(idx, 3)
            tx = pad + col * (col_w + gap)
            ty = y + row * (tile_h + gap)
            box = (tx, ty, tx + col_w, ty + tile_h)
            fill = (44, 58, 108, 236) if active else GLASS_CARD
            outline = ACCENT if active else GLASS_BORDER
            c.rect(box, radius=22, fill=fill, outline=outline, width=1.6 if active else 1.0)
            kw = dict(icon_kw)
            if icon_fn is _icon_moon:
                kw["bg"] = fill
            c.icon(icon_fn, tx + col_w / 2, ty + 32, 16, TEXT_PRIMARY if active else (218, 224, 242, 255), **kw)
            c.text((tx + col_w / 2, ty + 64), title, round(side * 0.030), TEXT_PRIMARY, bold=True, anchor="mm", max_w=col_w - 16)
            c.text((tx + col_w / 2, ty + 86), sub, round(side * 0.023),
                   (188, 206, 255, 255) if active else TEXT_MUTED, bold=False, anchor="mm", max_w=col_w - 16)
            c.hit(box, act)
        return c

    def _draw_slider(self, c, box, label, frac, readout, icon_fn, icon_kw, action, side):
        x0, y0, x1, y1 = box
        frac = max(0.0, min(1.0, float(frac)))
        c.rect(box, radius=20, fill=GLASS_CARD, outline=GLASS_BORDER)
        cy = (y0 + y1) / 2.0
        c.icon(icon_fn, x0 + 30, cy, 15, TEXT_PRIMARY, **icon_kw)
        c.text((x0 + 58, y0 + 21), label, round(side * 0.026), TEXT_MUTED, bold=True, anchor="lm")
        c.text((x1 - 20, y0 + 21), readout, round(side * 0.026), TEXT_PRIMARY, bold=True, anchor="rm")
        # Track & thumb (inset so the circular thumb never crowds the card edge at 0% or 100%).
        tx0, tx1 = x0 + 62, x1 - 28
        ty = y0 + 46
        th = 10
        c.rect((tx0, ty - th / 2, tx1, ty + th / 2), radius=5, fill=(255, 255, 255, 34))
        fill_x = tx0 + (tx1 - tx0) * frac
        if fill_x > tx0 + 6:
            c.rect((tx0, ty - th / 2, fill_x, ty + th / 2), radius=5, fill=ACCENT)
        c.circle(fill_x, ty, 11.5, TEXT_PRIMARY, outline=ACCENT, width=2.5)
        # Register generous vertical hit region along the track width.
        c.hit((tx0, y0, tx1, y1), action)

    # ----- View 3: Character Switcher Sheet

    def _render_characters(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        w = min(sw - 2 * round(side * 0.03), round(sw * 0.94))
        pad = round(side * 0.038)
        gap = round(side * 0.024)
        chars = self.device.characters.list()
        active_id = self.device.active_id()
        per_page = 4
        pages = max(1, (len(chars) + per_page - 1) // per_page)
        self.char_page = min(self.char_page, pages - 1)
        shown = chars[self.char_page * per_page:(self.char_page + 1) * per_page]

        header_h = 68
        card_h = 228 if shown else 160
        rows = 2 if len(shown) > 2 else 1
        footer_h = 62 if pages > 1 else 16
        h = pad + 26 + header_h + gap + rows * card_h + (gap if rows == 2 else 0) + gap + footer_h + pad
        c = _Canvas(w, h, screen, anchor="bottom")
        c.panel(radius=34)

        y = self._sheet_header(c, w, pad, side, "Characters", "%d installed" % len(chars))
        y += gap

        if not shown:
            box = (pad, y, w - pad, y + 140)
            c.rect(box, radius=22, fill=GLASS_CARD, outline=GLASS_BORDER)
            c.text((w / 2, y + 50), "No characters installed yet", round(side * 0.038), TEXT_PRIMARY, bold=True, anchor="mm")
            c.text((w / 2, y + 92), "Open More & QR to add one from your phone or computer",
                   round(side * 0.027), TEXT_MUTED, bold=False, anchor="mm", max_w=w - 2 * pad - 24)
            return c

        col_w = (w - 2 * pad - gap) / 2.0
        for i, item in enumerate(shown):
            r, col = divmod(i, 2)
            cx0 = pad + col * (col_w + gap)
            cy0 = y + r * (card_h + gap)
            box = (cx0, cy0, cx0 + col_w, cy0 + card_h)
            is_active = item["id"] == active_id
            c.rect(box, radius=24, fill=(38, 50, 92, 238) if is_active else GLASS_CARD,
                   outline=ACCENT if is_active else GLASS_BORDER, width=2.5 if is_active else 1.0)
            # Preview thumbnail or monogram tile.
            thumb_pad = 14
            thumb_h = card_h - 86
            tbox = (cx0 + thumb_pad, cy0 + thumb_pad, cx0 + col_w - thumb_pad, cy0 + thumb_pad + thumb_h)
            preview_img = self._load_preview(item["id"])
            if preview_img is not None:
                c.paste_rounded(preview_img, tbox, radius=16)
            else:
                hue_palette = [(76, 98, 178, 255), (124, 84, 178, 255), (60, 140, 160, 255), (178, 92, 132, 255)]
                bg_col = hue_palette[sum(ord(ch) for ch in item["id"]) % len(hue_palette)]
                c.rect(tbox, radius=16, fill=bg_col)
                initial = (item.get("name") or item["id"])[:1].upper()
                c.text(((tbox[0] + tbox[2]) / 2, (tbox[1] + tbox[3]) / 2), initial, round(side * 0.095), TEXT_PRIMARY, bold=True, anchor="mm")
            # Format pill badge in top-right of card.
            badge = "3D" if item.get("drawing") == "vrm" else "2D"
            c.rect((tbox[2] - 46, tbox[1] + 8, tbox[2] - 8, tbox[1] + 34), radius=10, fill=(14, 16, 26, 200))
            c.text((tbox[2] - 27, tbox[1] + 21), badge, round(side * 0.022), TEXT_PRIMARY, bold=True, anchor="mm")

            # Character name + active tag.
            c.text((cx0 + col_w / 2, cy0 + card_h - 46), item.get("name") or item["id"],
                   round(side * 0.034), TEXT_PRIMARY, bold=True, anchor="mm", max_w=col_w - 24)
            sub = "Active" if is_active else "Tap to switch"
            c.text((cx0 + col_w / 2, cy0 + card_h - 22), sub,
                   round(side * 0.023), EMERALD if is_active else TEXT_MUTED, bold=is_active, anchor="mm")
            c.hit(box, "select_character", item["id"])

        if pages > 1:
            fy = y + rows * card_h + (gap if rows == 2 else 0) + gap
            self._draw_pager(c, w, fy, pad, side, self.char_page, pages, "char_prev", "char_next")
        return c

    def _load_preview(self, cid):
        for name in ("preview.png", "preview.webp"):
            path = self.device.characters.file(cid, name)
            if os.path.exists(path):
                try:
                    with Image.open(path) as im:
                        return im.copy()
                except OSError:
                    pass
        return None

    # ----- View 4: Timers, Alarms & Clock Sheet

    def _render_timers(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        w = min(sw - 2 * round(side * 0.03), round(sw * 0.94))
        pad = round(side * 0.038)
        gap = round(side * 0.022)
        now_dt = datetime.datetime.now()
        items = sorted(((v[0], k, v[2]) for k, v in self.device.timers.items()))

        clock_h = 128
        quick_h = 68
        row_h = 74
        shown = items[:4]
        list_h = (len(shown) * (row_h + 12)) if shown else 72
        h = pad + 26 + 68 + gap + clock_h + gap + 30 + quick_h + gap + list_h + pad
        c = _Canvas(w, h, screen, anchor="bottom")
        c.panel(radius=34)

        y = self._sheet_header(c, w, pad, side, "Timers & Clock", "%d active" % len(items) if items else "No timers running")
        y += gap

        # Large digital clock hero card.
        c.rect((pad, y, w - pad, y + clock_h), radius=24, fill=GLASS_CARD, outline=GLASS_BORDER)
        c.text((w / 2, y + 48), now_dt.strftime("%H:%M"), round(side * 0.092), TEXT_PRIMARY, bold=True, anchor="mm")
        c.text((w / 2, y + 100), now_dt.strftime("%A, %d %B"), round(side * 0.031), TEXT_MUTED, bold=False, anchor="mm")
        y += clock_h + gap

        # Quick-set timer pills.
        c.text((pad, y + 12), "Quick timer", round(side * 0.028), TEXT_MUTED, bold=True, anchor="lm")
        y += 30
        bw = (w - 2 * pad - (len(QUICK_TIMERS) - 1) * 12) / len(QUICK_TIMERS)
        for i, (secs, lbl) in enumerate(QUICK_TIMERS):
            bx = pad + i * (bw + 12)
            box = (bx, y, bx + bw, y + quick_h)
            c.rect(box, radius=18, fill=(44, 56, 98, 232), outline=(126, 152, 255, 110), width=1.4)
            c.text((bx + bw / 2, y + quick_h / 2), "+" + lbl, round(side * 0.034), TEXT_PRIMARY, bold=True, anchor="mm")
            c.hit(box, "quick_timer", (secs, lbl))
        y += quick_h + gap

        if not shown:
            c.rect((pad, y, w - pad, y + 66), radius=18, fill=GLASS_CARD)
            c.text((w / 2, y + 33), "Tap a button above or ask the character to set a timer",
                   round(side * 0.026), TEXT_MUTED, bold=False, anchor="mm", max_w=w - 2 * pad - 24)
        else:
            now_ts = time.time()
            for due, label, kind in shown:
                box = (pad, y, w - pad, y + row_h)
                c.rect(box, radius=20, fill=GLASS_CARD, outline=GLASS_BORDER)
                c.icon(_icon_timer, pad + 32, y + row_h / 2, 15, CYAN if kind == "timer" else AMBER)
                c.text((pad + 62, y + 26), label, round(side * 0.032), TEXT_PRIMARY, bold=True, anchor="lm", max_w=w - 2 * pad - 230)
                c.text((pad + 62, y + 52), kind.capitalize(), round(side * 0.023), TEXT_MUTED, bold=False, anchor="lm")
                c.text((w - pad - 90, y + row_h / 2), _fmt_remaining(due - now_ts),
                       round(side * 0.036), CYAN, bold=True, anchor="rm")
                cbox = (w - pad - 72, y + 14, w - pad - 14, y + row_h - 14)
                c.rect(cbox, radius=14, fill=CORAL_BG)
                c.icon(_icon_close, (cbox[0] + cbox[2]) / 2, (cbox[1] + cbox[3]) / 2, 11, TEXT_PRIMARY)
                c.hit(cbox, "cancel_timer", label)
                y += row_h + 12
        return c

    # ----- View 5: Moods, Quick Toggles & Settings QR Sheet

    def _render_status(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        w = min(sw - 2 * round(side * 0.03), round(sw * 0.94))
        pad = round(side * 0.038)
        gap = round(side * 0.022)
        settings = self.device.store.settings()
        spoken_touch = bool(settings.get("touch", {}).get("spoken_reactions", True))
        wake_on = bool(settings.get("wake_word", {}).get("on", False))
        heard_on = bool(settings.get("captions", {}).get("heard", False))
        cur_mood = (self.device.animation or {}).get("mood") or getattr(self.device.stage, "expression", None) or "neutral"

        mood_h = 64
        toggle_h = 66
        qr_card_h = 204
        h = pad + 26 + 68 + gap + 28 + mood_h + gap + 3 * (toggle_h + 10) + gap + qr_card_h + pad
        c = _Canvas(w, h, screen, anchor="bottom")
        c.panel(radius=34)

        ver = updates_mod.current_version()
        ver_label = "Dev build" if ver == "0" else ("v%s" % ver)
        y = self._sheet_header(c, w, pad, side, "Moods & Console", ver_label)
        y += gap

        # Quick Mood / Gesture Strip.
        c.text((pad, y + 10), "Express", round(side * 0.028), TEXT_MUTED, bold=True, anchor="lm")
        y += 28
        bw = (w - 2 * pad - (len(QUICK_MOODS) - 1) * 10) / len(QUICK_MOODS)
        for i, (key, lbl) in enumerate(QUICK_MOODS):
            bx = pad + i * (bw + 10)
            box = (bx, y, bx + bw, y + mood_h)
            selected = key == cur_mood
            c.rect(box, radius=18, fill=ACCENT_BG if selected else GLASS_CARD,
                   outline=ACCENT if selected else GLASS_BORDER, width=1.6 if selected else 1.0)
            c.text((bx + bw / 2, y + mood_h / 2), lbl, round(side * 0.028), TEXT_PRIMARY, bold=True, anchor="mm", max_w=bw - 10)
            c.hit(box, "mood", key)
        y += mood_h + gap

        # Quick Feature Toggles.
        toggles = [
            ("Spoken touch reactions", "Reply aloud when petted or poked", spoken_touch, "toggle_spoken_touch"),
            ("Wake word", "Listen when you say its name", wake_on, "toggle_wake_word"),
            ("Show what it heard", "Display your words at the top", heard_on, "toggle_heard_captions"),
        ]
        for title, sub, is_on, act in toggles:
            box = (pad, y, w - pad, y + toggle_h)
            c.rect(box, radius=20, fill=GLASS_CARD, outline=GLASS_BORDER)
            c.text((pad + 20, y + 24), title, round(side * 0.031), TEXT_PRIMARY, bold=True, anchor="lm", max_w=w - 2 * pad - 110)
            c.text((pad + 20, y + 48), sub, round(side * 0.022), TEXT_MUTED, bold=False, anchor="lm", max_w=w - 2 * pad - 110)
            # iOS-style switch pill.
            sw_x1 = w - pad - 18
            sw_x0 = sw_x1 - 68
            sw_y0 = y + toggle_h / 2 - 19
            sw_y1 = y + toggle_h / 2 + 19
            c.rect((sw_x0, sw_y0, sw_x1, sw_y1), radius=19, fill=EMERALD if is_on else (72, 78, 102, 230))
            knob_x = (sw_x1 - 19) if is_on else (sw_x0 + 19)
            c.circle(knob_x, y + toggle_h / 2, 14, TEXT_PRIMARY)
            c.hit(box, act)
            y += toggle_h + 10

        y += gap - 10
        # Web Settings Console QR Card.
        qbox = (pad, y, w - pad, y + qr_card_h)
        c.rect(qbox, radius=24, fill=GLASS_CARD, outline=GLASS_BORDER)
        url = ("http://%s" % self.wifi_address) if self.wifi_address else "http://companion.local"
        qr_img = screen_mod.qr_code(url, box=6)
        qr_side = qr_card_h - 32
        if qr_img is not None:
            c.paste_rounded(qr_img, (pad + 16, y + 16, pad + 16 + qr_side, y + 16 + qr_side), radius=14, sharp=True)
        tx = pad + qr_side + 36 if qr_img is not None else pad + 24
        max_tw = w - pad - tx - 14
        c.text((tx, y + 40), "Settings page", round(side * 0.036), TEXT_PRIMARY, bold=True, anchor="lm", max_w=max_tw)
        c.text((tx, y + 76), "Scan to manage AI keys, memory & voices:", round(side * 0.023), TEXT_MUTED, bold=False, anchor="lm", max_w=max_tw)
        c.text((tx, y + 114), url, round(side * 0.030), CYAN, bold=True, anchor="lm", max_w=max_tw)
        c.text((tx, y + 148), "USB: http://10.12.194.1", round(side * 0.023), TEXT_MUTED, bold=False, anchor="lm", max_w=max_tw)
        c.text((tx, y + 178), "Up %dm · %s" % (max(1, round((time.time() - self.device.started) / 60)), self.device.timezone() or "Local time"),
               round(side * 0.021), TEXT_DIM, bold=False, anchor="lm", max_w=max_tw)
        return c

    # ----- View 6: On-Screen Wi-Fi Picker Sheet

    def _render_wifi(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        w = min(sw - 2 * round(side * 0.03), round(sw * 0.94))
        pad = round(side * 0.038)
        gap = round(side * 0.020)
        per_page = 5
        pages = max(1, (len(self.wifi_networks) + per_page - 1) // per_page)
        self.wifi_page = min(self.wifi_page, pages - 1)
        shown = self.wifi_networks[self.wifi_page * per_page:(self.wifi_page + 1) * per_page]

        status_h = 66
        row_h = 74
        rows_h = (len(shown) * (row_h + 10)) if shown else 110
        footer_h = 64
        pager_h = 56 if pages > 1 else 0
        h = pad + 26 + 68 + gap + status_h + gap + rows_h + (gap + pager_h if pager_h else 0) + gap + footer_h + pad
        c = _Canvas(w, h, screen, anchor="bottom")
        c.panel(radius=34)

        sub = "Scanning nearby networks…" if self.wifi_scanning else (
            ("Connected · " + self.wifi_address) if self.wifi_connected and self.wifi_address else
            ("Connected" if self.wifi_connected else "Choose your home Wi-Fi")
        )
        y = self._sheet_header(c, w, pad, side, "Wi-Fi", sub)
        y += gap

        # Status + Scan bar.
        sbox = (pad, y, w - pad, y + status_h)
        c.rect(sbox, radius=20, fill=GLASS_CARD, outline=CORAL if self.wifi_error else GLASS_BORDER)
        st_text = self.wifi_error or ("Looking for networks…" if self.wifi_scanning else "%d networks found" % len(self.wifi_networks))
        c.text((pad + 20, y + status_h / 2), st_text, round(side * 0.027),
               CORAL if self.wifi_error else TEXT_MUTED, bold=bool(self.wifi_error), anchor="lm", max_w=w - 2 * pad - 150)
        scan_box = (w - pad - 122, y + 11, w - pad - 12, y + status_h - 11)
        c.rect(scan_box, radius=14, fill=ACCENT_BG if not self.wifi_scanning else GLASS_CARD_HI)
        c.text(((scan_box[0] + scan_box[2]) / 2, y + status_h / 2), "Scanning" if self.wifi_scanning else "Scan",
               round(side * 0.027), TEXT_PRIMARY, bold=True, anchor="mm")
        c.hit(scan_box, "wifi_scan")
        y += status_h + gap

        if not shown:
            c.rect((pad, y, w - pad, y + 96), radius=20, fill=GLASS_CARD)
            msg = "Searching for Wi-Fi networks…" if self.wifi_scanning else "No networks found yet. Tap Scan or enter a network name below."
            c.text((w / 2, y + 48), msg, round(side * 0.027), TEXT_MUTED, bold=False, anchor="mm", max_w=w - 2 * pad - 32)
            y += 110
        else:
            for net in shown:
                box = (pad, y, w - pad, y + row_h)
                c.rect(box, radius=20, fill=GLASS_CARD, outline=GLASS_BORDER)
                c.icon(_icon_wifi, pad + 34, y + row_h / 2, 16, TEXT_PRIMARY,
                       strength=int(net.get("signal", 80)), locked=bool(net.get("secure")))
                c.text((pad + 70, y + 27), net["ssid"], round(side * 0.034), TEXT_PRIMARY, bold=True, anchor="lm", max_w=w - 2 * pad - 150)
                meta = "%d%% · %s" % (int(net.get("signal", 0)), "Secured" if net.get("secure") else "Open")
                c.text((pad + 70, y + 53), meta, round(side * 0.023), TEXT_MUTED, bold=False, anchor="lm")
                c.icon(_icon_chevron, w - pad - 28, y + row_h / 2, 11, TEXT_MUTED, direction="right")
                c.hit(box, "wifi_pick", net)
                y += row_h + 10

        if pager_h:
            y += gap
            self._draw_pager(c, w, y, pad, side, self.wifi_page, pages, "wifi_prev", "wifi_next")
            y += pager_h

        y += gap
        hbox = (pad, y, w - pad, y + footer_h)
        c.rect(hbox, radius=20, fill=GLASS_CARD_HI, outline=GLASS_BORDER)
        c.text((w / 2, y + footer_h / 2), "Enter hidden network name…", round(side * 0.030), TEXT_PRIMARY, bold=True, anchor="mm")
        c.hit(hbox, "wifi_hidden")
        return c

    # ----- View 7: Polished Full QWERTY On-Screen Touch Keyboard

    def _render_keyboard(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        w = min(sw - 2 * round(side * 0.03), round(sw * 0.94))
        pad = round(side * 0.030)
        gap = round(side * 0.014)

        is_pw = self.kb_target == "wifi_password"
        title = ("Join %s" % self.kb_ssid) if is_pw else "Hidden Wi-Fi Network"
        sub = "Connecting…" if self.kb_busy else ("Enter password (8–63 characters)" if is_pw else "Enter network name (SSID)")

        field_h = 74
        err_h = 34 if self.kb_error else 0
        key_h = 72
        rows = KB_ALPHA_ROWS if self.kb_layout == "abc" else (KB_NUM_ROWS if self.kb_layout == "num" else KB_SYM_ROWS)
        keys_h = len(rows) * key_h + (len(rows) - 1) * gap
        h = pad + 26 + 66 + gap + field_h + (err_h + 6 if err_h else 0) + gap * 2 + keys_h + pad
        c = _Canvas(w, h, screen, anchor="bottom")
        c.panel(radius=30)

        y = self._sheet_header(c, w, pad, side, title, sub, back_action="kb_back_view")
        y += gap

        # Text / password display box with Show/Hide eye toggle.
        fbox = (pad, y, w - pad, y + field_h)
        c.rect(fbox, radius=18, fill=(11, 13, 22, 245), outline=CORAL if self.kb_error else ACCENT, width=1.8)
        if is_pw and not self.kb_show_text:
            shown_txt = "•" * len(self.kb_text)
        else:
            shown_txt = self.kb_text
        if shown_txt:
            display = shown_txt[-26:] + "|"
            tcol = TEXT_PRIMARY
        else:
            display = "Password" if is_pw else "Network name"
            tcol = TEXT_DIM
        c.text((pad + 20, y + field_h / 2), display, round(side * 0.036), tcol, bold=False, anchor="lm", max_w=w - 2 * pad - 120)

        if is_pw:
            eye_box = (w - pad - 72, y + 10, w - pad - 10, y + field_h - 10)
            c.rect(eye_box, radius=14, fill=GLASS_CARD_HI)
            c.icon(_icon_eye, (eye_box[0] + eye_box[2]) / 2, (eye_box[1] + eye_box[3]) / 2, 15,
                   TEXT_PRIMARY if self.kb_show_text else TEXT_MUTED, shown=self.kb_show_text)
            c.hit(eye_box, "kb_toggle_show")
        y += field_h

        if self.kb_error:
            y += 6
            c.text((pad + 8, y + err_h / 2), self.kb_error, round(side * 0.025), CORAL, bold=True, anchor="lm", max_w=w - 2 * pad - 16)
            y += err_h

        y += gap * 2

        # Keyboard rows.
        inner_w = w - 2 * pad
        can_submit = (not self.kb_busy) and (bool(self.kb_text.strip()) if not is_pw else (len(self.kb_text) == 0 or len(self.kb_text) >= 8))
        for row_idx, row in enumerate(rows):
            total_w = sum(k[2] for k in row)
            # Slightly inset the middle 9-key alpha row like a real phone keyboard.
            row_inset = round(inner_w * 0.04) if (self.kb_layout == "abc" and row_idx == 1) else 0
            avail = inner_w - 2 * row_inset - gap * (len(row) - 1)
            kx = pad + row_inset
            for key_id, raw_label, weight in row:
                kw = avail * (weight / total_w)
                kbox = (kx, y, kx + kw, y + key_h)
                is_submit = key_id == "submit"
                is_mod = key_id in ("shift", "back", "mode_num", "mode_sym", "mode_abc", "clear")
                if is_submit:
                    bg = ACCENT_BG if can_submit else (48, 54, 78, 200)
                    label = ("…" if self.kb_busy else ("Connect" if is_pw else "Next"))
                elif key_id == "shift" and (self.kb_shift or self.kb_caps):
                    bg = ACCENT_BG
                    label = ""
                elif is_mod:
                    bg = KEY_MOD
                    label = raw_label
                else:
                    bg = KEY_BG
                    label = raw_label.upper() if (self.kb_layout == "abc" and (self.kb_shift or self.kb_caps) and len(raw_label) == 1) else raw_label
                c.rect(kbox, radius=14, fill=bg, outline=(255, 255, 255, 28), width=1.0)
                cx_k, cy_k = kx + kw / 2, y + key_h / 2
                if key_id == "back":
                    c.icon(_icon_backspace, cx_k, cy_k, 16, TEXT_PRIMARY)
                elif key_id == "shift":
                    c.icon(_icon_shift, cx_k, cy_k, 15, TEXT_PRIMARY, filled=(self.kb_shift or self.kb_caps), locked=self.kb_caps)
                else:
                    fsize = round(side * (0.029 if len(label) > 1 else 0.039))
                    c.text((cx_k, cy_k), label, fsize, TEXT_PRIMARY if (not is_submit or can_submit) else TEXT_MUTED,
                           bold=(is_submit or len(label) == 1), anchor="mm", max_w=kw - 10)
                c.hit(kbox, "kb_key", key_id)
                kx += kw + gap
            y += key_h + gap
        return c

    # ----- shared sheet chrome

    def _sheet_header(self, c, w, pad, side, title, subtitle, back_action=None):
        y = pad
        c.rect((w / 2 - 34, y, w / 2 + 34, y + 7), radius=4, fill=(255, 255, 255, 72))
        y += 26
        tx = pad
        if back_action:
            br = 22
            bcx, bcy = pad + br, y + 32
            c.circle(bcx, bcy, br, GLASS_CARD_HI, outline=GLASS_BORDER)
            c.icon(_icon_chevron, bcx, bcy, 12, TEXT_PRIMARY, direction="left")
            c.hit((bcx - br - 8, bcy - br - 8, bcx + br + 8, bcy + br + 8), back_action)
            tx = pad + br * 2 + 16
        close_r = 22
        close_cx, close_cy = w - pad - close_r, y + 32
        c.circle(close_cx, close_cy, close_r, GLASS_CARD_HI, outline=GLASS_BORDER)
        c.icon(_icon_close, close_cx, close_cy, 11, TEXT_PRIMARY)
        c.hit((close_cx - close_r - 8, close_cy - close_r - 8, close_cx + close_r + 8, close_cy + close_r + 8), "close")
        max_tw = close_cx - close_r - tx - 14
        c.text((tx, y + 20), title, round(side * 0.044), TEXT_PRIMARY, bold=True, anchor="lm", max_w=max_tw)
        c.text((tx, y + 50), subtitle, round(side * 0.026), TEXT_MUTED, bold=False, anchor="lm", max_w=max_tw)
        return y + 66

    def _draw_pager(self, c, w, y, pad, side, page, pages, prev_act, next_act):
        bh = 50
        bw = 126
        pbox = (pad, y, pad + bw, y + bh)
        nbox = (w - pad - bw, y, w - pad, y + bh)
        c.rect(pbox, radius=16, fill=GLASS_CARD_HI, outline=GLASS_BORDER)
        c.text((pad + bw / 2, y + bh / 2), "Prev", round(side * 0.029), TEXT_PRIMARY, bold=True, anchor="mm")
        c.hit(pbox, prev_act)
        c.rect(nbox, radius=16, fill=GLASS_CARD_HI, outline=GLASS_BORDER)
        c.text((w - pad - bw / 2, y + bh / 2), "Next", round(side * 0.029), TEXT_PRIMARY, bold=True, anchor="mm")
        c.hit(nbox, next_act)
        # Centered pagination dots.
        spacing = 18
        start_x = w / 2 - (pages - 1) * spacing / 2
        for i in range(pages):
            c.circle(start_x + i * spacing, y + bh / 2, 5 if i == page else 4,
                     ACCENT if i == page else (255, 255, 255, 65))
