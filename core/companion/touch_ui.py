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
import json
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

QUICK_TREATS = (
    ("tea", "Warm Tea"),
    ("snack", "Snack"),
    ("star", "Gold Star"),
    ("high_five", "High-5"),
)

QUICK_PROMPTS = (
    ("How's my day?", "How's my day looking? Remind me of anything I should keep in mind."),
    ("Fun fact", "Tell me a short, surprising fun fact."),
    ("25m focus", "Set a 25 minute focus timer for me."),
    ("Cheer me up", "Say something short and encouraging to brighten my mood."),
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


def _wrap_lines(draw, text, font, max_w, max_lines=2):
    """Wrap text into at most max_lines lines within max_w pixels, ellipsizing the final line if needed."""
    words = " ".join(str(text or "").split()).split(" ")
    if not words or words == [""]:
        return [""]
    lines = []
    cur = ""
    for i, word in enumerate(words):
        cand = (cur + " " + word).strip() if cur else word
        if draw.textlength(cand, font=font) <= max_w:
            cur = cand
            continue
        if len(lines) + 1 >= max_lines:
            rest = (cur + " " + " ".join(words[i:])).strip() if cur else " ".join(words[i:])
            lines.append(_fit_text(draw, rest, font, max_w))
            return lines
        if cur:
            lines.append(cur)
            cur = word
        else:
            lines.append(_fit_text(draw, word, font, max_w))
            cur = ""
    if cur:
        lines.append(_fit_text(draw, cur, font, max_w))
    return lines[:max_lines] or [""]


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


def _icon_chat(draw, cx, cy, r, color):
    w = max(2, round(r * 0.14))
    draw.rounded_rectangle((cx - r * 0.74, cy - r * 0.56, cx + r * 0.74, cy + r * 0.38),
                           radius=r * 0.28, outline=color, width=w)
    draw.polygon([(cx - r * 0.36, cy + r * 0.34), (cx - r * 0.52, cy + r * 0.70), (cx - r * 0.06, cy + r * 0.36)],
                 fill=color)
    for ox in (-r * 0.32, 0.0, r * 0.32):
        d = r * 0.09
        draw.ellipse((cx + ox - d, cy - r * 0.09 - d, cx + ox + d, cy - r * 0.09 + d), fill=color)


def _icon_bluetooth(draw, cx, cy, r, color):
    w = max(2, round(r * 0.14))
    pts = [
        (cx - r * 0.36, cy - r * 0.34),
        (cx + r * 0.42, cy + r * 0.32),
        (cx, cy + r * 0.74),
        (cx, cy - r * 0.74),
        (cx + r * 0.42, cy - r * 0.32),
        (cx - r * 0.36, cy + r * 0.34),
    ]
    draw.line(pts, fill=color, width=w, joint="curve")


def _icon_heart(draw, cx, cy, r, color):
    # Classic two-lobe heart drawn with clean vector primitives.
    lr = r * 0.36
    draw.ellipse((cx - r * 0.62, cy - r * 0.52, cx - r * 0.62 + lr * 2, cy - r * 0.52 + lr * 2), fill=color)
    draw.ellipse((cx + r * 0.62 - lr * 2, cy - r * 0.52, cx + r * 0.62, cy - r * 0.52 + lr * 2), fill=color)
    draw.polygon([(cx - r * 0.60, cy - r * 0.08), (cx + r * 0.60, cy - r * 0.08), (cx, cy + r * 0.66)], fill=color)


def _icon_sparkle(draw, cx, cy, r, color):
    d = r * 0.72
    m = r * 0.20
    pts = [
        (cx, cy - d), (cx + m, cy - m), (cx + d, cy), (cx + m, cy + m),
        (cx, cy + d), (cx - m, cy + m), (cx - d, cy), (cx - m, cy - m),
    ]
    draw.polygon(pts, fill=color)


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

    def line(self, pts, color=GLASS_BORDER, width=1.5):
        s = self.s
        scaled = [(x * s, y * s) for x, y in pts]
        self.g.line(scaled, fill=color, width=max(1, round(width * s)), joint="curve")

    def paste_rounded(self, img, box, radius=14, sharp=False):
        s = self.s
        x0, y0, x1, y1 = (v * s for v in box)
        tw, th = max(1, int(round(x1 - x0))), max(1, int(round(y1 - y0)))
        fitted = ImageOps.fit(img.convert("RGBA"), (tw, th), method=Image.NEAREST if sharp else Image.LANCZOS)
        mask = Image.new("L", (tw, th), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw - 1, th - 1), radius=radius * s, fill=255)
        self.hi.paste(fitted, (int(round(x0)), int(round(y0))), mask)

    def text(self, pos, value, size, color=TEXT_PRIMARY, bold=True, anchor="la", max_w=None):
        self._texts.append(("line", pos, str(value), max(10, round(size)), color, bold, anchor, max_w, 1, 0))

    def text_tail(self, pos, value, size, color=TEXT_PRIMARY, bold=False, anchor="lm", max_w=200):
        self._texts.append(("tail", pos, str(value), max(10, round(size)), color, bold, anchor, max_w, 1, 0))

    def text_wrapped(self, pos, value, size, color=TEXT_PRIMARY, bold=False, anchor="la", max_w=200, max_lines=2, line_gap=4):
        self._texts.append(("wrap", pos, str(value), max(10, round(size)), color, bold, anchor, max_w, max_lines, line_gap))

    def finish_image(self):
        img = self.hi.resize((self.w, self.h), Image.LANCZOS)
        draw = ImageDraw.Draw(img)
        for kind, (x, y), value, size, color, bold, anchor, max_w, max_lines, line_gap in self._texts:
            font = ov._font(size, bold=bold)
            if kind == "wrap":
                lines = _wrap_lines(draw, value, font, max_w, max_lines=max_lines)
                step = size + line_gap
                start_y = y - ((len(lines) - 1) * step) / 2.0 if anchor.endswith("m") else y
                for idx, line in enumerate(lines):
                    draw.text((x, start_y + idx * step), line, font=font, fill=color, anchor=anchor)
            elif kind == "tail" and max_w is not None:
                shown = value
                if draw.textlength(shown, font=font) > max_w:
                    lo, hi = 0, len(shown)
                    while lo < hi:
                        mid = (lo + hi) // 2
                        if draw.textlength("…" + shown[mid:], font=font) <= max_w:
                            hi = mid
                        else:
                            lo = mid + 1
                    shown = "…" + shown[lo:]
                draw.text((x, y), shown, font=font, fill=color, anchor=anchor)
            else:
                shown = _fit_text(draw, value, font, max_w) if max_w is not None else value
                draw.text((x, y), shown, font=font, fill=color, anchor=anchor)
        return img

    def finish(self, compress_level=2):
        buf = io.BytesIO()
        self.finish_image().save(buf, "PNG", compress_level=compress_level)
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


class _ReadyCanvas:
    """Lightweight pre-composited 1x RGBA canvas returned by the static-base dock cache."""

    def __init__(self, img, screen, anchor="bottom", hits=()):
        self.img = img
        self.w, self.h = img.size
        self.screen = screen
        self.anchor = anchor
        self.hits = list(hits)

    def finish(self, compress_level=1):
        buf = io.BytesIO()
        self.img.save(buf, "PNG", compress_level=compress_level)
        return buf.getvalue()

    def screen_rect(self):
        sw, sh = self.screen
        ox, oy, dw, dh = place_overlay(self.w, self.h, sw, sh, self.anchor)
        return [round(ox / sw, 4), round(oy / sh, 4), round((ox + dw) / sw, 4), round((oy + dh) / sh, 4)]

    def screen_hits(self):
        sw, sh = self.screen
        ox, oy, dw, dh = place_overlay(self.w, self.h, sw, sh, self.anchor)
        sx, sy = dw / max(1, self.w), dh / max(1, self.h)
        return [
            ((ox + x0 * sx) / sw, (oy + y0 * sy) / sh, (ox + x1 * sx) / sw, (oy + y1 * sy) / sh, action, payload)
            for x0, y0, x1, y1, action, payload in self.hits
        ]


# ----- Main TouchUI controller

