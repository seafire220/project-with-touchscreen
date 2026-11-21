"""Pictures shown over the character: captions, what it heard, the microphone-off sign, and hints while
the button is held (docs/28-user-guide.md).

The stage draws them (stage/src/overlay.rs). The core makes each one as a PNG, sized for the screen the
stage reports, in the overlay folder beside the stage's socket: /run/companion/overlays on the device,
which is in memory, so captions never wear the card. Then it names the picture in a command.
"""
import asyncio
import io
import itertools
import os

from PIL import Image, ImageDraw, ImageFont

from .store import write_atomic

# Slots, and where each sits on the screen.
CAPTION, HEARD, MIC, HINT = "caption", "heard", "mic-off", "hint"
TOUCH_PILL, TOUCH_DOCK, TOUCH_SHEET = "touch-pill", "touch-dock", "touch-sheet"
ANCHORS = {
    CAPTION: "bottom",
    HEARD: "top",
    MIC: "top_right",
    HINT: "center",
    TOUCH_PILL: "bottom",
    TOUCH_DOCK: "bottom",
    TOUCH_SHEET: "bottom",
}
LAYERS = {
    TOUCH_PILL: 10,
    CAPTION: 20,
    HEARD: 20,
    MIC: 25,
    TOUCH_DOCK: 30,
    TOUCH_SHEET: 40,
    HINT: 50,
}
LINES_PER_PAGE = 3
CHARS_PER_SECOND = 14.0       # how fast the device's voices speak, roughly, at speed 1
CAPTION_LINGER = 3.0          # seconds a caption stays after the character stops talking
FONT_SHARE = {"normal": 0.058, "large": 0.075}    # of the screen's shorter side


def _font(size, bold=True):
    names = ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf") if bold else ("DejaVuSans.ttf",)
    for folder in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF", "/usr/share/fonts/dejavu"):
        for name in names:
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                 # an old Pillow without sizes
        return ImageFont.load_default()


def wrap(text, font, width):
    """Lines of `text` no wider than `width` pixels (a word too long for a line is broken)."""
    measure = ImageDraw.Draw(Image.new("L", (1, 1))).textlength
    lines, line = [], ""
    for word in text.split():
        while measure(word, font=font) > width and len(word) > 1:
            cut = len(word)
            while cut > 1 and measure(word[:cut] + "-", font=font) > width:
                cut -= 1
            if line:
                lines.append(line)
                line = ""
            lines.append(word[:cut] + "-")
            word = word[cut:]
        trial = (line + " " + word).strip()
        if not line or measure(trial, font=font) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _box(lines, font, size, box_width, fill, text_fill=(246, 246, 248, 255)):
    """A rounded box of centred lines, as a PNG."""
    pad_x, pad_y = round(size * 0.6), round(size * 0.42)
    line_height = round(size * 1.22)
    height = 2 * pad_y + line_height * len(lines)
    scale = 2                                    # drawn large, then shrunk: smooth corners
    image = Image.new("RGBA", (box_width * scale, height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, box_width * scale - 1, height * scale - 1), radius=round(size * 0.45) * scale, fill=fill)
    image = image.resize((box_width, height), Image.LANCZOS)
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        y = pad_y + i * line_height + round((line_height - size) * 0.35)
        draw.text(((box_width - w) / 2, y), line, font=font, fill=text_fill)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def caption_pages(text, screen=(720, 1280), size="normal"):
    """A sentence as one or more caption pictures (at most three lines each), and the share of the
    sentence each page holds (for timing them against the voice)."""
    side = min(screen)
    font_size = max(16, round(side * FONT_SHARE.get(size, FONT_SHARE["normal"])))
    font = _font(font_size)
    margin = round(side * 0.03)
    box_width = screen[0] - 2 * margin
    lines = wrap(" ".join(text.split()), font, box_width - 2 * round(font_size * 0.6)) or [""]
    pages = [lines[i:i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)]
    total = sum(len(l) for l in lines) or 1
    shares = [sum(len(l) for l in page) / total for page in pages]
    return [_box(page, font, font_size, box_width, (14, 14, 20, 205)) for page in pages], shares


def heard_png(text, screen=(720, 1280)):
    """What the person said, smaller, at the top: two lines at most (the start is kept)."""
    side = min(screen)
    font_size = max(14, round(side * 0.042))
    font = _font(font_size, bold=False)
    margin = round(side * 0.03)
    # Narrower than the screen by the microphone-off sign on each side, so the two never overlap.
    sign = max(48, round(side * 0.13))
    box_width = screen[0] - 2 * (2 * margin + sign)
    lines = wrap("“%s”" % " ".join(text.split()), font, box_width - 2 * round(font_size * 0.6))
    if len(lines) > 2:
        lines = lines[:2]
        lines[1] = lines[1].rstrip("”") + "…”"
    return _box(lines, font, font_size, box_width, (44, 48, 70, 200), text_fill=(225, 228, 240, 255))


def hint_png(text, screen=(720, 1280)):
    side = min(screen)
    font_size = max(16, round(side * 0.05))
    font = _font(font_size)
    box_width = round(screen[0] * 0.86)
    lines = wrap(text, font, box_width - 2 * round(font_size * 0.6))
    return _box(lines, font, font_size, box_width, (20, 22, 34, 225))


