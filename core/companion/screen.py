"""Messages on the device's screen, such as first-time setup instructions.

The stage only draws puppets, so a message is drawn into a picture and
wrapped as a one-part puppet: a "card". The device shows a card when it has
no character yet, and while it is waiting to be put on Wi-Fi.
"""
import io
import json
import os
import struct

from PIL import Image, ImageDraw, ImageFont

SIZE = (720, 1280)
BACKGROUND = (22, 22, 28)
TEXT = (236, 236, 240)
ACCENT = (142, 165, 255)


def _font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                # an old Pillow without sizes
        return ImageFont.load_default()


def _wrap(draw, text, font, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def qr_code(text, box=8):
    """A QR code picture for a phone camera, or None if the qrcode library is missing."""
    try:
        import qrcode
    except ImportError:
        return None
    code = qrcode.QRCode(border=2, box_size=box, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(text)
    code.make(fit=True)
    return code.make_image(fill_color="black", back_color="white").get_image().convert("RGBA")


def card_png(title, lines, size=SIZE, qr=None):
    """A picture with a title and lines of text. Lines starting with '>' are shown large, as things to type.

    `qr`, if given, is shown as a QR code below the text.
    """
    image = Image.new("RGBA", size, BACKGROUND + (255,))
    draw = ImageDraw.Draw(image)
    margin = 56
    width = size[0] - 2 * margin
    y = int(size[1] * 0.12)
    title_font, body_font, big_font = _font(64), _font(34), _font(42)
    for line in _wrap(draw, title, title_font, width):
        draw.text((margin, y), line, font=title_font, fill=ACCENT)
        y += 80
    y += 28
    for text in lines:
        big = text.startswith(">")
        font = big_font if big else body_font
        for line in _wrap(draw, text.lstrip("> "), font, width):
            draw.text((margin, y), line, font=font, fill=TEXT if not big else (255, 255, 255))
            y += 54 if big else 44
        y += 20
    code = qr_code(qr) if qr else None
    if code is not None:
        side = min(size[0] - 2 * margin, max(160, size[1] - y - 120), 340)
        code = code.resize((side, side), Image.NEAREST)
        image.alpha_composite(code, ((size[0] - side) // 2, y + 10))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def card_puppet(png, name="card"):
    """A one-part Inochi2D puppet showing a picture."""
    with Image.open(io.BytesIO(png)) as im:
        w, h = im.size
    transform = {"trans": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 0.0], "scale": [1.0, 1.0]}
    part = {
        "uuid": 2, "name": "card", "type": "Part", "enabled": True, "zsort": 0.0, "transform": transform,
        "lockToRoot": False, "pinToMesh": False,
        "mesh": {"verts": [-w / 2, -h / 2, w / 2, -h / 2, w / 2, h / 2, -w / 2, h / 2],
                 "uvs": [0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0], "indices": [0, 1, 2, 0, 2, 3], "origin": [0.0, 0.0]},
        "textures": [0, 4294967295, 4294967295], "blend_mode": "Normal", "tint": [1.0, 1.0, 1.0],
        "screenTint": [0.0, 0.0, 0.0], "emissionStrength": 1.0, "mask_threshold": 0.5, "opacity": 1.0,
    }
    root = {"uuid": 1, "name": "Root", "type": "Node", "enabled": True, "zsort": 0.0, "transform": transform,
            "lockToRoot": False, "pinToMesh": False, "children": [part]}
    puppet = {"meta": {"name": name, "version": "1.0-alpha", "thumbnailId": 4294967295, "preservePixels": False},
              "physics": {"pixelsPerMeter": 1000.0, "gravity": 9.8}, "nodes": root, "param": [],
              "automation": [], "animations": {}}
    payload = json.dumps(puppet).encode()
    textures = b"TEX_SECT" + struct.pack(">I", 1) + struct.pack(">I", len(png)) + b"\x00" + png
    return b"TRNSRTS\0" + struct.pack(">I", len(payload)) + payload + textures


def setup_card(address=None):
    """The welcome card. Without an address yet (just started), it says so instead."""
    if not address or not address[:1].isdigit():
        return card_png("Hello!", [
            "I'm starting up. In a moment this screen shows how to set me up from your phone or on screen.",
        ])
    url = "http://%s" % address
    return card_png("Hello!", [
        "To set me up, scan this code or open this address on a phone or computer on the same Wi-Fi:",
        "> %s" % url,
        "There you add your AI service keys and a character. Tap below to change Wi-Fi on screen.",
    ], qr=url)


def wifi_qr(ssid, password):
    """The standard Wi-Fi QR format: phone cameras offer to join the network."""
    def esc(v):
        return "".join("\\" + c if c in "\\;,:\"" else c for c in v)
    return "WIFI:T:WPA;S:%s;P:%s;;" % (esc(ssid), esc(password))


def hotspot_card(ssid, password):
    return card_png("Set up Wi-Fi", [
        "Tap below to choose your home Wi-Fi right on this screen, or scan this code with your phone:",
        "> %s" % ssid,
        "Password:",
        "> %s" % password,
        "Then open http://10.42.0.1 and choose your home Wi-Fi.",
        "Or connect a computer by USB-C cable and open http://10.12.194.1",
    ], qr=wifi_qr(ssid, password))


def message_card(title, text):
    return card_png(title, [text])