class TouchUI:
    """Manages on-screen glass controls, nightstand clock, prompts/chat, character switcher,
    timers, moods & treats, Bluetooth pairing, quick setup wizard, Wi-Fi setup & touch keyboard."""

    def __init__(self, device):
        self.device = device
        self.view = "pill"              # "pill", "nightstand", "dock", "prompts", "characters", "timers", "status", "wifi", "bluetooth", "setup", "keyboard"
        self.hits = []                  # [(nx0, ny0, nx1, ny1, action, payload)] for active view
        self.panel_rect = None          # normalized [x0, y0, x1, y1] of open dock/sheet
        self.pill_rect = None           # normalized [x0, y0, x1, y1] of floating pill
        self._dragging = None           # "volume" | "brightness" | None
        self._last_slider_render = 0.0
        self._dock_cache = None         # static dock base layer cache for fast Pi 4 slider drags
        self._dock_cache_hits = 0
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
        self.kb_target = "wifi_password"   # "wifi_password", "wifi_ssid", or "chat_message"
        self.kb_ssid = ""
        self.kb_text = ""
        self.kb_layout = "abc"             # "abc", "num", "sym"
        self.kb_shift = False
        self.kb_caps = False
        self.kb_show_text = False
        self.kb_error = ""
        self.kb_busy = False
        self._last_shift_tap = 0.0

        # Bluetooth audio pairing state
        self.bt_devices = []
        self.bt_scanning = False
        self.bt_busy_mac = ""
        self.bt_error = ""
        self.bt_page = 0

        # On-screen Quick Setup Wizard & Touch Calibration state
        self.setup_step = 0             # 0: Wi-Fi, 1: Audio/Rotation/Touch test, 2: AI Keys & QR
        self.cal_last = None            # (x, y) last tapped test coordinates

        # Listen for caption show/hide so the floating pill yields cleanly to captions.
        self.device.overlays.on_caption_change = self._on_caption_change

    # ----- lifecycle & settings sync

    def enabled(self):
        return bool(self.device.store.settings().get("touch", {}).get("enabled", True))

    def sync_stage_config(self):
        """Push touchscreen settings, rotation compensation, and current hit-capture regions to stage."""
        settings = self.device.store.settings()
        cfg = settings.get("touch", {})
        rot = int(settings.get("screen", {}).get("rotation", 0))
        self.device.stage.send({
            "touch_config": {
                "enabled": bool(cfg.get("enabled", True)),
                "character_touch": bool(cfg.get("character_touch", True)),
                "effects": bool(cfg.get("effects", True)),
                "rotation": rot if rot in (0, 90, 180, 270) else 0,
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
        self._dock_cache = None
        if self.device.touch_ready and self.enabled():
            self.render()

    def _on_caption_change(self, visible):
        self._caption_visible = bool(visible)
        if self.device.touch_ready and self.view == "pill":
            self.render()

    def on_state_changed(self):
        """Refresh active view whenever listening/speaking/muted/timer state changes."""
        if not self.enabled():
            return
        if self.view in ("pill", "dock", "timers", "status", "prompts", "nightstand"):
            self.render()

    def enter_nightstand(self):
        """Show the ultra-dim Ambient Nightstand Clock over the softly dimmed character."""
        if not self.enabled():
            return
        self._cancel_auto_hide()
        self._dragging = None
        self.view = "nightstand"
        self.hits = []
        self.panel_rect = None
        self.pill_rect = None
        self.device.overlays.hide(ov.TOUCH_PILL)
        self.device.overlays.hide(ov.TOUCH_DOCK)
        self.device.overlays.hide(ov.TOUCH_SHEET)
        self.render()
        self._ensure_tick()

    def exit_nightstand(self):
        """Wake smoothly from Ambient Nightstand Mode back to the character-first pill."""
        self.device.overlays.hide(ov.TOUCH_NIGHTSTAND)
        if self.view == "nightstand":
            self.view = "pill"
            if self.enabled():
                self.render()
            self._ensure_tick()

    def hide_all(self):
        self._cancel_auto_hide()
        self._stop_tick()
        self._dock_cache = None
        self.view = "pill"
        self.hits = []
        self.panel_rect = None
        self.pill_rect = None
        self.device.overlays.hide(ov.TOUCH_PILL)
        self.device.overlays.hide(ov.TOUCH_DOCK)
        self.device.overlays.hide(ov.TOUCH_SHEET)
        self.device.overlays.hide(ov.TOUCH_NIGHTSTAND)
        self._push_capture()

    def _push_capture(self):
        if not self.enabled() or self.view == "nightstand":
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
        """Refresh timers every 1 s, or the Nightstand clock once every 30 s (~0% CPU)."""
        need = self.view in ("timers", "nightstand") or (self.view == "pill" and bool(self.device.timers))
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
                    interval = 30.0 if self.view == "nightstand" else 1.0
                    await asyncio.sleep(interval)
                    if not self.enabled():
                        return
                    if self.view in ("timers", "nightstand") or (self.view == "pill" and bool(self.device.timers)):
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

    def open_view(self, view, quiet=False):
        if not self.enabled():
            return
        prev = self.view
        self._dragging = None
        self.view = view
        self.device.activity()
        self.device.overlays.hide(ov.TOUCH_NIGHTSTAND)
        if view == "dock":
            self.device.overlays.hide(ov.TOUCH_PILL)
            self.device.overlays.hide(ov.TOUCH_SHEET)
            self._arm_auto_hide()
        elif view == "pill":
            self._dock_cache = None
            self._cancel_auto_hide()
            self.device.overlays.hide(ov.TOUCH_DOCK)
            self.device.overlays.hide(ov.TOUCH_SHEET)
        else:
            self._dock_cache = None
            self._cancel_auto_hide()
            self.device.overlays.hide(ov.TOUCH_PILL)
            self.device.overlays.hide(ov.TOUCH_DOCK)
        if not quiet and prev != view:
            self.device.play_ui_sound("close" if view == "pill" else "open")
        if view == "wifi":
            self.wifi_page = 0
            self.wifi_error = ""
            self._start_wifi_scan()
        elif view == "bluetooth":
            self.bt_page = 0
            self.bt_error = ""
            self._start_bt_scan(quick=True)
        elif view in ("status", "setup"):
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

        # Edge swipes: bottom-up -> Dock (or Wi-Fi on setup), top-down -> Timers, left-right -> Quick Prompts & Chat.
        if target == "edge" and phase == "swipe":
            if direction == "up":
                if self._setup_card_showing and not self.device.active_id():
                    self.open_view("wifi")
                else:
                    self.open_view("dock")
            elif direction == "down":
                self.open_view("timers")
            elif direction == "right":
                self.open_view("prompts")
            return

        # Floating pill interactions.
        if target == "pill":
            if phase == "swipe" and direction == "up":
                self.open_view("wifi" if (self._setup_card_showing and not self.device.active_id()) else "dock")
            elif phase == "tap":
                self._tap_pill()
            elif phase == "long_press":
                self.device.play_ui_sound("listen_start" if not self.device.listening else "listen_stop")
                self.device.button()
                self.render()
            return

        # Panel / sheet interactions (including fast cached slider dragging & swipe pagination/dismiss).
        if target == "panel":
            if phase == "down":
                hit = self._find_hit(x, y)
                if hit and hit[4] in ("slider_volume", "slider_brightness"):
                    self._dragging = hit[4]
                    self._apply_slider(hit, x, force_render=True)
            elif phase == "move":
                if self._dragging:
                    hit = self._find_action(self._dragging)
                    if hit:
                        self._apply_slider(hit, x, force_render=False)
            elif phase == "up":
                if self._dragging:
                    hit = self._find_action(self._dragging)
                    if hit:
                        self._apply_slider(hit, x, force_render=True)
                    self._dragging = None
            elif phase == "tap":
                hit = self._find_hit(x, y)
                if hit:
                    self._run_action(hit[4], hit[5], hit, x, y)
            elif phase == "swipe":
                if direction == "down" and self.view in ("dock", "prompts", "characters", "timers", "status", "wifi", "bluetooth", "setup"):
                    self.dismiss()
                elif direction in ("left", "right") and self.view == "characters":
                    self.device.play_ui_sound("tap")
                    self._step_char_page(1 if direction == "left" else -1)
                elif direction in ("left", "right") and self.view == "wifi":
                    self.device.play_ui_sound("tap")
                    self._step_wifi_page(1 if direction == "left" else -1)
                elif direction in ("left", "right") and self.view == "bluetooth":
                    self.device.play_ui_sound("tap")
                    self._step_bt_page(1 if direction == "left" else -1)

    def _tap_pill(self):
        if self._setup_card_showing and not self.device.active_id():
            self.open_view("wifi")
            return
        busy = self.device.conversation is not None and self.device.conversation.busy
        if busy or self.device.listening or self.device.recording is not None:
            # One tap on the active pill interrupts speech or stops/sends listening immediately.
            self.device.play_ui_sound("listen_stop")
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

    def _apply_slider(self, hit, x, force_render=True):
        x0, _, x1, _, action, _ = hit
        frac = max(0.0, min(1.0, (x - x0) / max(1e-4, x1 - x0)))
        changed = False
        if action == "slider_volume":
            vol = round(frac * 20) / 20.0
            if abs(vol - float(self.device.store.settings().get("volume", 0.8))) >= 0.04 or frac in (0.0, 1.0):
                self.device.store.update_settings({"volume": vol})
                self.device.speaker.volume = vol
                self.device.emit("touch_ui", {"action": "volume", "value": vol})
                changed = True
        elif action == "slider_brightness":
            pct = max(10, min(100, int(round((10 + frac * 90) / 5.0) * 5)))
            cur = int(self.device.store.settings().get("screen", {}).get("brightness", 100))
            if pct != cur:
                self.device.store.update_settings({"screen": {"brightness": pct}})
                self.device.backlight.set(pct / 100.0)
                self.device.emit("touch_ui", {"action": "brightness", "value": pct})
                changed = True
        now = time.monotonic()
        if changed and (force_render or now - self._last_slider_render >= 0.045):
            self._last_slider_render = now
            self.render()

    def _run_action(self, action, payload, hit, x, y=0.5):
        if action in ("slider_volume", "slider_brightness"):
            self._apply_slider(hit, x, force_render=True)
            return
        if action == "close":
            self.dismiss()
        elif action == "talk":
            was_active = self.device.listening or (self.device.conversation and self.device.conversation.busy)
            self.device.play_ui_sound("listen_stop" if was_active else "listen_start")
            self.device.button()
            if self.device.listening or (self.device.conversation and self.device.conversation.busy):
                self.open_view("pill", quiet=True)
            else:
                self.render()
        elif action == "mute":
            self.device.play_ui_sound("tap")
            if self.device.mic_switch:
                self.device.overlays.hint("The mute switch is on: slide it to turn the microphone on", seconds=3.5)
            else:
                self.device.set_muted(not self.device._mute_choice)
                self.device.overlays.hint("Microphone off" if self.device.muted else "Microphone on", seconds=1.8)
            self.render()
        elif action == "captions":
            self.device.play_ui_sound("tap")
            cur = bool(self.device.store.settings().get("captions", {}).get("on"))
            old = self.device.store.settings()
            new = self.device.store.update_settings({"captions": {"on": not cur}})
            self.device.settings_changed(old, new)
            self.device.emit("touch_ui", {"action": "captions", "on": not cur})
            self.render()
        elif action == "sleep":
            self.device.play_ui_sound("close")
            how = self.device.store.settings().get("screen", {}).get("how", "off")
            if how == "nightstand":
                self.device.set_screen("nightstand")
            else:
                self.open_view("pill", quiet=True)
                self.device.set_screen(how)
            self.device.emit("touch_ui", {"action": "sleep", "screen": how})
        elif action == "enter_nightstand":
            self.device.play_ui_sound("close")
            self.device.set_screen("nightstand")
            self.device.emit("touch_ui", {"action": "sleep", "screen": "nightstand"})
        elif action == "open_characters":
            self.open_view("characters")
        elif action == "open_timers":
            self.open_view("timers")
        elif action == "open_wifi":
            self.open_view("wifi")
        elif action == "open_status":
            self.open_view("status")
        elif action == "open_prompts":
            self.open_view("prompts")
        elif action == "open_bluetooth":
            self.open_view("bluetooth")
        elif action == "open_setup":
            self.setup_step = 0
            self.cal_last = None
            self.open_view("setup")
        elif action == "send_prompt":
            self.device.play_ui_sound("open")
            self.open_view("pill", quiet=True)
            try:
                asyncio.ensure_future(self.device.say(str(payload)))
            except RuntimeError:
                pass
            self.device.emit("touch_ui", {"action": "prompt", "text": str(payload)})
        elif action == "open_chat_kb":
            self._open_keyboard("chat_message", ssid="")
        elif action == "treat":
            try:
                self.device.give_treat(str(payload))
            except ValueError:
                pass
            self.render()
        elif action == "select_character":
            cid = str(payload)
            if cid != self.device.active_id():
                try:
                    name = self.device.characters.manifest(cid).get("name", cid)
                    self.device.play_ui_sound("open")
                    self.open_view("pill", quiet=True)
                    self.device.overlays.hint("Switching to %s…" % name, seconds=2.0)
                    self.device.activate(cid)
                    self.device.emit("touch_ui", {"action": "character", "id": cid})
                except KeyError:
                    pass
            else:
                self.dismiss()
        elif action == "char_prev":
            self.device.play_ui_sound("tap")
            self._step_char_page(-1)
        elif action == "char_next":
            self.device.play_ui_sound("tap")
            self._step_char_page(1)
        elif action == "quick_timer":
            secs, label = payload
            self.device.play_ui_sound("timer")
            self.device.action({"kind": "timer", "seconds": secs, "label": "%s timer" % label})
            self.device.overlays.hint("%s timer set" % label, seconds=1.8)
            self.render()
            self._ensure_tick()
        elif action == "cancel_timer":
            self.device.play_ui_sound("close")
            self.device.action({"kind": "cancel", "label": str(payload)})
            self.render()
        elif action == "mood":
            self.device.play_ui_sound("tap")
            if payload == "wave":
                if hasattr(self.device.stage, "gesture"):
                    self.device.stage.gesture("wave")
            else:
                self.device.stage.express(str(payload))
            self.device.emit("touch_ui", {"action": "mood", "name": str(payload)})
            self.render()
        elif action == "toggle_spoken_touch":
            self.device.play_ui_sound("tap")
            cur = bool(self.device.store.settings().get("touch", {}).get("spoken_reactions", True))
            self.device.store.update_settings({"touch": {"spoken_reactions": not cur}})
            self.device.emit("touch_ui", {"action": "spoken_reactions", "on": not cur})
            self.render()
        elif action == "toggle_touch_sounds":
            cur = bool(self.device.store.settings().get("touch", {}).get("sounds", True))
            self.device.store.update_settings({"touch": {"sounds": not cur}})
            if not cur:
                self.device.play_ui_sound("tap")
            self.device.emit("touch_ui", {"action": "sounds", "on": not cur})
            self.render()
        elif action == "toggle_wake_word":
            self.device.play_ui_sound("tap")
            old = self.device.store.settings()
            cur = bool(old.get("wake_word", {}).get("on"))
            new = self.device.store.update_settings({"wake_word": {"on": not cur}})
            self.device.settings_changed(old, new)
            self.device.emit("touch_ui", {"action": "wake_word", "on": not cur})
            self.render()
        elif action == "toggle_heard_captions":
            self.device.play_ui_sound("tap")
            old = self.device.store.settings()
            cur = bool(old.get("captions", {}).get("heard"))
            new = self.device.store.update_settings({"captions": {"on": True if not cur else old.get("captions", {}).get("on", False), "heard": not cur}})
            self.device.settings_changed(old, new)
            self.render()
        elif action == "wifi_scan":
            self.device.play_ui_sound("tap")
            self._start_wifi_scan()
        elif action == "wifi_prev":
            self.device.play_ui_sound("tap")
            self._step_wifi_page(-1)
        elif action == "wifi_next":
            self.device.play_ui_sound("tap")
            self._step_wifi_page(1)
        elif action == "wifi_pick":
            self.device.play_ui_sound("tap")
            net = payload
            if net.get("secure"):
                self._open_keyboard("wifi_password", ssid=net["ssid"])
            else:
                self._join_wifi_async(net["ssid"], "")
        elif action == "wifi_hidden":
            self.device.play_ui_sound("tap")
            self._open_keyboard("wifi_ssid", ssid="")
        elif action == "bt_scan":
            self.device.play_ui_sound("tap")
            self._start_bt_scan(quick=False)
        elif action == "bt_prev":
            self.device.play_ui_sound("tap")
            self._step_bt_page(-1)
        elif action == "bt_next":
            self.device.play_ui_sound("tap")
            self._step_bt_page(1)
        elif action == "bt_toggle":
            self.device.play_ui_sound("tap")
            self._bt_toggle_async(payload)
        elif action == "setup_step":
            self.device.play_ui_sound("tap")
            self.setup_step = max(0, min(2, int(payload)))
            if self.setup_step in (0, 2):
                self._refresh_wifi_address()
            self.render()
        elif action == "setup_test_speaker":
            self.device.play_ui_sound("test", force=True)
            self.device.overlays.hint("Playing test chime…", seconds=1.8)
        elif action == "setup_rotate":
            self.device.play_ui_sound("tap")
            deg = int(payload)
            if deg in (0, 90, 180, 270):
                old = self.device.store.settings()
                new = self.device.store.update_settings({"screen": {"rotation": deg}})
                self.device.settings_changed(old, new)
                self.device.emit("touch_ui", {"action": "rotation", "degrees": deg})
                self.render()
        elif action == "setup_cal_tap":
            self.device.play_ui_sound("poke")
            self.cal_last = (round(x, 2), round(y, 2))
            self.device.stage.send({"touch_fx": {"kind": "sparkles", "x": x, "y": y}})
            self.render()
        elif action == "kb_back_view":
            self.open_view("prompts" if self.kb_target == "chat_message" else "wifi")
        elif action == "kb_toggle_show":
            self.device.play_ui_sound("tap")
            self.kb_show_text = not self.kb_show_text
            self.render()
        elif action == "kb_key":
            self.device.play_ui_sound("tap")
            self._handle_key(str(payload))

    def _step_char_page(self, delta):
        total = max(1, (len(self.device.characters.list()) + 3) // 4)
        self.char_page = (self.char_page + delta) % total
        self.render()

    def _step_wifi_page(self, delta):
        total = max(1, (len(self.wifi_networks) + 4) // 5)
        self.wifi_page = (self.wifi_page + delta) % total
        self.render()

    def _step_bt_page(self, delta):
        total = max(1, (len(self.bt_devices) + 3) // 4)
        self.bt_page = (self.bt_page + delta) % total
        self.render()

    # ----- Wi-Fi, Bluetooth & touch keyboard helpers

    def _open_keyboard(self, target, ssid=""):
        self.kb_target = target
        self.kb_ssid = ssid
        self.kb_text = ""
        self.kb_layout = "abc"
        self.kb_shift = target == "chat_message"
        self.kb_caps = False
        self.kb_show_text = target != "wifi_password"
        self.kb_error = ""
        self.kb_busy = False
        self.open_view("keyboard")

    def _handle_key(self, key):
        if self.kb_busy:
            return
        self.kb_error = ""
        max_len = 160 if self.kb_target == "chat_message" else (32 if self.kb_target == "wifi_ssid" else 63)
        if key == "back":
            self.kb_text = self.kb_text[:-1]
        elif key == "clear":
            self.kb_text = ""
        elif key == "space":
            if len(self.kb_text) < max_len:
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
            if len(self.kb_text) < max_len:
                ch = key.upper() if (self.kb_layout == "abc" and (self.kb_shift or self.kb_caps)) else key
                self.kb_text += ch
                if self.kb_shift and not self.kb_caps:
                    self.kb_shift = False
        self.render()

    def _submit_keyboard(self):
        if self.kb_target == "chat_message":
            msg = self.kb_text.strip()
            if not msg:
                self.kb_error = "Type a message to send"
                self.render()
                return
            self.open_view("pill", quiet=True)
            try:
                asyncio.ensure_future(self.device.say(msg))
            except RuntimeError:
                pass
            self.device.emit("touch_ui", {"action": "chat_typed", "text": msg})
            return
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
                if self.view in ("wifi", "status", "dock", "setup"):
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
                if self.view in ("status", "setup"):
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

    def _start_bt_scan(self, quick=False):
        bt = self.device.bluetooth
        if bt is None or not bt.available():
            self.bt_error = "Bluetooth is unavailable on this machine"
            self.bt_scanning = False
            self.render()
            return
        if self.bt_scanning:
            return
        self.bt_scanning = True
        self.bt_error = ""
        self.render()

        async def run_scan():
            try:
                self.bt_devices = await (bt.devices() if quick else bt.scan(seconds=4.0))
            except Exception as err:
                self.bt_error = str(err)
            finally:
                self.bt_scanning = False
                if self.view == "bluetooth":
                    self.render()

        try:
            asyncio.ensure_future(run_scan())
        except RuntimeError:
            self.bt_scanning = False

    def _bt_toggle_async(self, dev):
        bt = self.device.bluetooth
        if bt is None or not bt.available() or self.bt_busy_mac:
            return
        mac = dev["mac"]
        want_disconnect = bool(dev.get("connected"))
        self.bt_busy_mac = mac
        self.bt_error = ""
        self.render()

        async def toggle():
            try:
                if want_disconnect:
                    await bt.disconnect(mac)
                    self.device.overlays.hint("Disconnected %s" % dev["name"], seconds=2.0)
                else:
                    await bt.connect(mac)
                    self.device.overlays.hint("Connected %s" % dev["name"], seconds=2.5)
                self.bt_devices = await bt.devices()
                self.device.emit("touch_ui", {"action": "bluetooth", "mac": mac, "connected": not want_disconnect})
            except Exception as err:
                self.bt_error = str(err)
            finally:
                self.bt_busy_mac = ""
                if self.view == "bluetooth":
                    self.render()

        try:
            asyncio.ensure_future(toggle())
        except RuntimeError:
            self.bt_busy_mac = ""

    # ----- Rendering dispatch

    def render(self):
        """Render the current view into a PNG and push both overlay + touch capture bounds to stage."""
        if not self.enabled():
            self.hide_all()
            return
        screen = self.device.overlays.screen
        if self.view == "nightstand":
            canvas = self._render_nightstand(screen)
            self.pill_rect = None
            self.panel_rect = None
            self.hits = []
            self.device.overlays.show(ov.TOUCH_NIGHTSTAND, canvas.finish(), anchor="center", layer=90, slide="none")
            self._push_capture()
            return
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
                "prompts": self._render_prompts,
                "characters": self._render_characters,
                "timers": self._render_timers,
                "status": self._render_status,
                "wifi": self._render_wifi,
                "bluetooth": self._render_bluetooth,
                "setup": self._render_setup,
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
        sleep_how = settings.get("screen", {}).get("how", "off")
        muted = self.device.muted
        state = self.device.state
        busy = self.device.conversation is not None and self.device.conversation.busy
        cid = self.device.active_id()
        char_name = self.device.characters.manifest(cid).get("name", cid) if cid else "No character"
        mood = (self.device.animation or {}).get("mood") or getattr(self.device.stage, "expression", None) or "neutral"
        bond_label = self.device.touch_stats(cid)["bond"] if cid else ""
        chars_count = len(self.device.characters.ids())
        next_t = self._next_timer_label()
        now_hm = time.strftime("%H:%M")

        # Layout vertical rhythm.
        handle_h = 26
        header_h = 56
        hero_h = 84
        slider_h = 68
        tile_h = 104
        h = pad + handle_h + header_h + gap + hero_h + gap + slider_h + gap + slider_h + gap + tile_h * 2 + gap + pad
        y_vol = pad + handle_h + header_h + gap + hero_h + gap
        y_bri = y_vol + slider_h + gap
        y_tiles = y_bri + slider_h + gap

        # Cache everything except the two live sliders so dragging on Pi 4 only redraws two small strips.
        cache_key = (
            screen, w, h, cid, char_name, mood, bond_label, state, busy,
            self.device.recording is not None, self.device.listening,
            muted, captions_on, sleep_how, chars_count, next_t,
            len(self.device.timers), self.wifi_connected, self.wifi_address, now_hm,
        )
        if self._dock_cache is not None and self._dock_cache[0] == cache_key:
            self._dock_cache_hits += 1
            base_img, base_hits = self._dock_cache[1], self._dock_cache[2]
        else:
            c = _Canvas(w, h, screen, anchor="bottom")
            c.panel(radius=34)

            y = pad
            # Grab handle pill at top center.
            c.rect((w / 2 - 34, y, w / 2 + 34, y + 7), radius=4, fill=(255, 255, 255, 72))
            y += handle_h

            # Header: active character name + mood/bond on left; Chat pill, clock & close on right.
            close_r = 22
            close_cx, close_cy = w - pad - close_r, y + 26
            c.circle(close_cx, close_cy, close_r, GLASS_CARD_HI, outline=GLASS_BORDER)
            c.icon(_icon_close, close_cx, close_cy, 11, TEXT_PRIMARY)
            c.hit((close_cx - close_r - 8, close_cy - close_r - 8, close_cx + close_r + 8, close_cy + close_r + 8), "close")

            clock_x = close_cx - close_r - 14
            c.text((clock_x, close_cy), now_hm, round(side * 0.034), TEXT_PRIMARY, bold=True, anchor="rm")

            # Compact Chat / Quick Prompts button in header.
            chat_w, chat_h = 98, 40
            chat_x1 = clock_x - 96
            chat_x0 = chat_x1 - chat_w
            chat_box = (chat_x0, close_cy - chat_h / 2, chat_x1, close_cy + chat_h / 2)
            c.rect(chat_box, radius=20, fill=GLASS_CARD_HI, outline=GLASS_BORDER)
            c.icon(_icon_chat, chat_x0 + 23, close_cy, 12, CYAN)
            c.text((chat_x0 + 42, close_cy), "Chat", round(side * 0.026), TEXT_PRIMARY, bold=True, anchor="lm")
            c.hit(chat_box, "open_prompts")

            left_max = max(120, chat_x0 - pad - 12)
            c.text((pad, y + 17), char_name, round(side * 0.043), TEXT_PRIMARY, bold=True, anchor="lm", max_w=left_max)
            sub_txt = "%s · %s" % (mood.capitalize(), bond_label if (state == "idle" and bond_label) else state)
            c.text((pad, y + 44), sub_txt, round(side * 0.026), TEXT_MUTED, bold=False, anchor="lm", max_w=left_max)
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

            # 2x3 Quick Action Tile Grid (drawn below the two slider slots).
            timers_sub = next_t if next_t else ("%d active" % len(self.device.timers) if self.device.timers else "Set timer")
            wifi_sub = self.wifi_address if self.wifi_connected and self.wifi_address else ("Connected" if self.wifi_connected else "Setup")
            sleep_sub = "Nightstand" if sleep_how == "nightstand" else ("Dim screen" if sleep_how == "dim" else "Tap to wake")
            tiles = [
                ("Characters", "%d installed" % chars_count, _icon_people, {}, "open_characters", False),
                ("Captions", "On" if captions_on else "Off", _icon_captions, {}, "captions", captions_on),
                ("Sleep", sleep_sub, _icon_moon, {"bg": GLASS_CARD}, "sleep", False),
                ("Timers", timers_sub, _icon_timer, {}, "open_timers", bool(self.device.timers)),
                ("Wi-Fi", wifi_sub, _icon_wifi, {"strength": 100 if self.wifi_connected else 40}, "open_wifi", self.wifi_connected),
                ("More & Care", "Treats · QR", _icon_qr, {}, "open_status", False),
            ]
            col_w = (w - 2 * pad - 2 * gap) / 3.0
            for idx, (title, sub, icon_fn, icon_kw, act, active) in enumerate(tiles):
                row, col = divmod(idx, 3)
                tx = pad + col * (col_w + gap)
                ty = y_tiles + row * (tile_h + gap)
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

            base_img = c.finish_image()
            base_hits = list(c.hits)
            self._dock_cache = (cache_key, base_img, base_hits)

        # Composite fresh Volume & Brightness slider strips onto a copy of the cached static dock.
        img = base_img.copy()
        all_hits = list(base_hits)
        slider_w = max(40, int(w - 2 * pad))
        for sy, label, frac, readout, icon_fn, icon_kw, action in (
            (y_vol, "Volume", volume, "%d%%" % round(volume * 100), _icon_speaker, {"level": volume}, "slider_volume"),
            (y_bri, "Brightness", (brightness - 10) / 90.0, "%d%%" % brightness, _icon_sun, {}, "slider_brightness"),
        ):
            sc = _Canvas(slider_w, slider_h, screen, anchor="bottom")
            self._draw_slider(sc, (1, 1, slider_w - 1, slider_h - 1), label, frac, readout, icon_fn, icon_kw, action, side)
            img.alpha_composite(sc.finish_image(), (int(pad), int(sy)))
            for hx0, hy0, hx1, hy1, hact, hpay in sc.hits:
                all_hits.append((hx0 + pad, hy0 + sy, hx1 + pad, hy1 + sy, hact, hpay))
        return _ReadyCanvas(img, screen, anchor="bottom", hits=all_hits)

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

    # ----- View 5: Moods, Care & Treats, Quick Toggles, Tools & Settings QR Sheet

    def _render_status(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        w = min(sw - 2 * round(side * 0.03), round(sw * 0.94))
        pad = round(side * 0.034)
        gap = round(side * 0.019)
        settings = self.device.store.settings()
        spoken_touch = bool(settings.get("touch", {}).get("spoken_reactions", True))
        touch_sounds = bool(settings.get("touch", {}).get("sounds", True))
        wake_on = bool(settings.get("wake_word", {}).get("on", False))
        heard_on = bool(settings.get("captions", {}).get("heard", False))
        cur_mood = (self.device.animation or {}).get("mood") or getattr(self.device.stage, "expression", None) or "neutral"
        cid = self.device.active_id()
        stats = self.device.touch_stats(cid) if cid else None
        bt_connected = any(d.get("connected") for d in self.bt_devices)

        mood_h = 54
        treat_h = 68
        toggle_h = 62
        tools_h = 66
        qr_card_h = 178
        h = (pad + 26 + 66 + gap + 24 + mood_h + gap + 24 + treat_h + gap
             + (toggle_h * 2 + 10) + gap + tools_h + gap + qr_card_h + pad)
        c = _Canvas(w, h, screen, anchor="bottom")
        c.panel(radius=34)

        ver = updates_mod.current_version()
        ver_label = "Dev build" if ver == "0" else ("v%s" % ver)
        sub = ("Bond: %s (%d) · %s" % (stats["bond"], stats["total"], ver_label)) if stats else ver_label
        y = self._sheet_header(c, w, pad, side, "Moods & Care", sub)
        y += gap

        # Quick Mood / Gesture Strip.
        c.text((pad, y + 10), "Express", round(side * 0.026), TEXT_MUTED, bold=True, anchor="lm")
        y += 24
        bw = (w - 2 * pad - (len(QUICK_MOODS) - 1) * 10) / len(QUICK_MOODS)
        for i, (key, lbl) in enumerate(QUICK_MOODS):
            bx = pad + i * (bw + 10)
            box = (bx, y, bx + bw, y + mood_h)
            selected = key == cur_mood
            c.rect(box, radius=16, fill=ACCENT_BG if selected else GLASS_CARD,
                   outline=ACCENT if selected else GLASS_BORDER, width=1.6 if selected else 1.0)
            c.text((bx + bw / 2, y + mood_h / 2), lbl, round(side * 0.027), TEXT_PRIMARY, bold=True, anchor="mm", max_w=bw - 10)
            c.hit(box, "mood", key)
        y += mood_h + gap

        # Interactive Care & Treats Strip.
        c.text((pad, y + 10), "Care & Treats", round(side * 0.026), TEXT_MUTED, bold=True, anchor="lm")
        y += 24
        treat_styles = {
            "tea": (_icon_heart, ROSE),
            "snack": (_icon_sparkle, AMBER),
            "star": (_icon_sparkle, (255, 224, 102, 255)),
            "high_five": (_icon_heart, CYAN),
        }
        tw = (w - 2 * pad - (len(QUICK_TREATS) - 1) * 10) / len(QUICK_TREATS)
        for i, (key, lbl) in enumerate(QUICK_TREATS):
            tx = pad + i * (tw + 10)
            box = (tx, y, tx + tw, y + treat_h)
            icon_fn, icon_col = treat_styles[key]
            c.rect(box, radius=18, fill=GLASS_CARD, outline=(icon_col[0], icon_col[1], icon_col[2], 95), width=1.2)
            c.icon(icon_fn, tx + tw / 2, y + 23, 12, icon_col)
            c.text((tx + tw / 2, y + 50), lbl, round(side * 0.024), TEXT_PRIMARY, bold=True, anchor="mm", max_w=tw - 10)
            c.hit(box, "treat", key)
        y += treat_h + gap

        # 2x2 Quick Feature Toggles Grid.
        toggles = [
            ("Touch speech", "Reply on pet", spoken_touch, "toggle_spoken_touch"),
            ("Touch sounds", "Subtle UI chimes", touch_sounds, "toggle_touch_sounds"),
            ("Wake word", "Say name to talk", wake_on, "toggle_wake_word"),
            ("Show heard", "Your words on top", heard_on, "toggle_heard_captions"),
        ]
        t_gap = 10
        t_col_w = (w - 2 * pad - t_gap) / 2.0
        for idx, (title, tsub, is_on, act) in enumerate(toggles):
            r, col = divmod(idx, 2)
            tx = pad + col * (t_col_w + t_gap)
            ty = y + r * (toggle_h + t_gap)
            box = (tx, ty, tx + t_col_w, ty + toggle_h)
            c.rect(box, radius=18, fill=GLASS_CARD, outline=GLASS_BORDER)
            c.text((tx + 16, ty + 22), title, round(side * 0.027), TEXT_PRIMARY, bold=True, anchor="lm", max_w=t_col_w - 86)
            c.text((tx + 16, ty + 44), tsub, round(side * 0.020), TEXT_MUTED, bold=False, anchor="lm", max_w=t_col_w - 86)
            sw_x1 = tx + t_col_w - 14
            sw_x0 = sw_x1 - 52
            sw_y0 = ty + toggle_h / 2 - 15
            sw_y1 = ty + toggle_h / 2 + 15
            c.rect((sw_x0, sw_y0, sw_x1, sw_y1), radius=15, fill=EMERALD if is_on else (72, 78, 102, 230))
            knob_x = (sw_x1 - 15) if is_on else (sw_x0 + 15)
            c.circle(knob_x, ty + toggle_h / 2, 11, TEXT_PRIMARY)
            c.hit(box, act)
        y += toggle_h * 2 + t_gap + gap

        # Tools Row: Bluetooth Audio, Quick Setup Wizard, Ambient Nightstand.
        tools = [
            ("Bluetooth", _icon_bluetooth, CYAN if bt_connected else TEXT_PRIMARY, "open_bluetooth", bt_connected),
            ("Setup Wizard", _icon_sparkle, AMBER, "open_setup", False),
            ("Nightstand", _icon_moon, VIOLET, "enter_nightstand", False),
        ]
        tool_w = (w - 2 * pad - 2 * 10) / 3.0
        for i, (lbl, icon_fn, icol, act, active) in enumerate(tools):
            tx = pad + i * (tool_w + 10)
            box = (tx, y, tx + tool_w, y + tools_h)
            fill = (34, 54, 88, 236) if active else GLASS_CARD_HI
            c.rect(box, radius=18, fill=fill, outline=CYAN if active else GLASS_BORDER, width=1.4 if active else 1.0)
            kw = {"bg": fill} if icon_fn is _icon_moon else {}
            c.icon(icon_fn, tx + tool_w / 2, y + 23, 12, icol, **kw)
            c.text((tx + tool_w / 2, y + 48), lbl, round(side * 0.024), TEXT_PRIMARY, bold=True, anchor="mm", max_w=tool_w - 12)
            c.hit(box, act)
        y += tools_h + gap

        # Web Settings Console QR Card.
        qbox = (pad, y, w - pad, y + qr_card_h)
        c.rect(qbox, radius=24, fill=GLASS_CARD, outline=GLASS_BORDER)
        url = ("http://%s" % self.wifi_address) if self.wifi_address else "http://companion.local"
        qr_img = screen_mod.qr_code(url, box=6)
        qr_side = qr_card_h - 28
        if qr_img is not None:
            c.paste_rounded(qr_img, (pad + 14, y + 14, pad + 14 + qr_side, y + 14 + qr_side), radius=14, sharp=True)
        tx = pad + qr_side + 32 if qr_img is not None else pad + 22
        max_tw = w - pad - tx - 14
        c.text((tx, y + 34), "Settings page", round(side * 0.035), TEXT_PRIMARY, bold=True, anchor="lm", max_w=max_tw)
        c.text((tx, y + 66), "AI keys, memory & voices:", round(side * 0.022), TEXT_MUTED, bold=False, anchor="lm", max_w=max_tw)
        c.text((tx, y + 98), url, round(side * 0.029), CYAN, bold=True, anchor="lm", max_w=max_tw)
        c.text((tx, y + 128), "USB: http://10.12.194.1", round(side * 0.022), TEXT_MUTED, bold=False, anchor="lm", max_w=max_tw)
        c.text((tx, y + 154), "Up %dm · %s" % (max(1, round((time.time() - self.device.started) / 60)), self.device.timezone() or "Local time"),
               round(side * 0.020), TEXT_DIM, bold=False, anchor="lm", max_w=max_tw)
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
        is_chat = self.kb_target == "chat_message"
        if is_chat:
            cid = self.device.active_id()
            cname = self.device.characters.manifest(cid).get("name", cid) if cid else "Companion"
            title = "Message to %s" % cname
            sub = "Type anything to say aloud"
            placeholder = "Type a message…"
        elif is_pw:
            title = "Join %s" % self.kb_ssid
            sub = "Connecting…" if self.kb_busy else "Enter password (8–63 characters)"
            placeholder = "Password"
        else:
            title = "Hidden Wi-Fi Network"
            sub = "Connecting…" if self.kb_busy else "Enter network name (SSID)"
            placeholder = "Network name"

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
            display = shown_txt + "|"
            tcol = TEXT_PRIMARY
        else:
            display = placeholder
            tcol = TEXT_DIM
        c.text_tail((pad + 20, y + field_h / 2), display, round(side * 0.036), tcol, bold=False, anchor="lm",
                    max_w=w - 2 * pad - (110 if is_pw else 36))

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
        submit_text = "…" if self.kb_busy else ("Send" if is_chat else ("Connect" if is_pw else "Next"))
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
                    label = submit_text
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

    # ----- View 8: Ambient Nightstand Clock Overlay (layer=90, drawn above the night veil)

    def _render_nightstand(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        now_dt = datetime.datetime.now()
        next_t = self._next_timer_label()
        w = min(round(sw * 0.84), 540)
        h = 304 if next_t else 258
        c = _Canvas(w, h, screen, anchor="center")
        # Warm low-glare dark obsidian glass with soft amber moonlight typography.
        c.rect((0, 0, w, h), radius=34, fill=(10, 11, 18, 138), outline=(245, 214, 178, 36), width=1.4)
        c.text((w / 2, 92), now_dt.strftime("%H:%M"), round(side * 0.175), (238, 222, 200, 218), bold=True, anchor="mm")
        c.text((w / 2, 168), now_dt.strftime("%A, %d %B"), round(side * 0.034), (176, 164, 152, 192), bold=False, anchor="mm", max_w=w - 48)
        if next_t:
            pill_w = min(w - 80, 240)
            px0, py0 = (w - pill_w) / 2, 196
            c.rect((px0, py0, px0 + pill_w, py0 + 42), radius=21, fill=(46, 36, 22, 176), outline=(251, 191, 36, 95), width=1.2)
            c.icon(_icon_timer, px0 + 25, py0 + 21, 11, (242, 190, 92, 220))
            c.text((px0 + 44, py0 + 21), "Next timer · %s" % next_t, round(side * 0.025), (242, 206, 146, 220), bold=True, anchor="lm", max_w=pill_w - 54)
        c.text((w / 2, h - 28), "Tap anywhere to wake", round(side * 0.023), (146, 140, 146, 156), bold=False, anchor="mm")
        return c

    # ----- View 9: Interactive Chat Transcript & Quick Prompts Drawer (left-edge swipe-right)

    def _recent_turns(self, limit=3):
        """Read the latest conversation turns directly from history.jsonl with minimal RAM."""
        cid = self.device.active_id()
        if not cid:
            return []
        path = os.path.join(self.device.memory_dir, cid, "history.jsonl")
        try:
            with open(path, encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()][-limit:]
        except OSError:
            return []
        out = []
        for ln in lines:
            try:
                item = json.loads(ln)
            except ValueError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def _render_prompts(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        w = min(sw - 2 * round(side * 0.03), round(sw * 0.94))
        pad = round(side * 0.036)
        gap = round(side * 0.020)
        cid = self.device.active_id()
        char_name = self.device.characters.manifest(cid).get("name", cid) if cid else "Companion"

        # Flatten recent turns into the latest 3 speech bubbles.
        bubbles = []
        for turn in self._recent_turns(limit=3):
            u = str(turn.get("user") or "").strip()
            r = str(turn.get("reply") or "").strip()
            if u:
                bubbles.append(("user", u))
            if r:
                bubbles.append(("assistant", r))
        bubbles = bubbles[-3:]

        chat_h = 298
        prompt_h = 64
        action_h = 72
        h = pad + 26 + 66 + gap + chat_h + gap + 26 + (prompt_h * 2 + 10) + gap + action_h + pad
        c = _Canvas(w, h, screen, anchor="bottom")
        c.panel(radius=34)

        y = self._sheet_header(c, w, pad, side, "Chat & Prompts", "%s · Swipe left edge anytime" % char_name)
        y += gap

        # Recent conversation transcript card.
        tbox = (pad, y, w - pad, y + chat_h)
        c.rect(tbox, radius=24, fill=(14, 16, 26, 224), outline=GLASS_BORDER)
        if not bubbles:
            c.icon(_icon_chat, w / 2, y + chat_h * 0.38, 22, TEXT_DIM)
            c.text((w / 2, y + chat_h * 0.58), "No recent messages with %s" % char_name,
                   round(side * 0.030), TEXT_PRIMARY, bold=True, anchor="mm", max_w=w - 2 * pad - 48)
            c.text((w / 2, y + chat_h * 0.72), "Pick a quick prompt below or type a message",
                   round(side * 0.023), TEXT_MUTED, bold=False, anchor="mm", max_w=w - 2 * pad - 48)
        else:
            b_pad = 14
            b_gap = 10
            b_h = (chat_h - 2 * b_pad - 2 * b_gap) / 3.0
            max_bw = (w - 2 * pad - 2 * b_pad) * 0.84
            # Anchor bubbles toward the bottom when fewer than 3 exist.
            by = y + b_pad + (3 - len(bubbles)) * (b_h + b_gap)
            for role, text in bubbles:
                if role == "user":
                    bx1 = w - pad - b_pad
                    bx0 = bx1 - max_bw
                    c.rect((bx0, by, bx1, by + b_h), radius=18, fill=(54, 72, 138, 232), outline=(126, 152, 255, 80))
                    c.text((bx0 + 16, by + 16), "You", round(side * 0.020), (192, 210, 255, 255), bold=True, anchor="lm")
                    c.text_wrapped((bx0 + 16, by + 33), text, round(side * 0.024), TEXT_PRIMARY, bold=False, anchor="la", max_w=max_bw - 32, max_lines=2, line_gap=3)
                else:
                    bx0 = pad + b_pad
                    bx1 = bx0 + max_bw
                    c.rect((bx0, by, bx1, by + b_h), radius=18, fill=GLASS_CARD_HI, outline=GLASS_BORDER)
                    c.text((bx0 + 16, by + 16), char_name, round(side * 0.020), CYAN, bold=True, anchor="lm", max_w=max_bw - 32)
                    c.text_wrapped((bx0 + 16, by + 33), text, round(side * 0.024), TEXT_PRIMARY, bold=False, anchor="la", max_w=max_bw - 32, max_lines=2, line_gap=3)
                by += b_h + b_gap
        y += chat_h + gap

        # 2x2 One-Tap Quick Prompts.
        c.text((pad, y + 10), "Quick prompts", round(side * 0.026), TEXT_MUTED, bold=True, anchor="lm")
        y += 26
        p_gap = 10
        pw = (w - 2 * pad - p_gap) / 2.0
        for idx, (label, prompt) in enumerate(QUICK_PROMPTS):
            r, col = divmod(idx, 2)
            px = pad + col * (pw + p_gap)
            py = y + r * (prompt_h + p_gap)
            box = (px, py, px + pw, py + prompt_h)
            c.rect(box, radius=18, fill=(38, 48, 86, 232), outline=(120, 146, 255, 92), width=1.2)
            c.icon(_icon_sparkle, px + 26, py + prompt_h / 2, 10, CYAN if idx % 2 == 0 else VIOLET)
            c.text((px + 46, py + prompt_h / 2), label, round(side * 0.029), TEXT_PRIMARY, bold=True, anchor="lm", max_w=pw - 58)
            c.hit(box, "send_prompt", prompt)
        y += prompt_h * 2 + p_gap + gap

        # Bottom Compose + Talk bar.
        talk_w = round((w - 2 * pad - gap) * 0.30)
        type_w = (w - 2 * pad - gap) - talk_w
        type_box = (pad, y, pad + type_w, y + action_h)
        c.rect(type_box, radius=22, fill=GLASS_CARD_HI, outline=ACCENT, width=1.4)
        c.icon(_icon_chat, pad + 32, y + action_h / 2, 14, CYAN)
        c.text((pad + 58, y + action_h / 2), "Type a message…", round(side * 0.032), TEXT_PRIMARY, bold=True, anchor="lm", max_w=type_w - 72)
        c.hit(type_box, "open_chat_kb")

        tx0 = pad + type_w + gap
        talk_box = (tx0, y, tx0 + talk_w, y + action_h)
        c.rect(talk_box, radius=22, fill=ACCENT_BG, outline=(255, 255, 255, 60), width=1.4)
        c.icon(_icon_mic, tx0 + 34, y + action_h / 2, 14, TEXT_PRIMARY)
        c.text((tx0 + 58, y + action_h / 2), "Talk", round(side * 0.032), TEXT_PRIMARY, bold=True, anchor="lm")
        c.hit(talk_box, "talk")
        return c

    # ----- View 10: Bluetooth Audio Pairing Sheet

    def _render_bluetooth(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        w = min(sw - 2 * round(side * 0.03), round(sw * 0.94))
        pad = round(side * 0.036)
        gap = round(side * 0.020)
        per_page = 4
        pages = max(1, (len(self.bt_devices) + per_page - 1) // per_page)
        self.bt_page = min(self.bt_page, pages - 1)
        shown = self.bt_devices[self.bt_page * per_page:(self.bt_page + 1) * per_page]

        status_h = 66
        row_h = 78
        rows_h = (len(shown) * (row_h + 10)) if shown else 116
        pager_h = 56 if pages > 1 else 0
        footer_h = 56
        h = pad + 26 + 66 + gap + status_h + gap + rows_h + (gap + pager_h if pager_h else 0) + gap + footer_h + pad
        c = _Canvas(w, h, screen, anchor="bottom")
        c.panel(radius=34)

        conn = next((d for d in self.bt_devices if d.get("connected")), None)
        sub = "Scanning nearby speakers…" if self.bt_scanning else (
            ("Connected · " + conn["name"]) if conn else "Pair a wireless speaker or headphones"
        )
        y = self._sheet_header(c, w, pad, side, "Bluetooth Audio", sub, back_action="open_status")
        y += gap

        # Status + Scan bar.
        sbox = (pad, y, w - pad, y + status_h)
        c.rect(sbox, radius=20, fill=GLASS_CARD, outline=CORAL if self.bt_error else GLASS_BORDER)
        st_text = self.bt_error or ("Discovering devices (4s)…" if self.bt_scanning else "%d devices found" % len(self.bt_devices))
        c.text((pad + 20, y + status_h / 2), st_text, round(side * 0.027),
               CORAL if self.bt_error else TEXT_MUTED, bold=bool(self.bt_error), anchor="lm", max_w=w - 2 * pad - 150)
        scan_box = (w - pad - 122, y + 11, w - pad - 12, y + status_h - 11)
        c.rect(scan_box, radius=14, fill=ACCENT_BG if not self.bt_scanning else GLASS_CARD_HI)
        c.text(((scan_box[0] + scan_box[2]) / 2, y + status_h / 2), "Scanning" if self.bt_scanning else "Scan",
               round(side * 0.027), TEXT_PRIMARY, bold=True, anchor="mm")
        c.hit(scan_box, "bt_scan")
        y += status_h + gap

        if not shown:
            c.rect((pad, y, w - pad, y + 102), radius=20, fill=GLASS_CARD)
            msg = "Looking for Bluetooth speakers & headphones…" if self.bt_scanning else "No Bluetooth audio devices found yet. Put your speaker in pairing mode and tap Scan."
            c.text_wrapped((w / 2, y + 51), msg, round(side * 0.026), TEXT_MUTED, bold=False, anchor="mm", max_w=w - 2 * pad - 40, max_lines=2)
            y += 116
        else:
            for dev in shown:
                box = (pad, y, w - pad, y + row_h)
                is_conn = bool(dev.get("connected"))
                is_busy = self.bt_busy_mac == dev["mac"]
                fill = (32, 54, 88, 236) if is_conn else GLASS_CARD
                c.rect(box, radius=20, fill=fill, outline=CYAN if is_conn else GLASS_BORDER, width=1.5 if is_conn else 1.0)
                c.icon(_icon_bluetooth, pad + 32, y + row_h / 2, 16, EMERALD if is_conn else (CYAN if dev.get("paired") else TEXT_MUTED))
                c.text((pad + 64, y + 28), dev.get("name") or dev["mac"], round(side * 0.032), TEXT_PRIMARY, bold=True, anchor="lm", max_w=w - 2 * pad - 216)
                meta = "Working…" if is_busy else (
                    "Connected · Tap to disconnect" if is_conn else (
                        "Paired · Tap to connect" if dev.get("paired") else "Available · Tap to pair"
                    )
                )
                c.text((pad + 64, y + 54), meta, round(side * 0.022), EMERALD if is_conn else TEXT_MUTED, bold=False, anchor="lm", max_w=w - 2 * pad - 216)
                badge_txt = "…" if is_busy else ("Connected" if is_conn else ("Connect" if dev.get("paired") else "Pair"))
                badge_bg = (32, 118, 92, 230) if is_conn else ACCENT_BG
                bbox = (w - pad - 138, y + 18, w - pad - 14, y + row_h - 18)
                c.rect(bbox, radius=14, fill=GLASS_CARD_HI if is_busy else badge_bg)
                c.text(((bbox[0] + bbox[2]) / 2, y + row_h / 2), badge_txt, round(side * 0.024), TEXT_PRIMARY, bold=True, anchor="mm")
                c.hit(box, "bt_toggle", dev)
                y += row_h + 10

        if pager_h:
            y += gap
            self._draw_pager(c, w, y, pad, side, self.bt_page, pages, "bt_prev", "bt_next")
            y += pager_h

        y += gap
        c.rect((pad, y, w - pad, y + footer_h), radius=18, fill=(22, 26, 40, 220))
        c.text((w / 2, y + footer_h / 2), "Audio routes automatically to connected Bluetooth speakers",
               round(side * 0.023), TEXT_MUTED, bold=False, anchor="mm", max_w=w - 2 * pad - 24)
        return c

    # ----- View 11: 3-Step On-Screen Quick Setup Wizard & Touch Calibration

    def _render_setup(self, screen):
        sw, sh = screen
        side = min(sw, sh)
        w = min(sw - 2 * round(side * 0.03), round(sw * 0.94))
        pad = round(side * 0.036)
        gap = round(side * 0.020)
        step = max(0, min(2, int(self.setup_step)))
        step_titles = ("Wi-Fi", "Audio & Touch", "Ready & Console")

        tab_h = 46
        footer_h = 64
        body_h = 312 if step == 0 else (402 if step == 1 else 370)
        h = pad + 26 + 66 + gap + tab_h + gap + body_h + gap + footer_h + pad
        c = _Canvas(w, h, screen, anchor="bottom")
        c.panel(radius=34)

        y = self._sheet_header(c, w, pad, side, "Quick Setup", "Step %d of 3 · %s" % (step + 1, step_titles[step]), back_action="open_status")
        y += gap

        # 3-step interactive tab bar.
        tab_w = (w - 2 * pad - 2 * 10) / 3.0
        for idx, label in enumerate(("1. Wi-Fi", "2. Audio & Touch", "3. Ready")):
            tx = pad + idx * (tab_w + 10)
            box = (tx, y, tx + tab_w, y + tab_h)
            active = idx == step
            c.rect(box, radius=14, fill=ACCENT_BG if active else GLASS_CARD, outline=ACCENT if active else GLASS_BORDER)
            c.text((tx + tab_w / 2, y + tab_h / 2), label, round(side * 0.024), TEXT_PRIMARY if active else TEXT_MUTED, bold=True, anchor="mm", max_w=tab_w - 10)
            c.hit(box, "setup_step", idx)
        y += tab_h + gap

        body_top = y
        if step == 0:
            # Step 1: Wi-Fi status + quick launcher.
            sbox = (pad, y, w - pad, y + 124)
            c.rect(sbox, radius=22, fill=GLASS_CARD, outline=EMERALD if self.wifi_connected else GLASS_BORDER, width=1.5 if self.wifi_connected else 1.0)
            c.icon(_icon_wifi, pad + 44, y + 62, 22, EMERALD if self.wifi_connected else AMBER, strength=100 if self.wifi_connected else 40)
            st_title = "Wi-Fi Connected" if self.wifi_connected else "Connect to home Wi-Fi"
            st_sub = (self.wifi_address or "Online on your local network") if self.wifi_connected else "Pick your network and type the password right on screen"
            c.text((pad + 86, y + 46), st_title, round(side * 0.036), TEXT_PRIMARY, bold=True, anchor="lm", max_w=w - 2 * pad - 104)
            c.text((pad + 86, y + 80), st_sub, round(side * 0.024), EMERALD if self.wifi_connected else TEXT_MUTED, bold=False, anchor="lm", max_w=w - 2 * pad - 104)
            y += 124 + gap

            wbtn = (pad, y, w - pad, y + 76)
            c.rect(wbtn, radius=22, fill=ACCENT_BG, outline=(255, 255, 255, 60), width=1.4)
            c.text((w / 2, y + 38), "Change Wi-Fi Network" if self.wifi_connected else "Open On-Screen Wi-Fi Picker",
                   round(side * 0.033), TEXT_PRIMARY, bold=True, anchor="mm")
            c.hit(wbtn, "open_wifi")
            y += 76 + gap

            c.rect((pad, y, w - pad, y + 84), radius=20, fill=(22, 26, 40, 220))
            c.text_wrapped((w / 2, y + 42), "You can also connect over USB at http://10.12.194.1 even without Wi-Fi.",
                           round(side * 0.024), TEXT_MUTED, bold=False, anchor="mm", max_w=w - 2 * pad - 36, max_lines=2)

        elif step == 1:
            # Step 2: Speaker chime test, Touch Coordinate Rotation, and Interactive Touch Calibration Target.
            sp_h = 76
            c.rect((pad, y, w - pad, y + sp_h), radius=20, fill=GLASS_CARD, outline=GLASS_BORDER)
            c.icon(_icon_speaker, pad + 32, y + sp_h / 2, 16, CYAN, level=1.0)
            c.text((pad + 62, y + 26), "Speaker check", round(side * 0.030), TEXT_PRIMARY, bold=True, anchor="lm")
            c.text((pad + 62, y + 52), "Play a warm harmonic test chime", round(side * 0.022), TEXT_MUTED, bold=False, anchor="lm", max_w=w - 2 * pad - 210)
            tbtn = (w - pad - 144, y + 14, w - pad - 14, y + sp_h - 14)
            c.rect(tbtn, radius=14, fill=ACCENT_BG)
            c.text(((tbtn[0] + tbtn[2]) / 2, y + sp_h / 2), "Test chime", round(side * 0.026), TEXT_PRIMARY, bold=True, anchor="mm")
            c.hit(tbtn, "setup_test_speaker")
            y += sp_h + gap

            rot_h = 114
            rot_cur = int(self.device.store.settings().get("screen", {}).get("rotation", 0))
            c.rect((pad, y, w - pad, y + rot_h), radius=20, fill=GLASS_CARD, outline=GLASS_BORDER)
            c.text((pad + 20, y + 24), "Touch rotation compensation", round(side * 0.028), TEXT_PRIMARY, bold=True, anchor="lm")
            c.text((w - pad - 20, y + 24), "%d°" % rot_cur, round(side * 0.026), CYAN, bold=True, anchor="rm")
            rbw = (w - 2 * pad - 36 - 3 * 10) / 4.0
            ry0, ry1 = y + 50, y + rot_h - 16
            for i, deg in enumerate((0, 90, 180, 270)):
                rx = pad + 18 + i * (rbw + 10)
                rbox = (rx, ry0, rx + rbw, ry1)
                sel = rot_cur == deg
                c.rect(rbox, radius=14, fill=ACCENT_BG if sel else GLASS_CARD_HI, outline=ACCENT if sel else GLASS_BORDER)
                c.text((rx + rbw / 2, (ry0 + ry1) / 2), "%d°" % deg, round(side * 0.028), TEXT_PRIMARY, bold=True, anchor="mm")
                c.hit(rbox, "setup_rotate", deg)
            y += rot_h + gap

            # Interactive touch alignment target pad.
            cal_h = 184
            cbox = (pad, y, w - pad, y + cal_h)
            c.rect(cbox, radius=22, fill=(12, 16, 28, 240), outline=CYAN if self.cal_last else GLASS_BORDER, width=1.4)
            cx_m, cy_m = (pad + w - pad) / 2.0, y + cal_h / 2.0 - 12
            c.line([(pad + 24, cy_m), (w - pad - 24, cy_m)], color=(255, 255, 255, 26), width=1.0)
            c.line([(cx_m, y + 18), (cx_m, y + cal_h - 42)], color=(255, 255, 255, 26), width=1.0)
            c.circle(cx_m, cy_m, 26, (0, 0, 0, 0), outline=(56, 198, 255, 90), width=1.5)
            c.circle(cx_m, cy_m, 5, (56, 198, 255, 160))
            if self.cal_last is not None:
                ox, oy, dw, dh = place_overlay(w, h, sw, sh, "bottom")
                lx = (self.cal_last[0] * sw - ox) * (w / max(1.0, dw))
                ly = (self.cal_last[1] * sh - oy) * (h / max(1.0, dh))
                lx = max(pad + 24, min(w - pad - 24, lx))
                ly = max(y + 24, min(y + cal_h - 44, ly))
                c.circle(lx, ly, 16, (56, 198, 255, 70), outline=CYAN, width=2.0)
                c.circle(lx, ly, 5, TEXT_PRIMARY)
                cal_msg = "Touch verified at (%.2f, %.2f) · Sparkles aligned!" % self.cal_last
                cal_col = EMERALD
            else:
                cal_msg = "Tap anywhere inside this target box to verify touch alignment"
                cal_col = TEXT_MUTED
            c.text((w / 2, y + cal_h - 20), cal_msg, round(side * 0.023), cal_col, bold=bool(self.cal_last), anchor="mm", max_w=w - 2 * pad - 28)
            c.hit(cbox, "setup_cal_tap")

        else:
            # Step 3: Live readiness checklist + Web Console QR code.
            settings = self.device.store.settings()
            secrets = self.device.store.secret_status()
            llm_prov = settings.get("llm", {}).get("provider", "")
            ai_ready = llm_prov == "local" or any(bool(v) for v in secrets.values())
            cid = self.device.active_id()
            cname = self.device.characters.manifest(cid).get("name", cid) if cid else ""
            checks = [
                ("Wi-Fi network", self.wifi_address or ("Connected" if self.wifi_connected else "Not connected yet"), self.wifi_connected),
                ("Active character", cname if cid else "Upload one on the Settings page", bool(cid)),
                ("AI conversation key", ("Local model" if llm_prov == "local" else "Configured") if ai_ready else "Add API key on Settings page", ai_ready),
            ]
            chk_h = 178
            c.rect((pad, y, w - pad, y + chk_h), radius=22, fill=GLASS_CARD, outline=GLASS_BORDER)
            row_step = chk_h / 3.0
            for idx, (label, detail, ok) in enumerate(checks):
                ry = y + idx * row_step + row_step / 2.0
                c.circle(pad + 28, ry, 10, EMERALD if ok else (251, 191, 36, 70), outline=EMERALD if ok else AMBER, width=1.6)
                c.text((pad + 52, ry - 8), label, round(side * 0.027), TEXT_PRIMARY, bold=True, anchor="lm", max_w=w - 2 * pad - 72)
                c.text((pad + 52, ry + 14), detail, round(side * 0.021), EMERALD if ok else TEXT_MUTED, bold=False, anchor="lm", max_w=w - 2 * pad - 72)
            y += chk_h + gap

            qr_card_h = 178
            c.rect((pad, y, w - pad, y + qr_card_h), radius=22, fill=GLASS_CARD, outline=GLASS_BORDER)
            url = ("http://%s" % self.wifi_address) if self.wifi_address else "http://companion.local"
            qr_img = screen_mod.qr_code(url, box=6)
            qr_side = qr_card_h - 28
            if qr_img is not None:
                c.paste_rounded(qr_img, (pad + 14, y + 14, pad + 14 + qr_side, y + 14 + qr_side), radius=14, sharp=True)
            tx = pad + qr_side + 30 if qr_img is not None else pad + 22
            max_tw = w - pad - tx - 14
            c.text((tx, y + 36), "Open Settings Console", round(side * 0.032), TEXT_PRIMARY, bold=True, anchor="lm", max_w=max_tw)
            c.text((tx, y + 72), "Add AI keys or upload characters:", round(side * 0.022), TEXT_MUTED, bold=False, anchor="lm", max_w=max_tw)
            c.text((tx, y + 110), url, round(side * 0.029), CYAN, bold=True, anchor="lm", max_w=max_tw)
            c.text((tx, y + 144), "USB: http://10.12.194.1", round(side * 0.022), TEXT_MUTED, bold=False, anchor="lm", max_w=max_tw)

        # Wizard Footer Navigation.
        fy = body_top + body_h + gap
        bw = (w - 2 * pad - gap) / 2.0
        lbox = (pad, fy, pad + bw, fy + footer_h)
        rbox = (pad + bw + gap, fy, w - pad, fy + footer_h)
        c.rect(lbox, radius=20, fill=GLASS_CARD_HI, outline=GLASS_BORDER)
        c.text((pad + bw / 2, fy + footer_h / 2), "Back" if step > 0 else "Close", round(side * 0.031), TEXT_PRIMARY, bold=True, anchor="mm")
        c.hit(lbox, "setup_step" if step > 0 else "close", step - 1 if step > 0 else None)

        c.rect(rbox, radius=20, fill=ACCENT_BG, outline=(255, 255, 255, 60), width=1.4)
        c.text((pad + bw + gap + bw / 2, fy + footer_h / 2), "Next Step" if step < 2 else "Done", round(side * 0.031), TEXT_PRIMARY, bold=True, anchor="mm")
        c.hit(rbox, "setup_step" if step < 2 else "close", step + 1 if step < 2 else None)
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