def mic_off_png(screen=(720, 1280)):
    """The microphone-off sign: a microphone, struck through, on a dark disc."""
    side = max(48, round(min(screen) * 0.13))
    s = 4                                        # drawn four times larger, then shrunk
    big = side * s
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((0, 0, big - 1, big - 1), fill=(16, 16, 22, 215))
    white, red = (240, 240, 244, 255), (235, 72, 72, 255)
    c = big / 2
    w = big * 0.07
    head = (c - big * 0.11, big * 0.2, c + big * 0.11, big * 0.56)
    draw.rounded_rectangle(head, radius=big * 0.11, fill=white)
    draw.arc((c - big * 0.2, big * 0.3, c + big * 0.2, big * 0.66), start=0, end=180, fill=white, width=round(w * 0.7))
    draw.line((c, big * 0.66, c, big * 0.77), fill=white, width=round(w * 0.7))
    draw.line((c - big * 0.12, big * 0.78, c + big * 0.12, big * 0.78), fill=white, width=round(w * 0.7))
    # The strike: a dark edge, then red, so it reads on the white microphone.
    a, b = (big * 0.24, big * 0.22), (big * 0.76, big * 0.8)
    draw.line((a, b), fill=(16, 16, 22, 255), width=round(w * 1.9))
    draw.line((a, b), fill=red, width=round(w))
    image = image.resize((side, side), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


class Overlays:
    """What shows over the character, through the stage."""

    def __init__(self, folder, stage):
        self.folder = folder
        self.stage = stage
        self.screen = (720, 1280)          # updated from the stage's ready and size events
        self._names = itertools.count(1)
        self.shown = {}                    # slot: the picture's name
        self._kept = {}                    # slot: names written, the latest last
        self._pages = None                 # the caption's later pages, waiting their turn
        self._pages_end = 0.0              # when the last of them shows (the event loop's time)
        self._hide = {}                    # slot: a pending hide
        self.on_caption_change = None      # optional callback(visible: bool) so touch pill yields to captions

    def show(self, slot, png, keep_hide=False, *, anchor=None, layer=None, slide=None, scrim=None):
        """Show a picture in a slot. A pending hide of the slot is cancelled, unless `keep_hide`."""
        os.makedirs(self.folder, exist_ok=True)
        name = "%s-%d.png" % (slot, next(self._names))
        write_atomic(os.path.join(self.folder, name), png)
        if not keep_hide:
            self._cancel_hide(slot)
        was_caption = CAPTION in self.shown
        self.shown[slot] = name
        payload = {"slot": slot, "image": name, "anchor": anchor or ANCHORS.get(slot, "center")}
        resolved_layer = LAYERS.get(slot, 0) if layer is None else layer
        if resolved_layer:
            payload["layer"] = int(resolved_layer)
        if slide and slide != "none":
            payload["slide"] = slide
        if scrim:
            payload["scrim"] = round(float(scrim), 3)
        sent = self.stage.send({"overlay": payload})
        if slot == CAPTION and not was_caption and self.on_caption_change:
            self.on_caption_change(True)
        # The stage reads a picture when it takes the command; the two latest are kept for it.
        kept = self._kept.setdefault(slot, [])
        kept.append(name)
        while len(kept) > 2:
            try:
                os.remove(os.path.join(self.folder, kept.pop(0)))
            except OSError:
                pass
        return sent

    def hide(self, slot, after=0.0):
        """Fade a slot out, now or after a while (a later show cancels it)."""
        self._cancel_hide(slot)
        if after > 0:
            try:
                self._hide[slot] = asyncio.get_running_loop().call_later(after, self.hide, slot)
                return
            except RuntimeError:
                pass
        if slot == CAPTION:
            self._stop_pages()
        if self.shown.pop(slot, None) is not None:
            self.stage.send({"overlay": {"slot": slot, "image": None}})
            if slot == CAPTION and self.on_caption_change:
                self.on_caption_change(False)

    def clear(self):
        for slot in list(self.shown):
            self.hide(slot)

    def _cancel_hide(self, slot):
        pending = self._hide.pop(slot, None)
        if pending is not None:
            pending.cancel()

    def _stop_pages(self):
        if self._pages is not None:
            for handle in self._pages:
                handle.cancel()
            self._pages = None

    # ----- captions
    def caption(self, text, size="normal", speed=1.0):
        """Show a sentence as the character starts saying it; a long one turns its pages as it goes."""
        self._stop_pages()
        pages, shares = caption_pages(text, self.screen, size)
        self.show(CAPTION, pages[0])
        if len(pages) > 1:
            seconds = len(text) / CHARS_PER_SECOND / max(0.5, float(speed or 1.0))
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            at, handles = 0.0, []
            for page, share in zip(pages[1:], shares[:-1]):
                at += share * seconds
                handles.append(loop.call_later(at, self.show, CAPTION, page, True))
            self._pages = handles
            self._pages_end = loop.time() + at

    def caption_done(self, linger=CAPTION_LINGER):
        """The character stopped talking: the caption, and what it heard, go after a moment."""
        if CAPTION in self.shown:
            later = 0.0
            if self._pages:
                try:
                    later = max(0.0, self._pages_end - asyncio.get_running_loop().time())
                except RuntimeError:
                    pass
            self.hide(CAPTION, after=linger + later)
        if HEARD in self.shown:
            self.hide(HEARD, after=linger)

    def heard(self, text):
        self.show(HEARD, heard_png(text, self.screen))

    def hint(self, text, seconds=0.0):
        self.show(HINT, hint_png(text, self.screen))
        if seconds:
            self.hide(HINT, after=seconds)

    def microphone(self, muted):
        if muted:
            self.show(MIC, mic_off_png(self.screen))
        else:
            self.hide(MIC)
