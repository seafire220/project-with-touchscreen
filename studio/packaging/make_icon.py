#!/usr/bin/env python3
"""Draw Character Studio's icon (original artwork, drawn here) and write it in each system's format:
icon.png (1024 px, Linux), icon.ico (Windows) and icon.icns (macOS), beside this file.

    python3 studio/packaging/make_icon.py

Needs Pillow. The files are kept in the repository, so building the apps does not need this.
"""
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
S = 4                       # drawn at four times the size, then scaled down for smooth edges
N = 1024 * S


def gradient(size, top, bottom):
    """A diagonal blend from top-left to bottom-right."""
    base = Image.new("RGB", (size, size), top)
    mask = Image.linear_gradient("L").resize((size, size)).rotate(45, expand=False, fillcolor=128)
    return Image.composite(Image.new("RGB", (size, size), bottom), base, mask)


def star(draw, cx, cy, r, fill):
    """A four-pointed sparkle."""
    w = r * 0.28
    draw.polygon([(cx, cy - r), (cx + w, cy - w), (cx + r, cy), (cx + w, cy + w), (cx, cy + r), (cx - w, cy + w),
                  (cx - r, cy), (cx - w, cy - w)], fill=fill)


def draw_icon():
    margin, radius = 100 * S, 185 * S
    shape = Image.new("L", (N, N), 0)
    ImageDraw.Draw(shape).rounded_rectangle((margin, margin, N - margin, N - margin), radius=radius, fill=255)
    # A soft shadow under the tile, then the tile.
    icon = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    shadow = shape.filter(ImageFilter.GaussianBlur(18 * S)).point(lambda v: int(v * 0.35))
    icon.paste(Image.new("RGBA", (N, N), (20, 10, 40, 255)), (0, 14 * S), shadow)
    icon.paste(gradient(N, (110, 106, 240), (232, 111, 174)), (0, 0), shape)

    # The character, on a layer of its own, kept inside the tile.
    face = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(face)
    cx = N // 2
    skin, hair, ink = (255, 244, 236), (58, 44, 112), (42, 36, 80)
    d.rounded_rectangle((cx - 250 * S, 700 * S, cx + 250 * S, 1100 * S), radius=170 * S, fill=(255, 255, 255))
    hx, hy, hr = cx, 470 * S, 205 * S
    d.ellipse((hx - hr - 22 * S, hy - hr - 40 * S, hx + hr + 22 * S, hy + hr - 10 * S), fill=hair)
    d.ellipse((hx - hr, hy - hr + 30 * S, hx + hr, hy + hr + 30 * S), fill=skin)
    d.chord((hx - hr - 6 * S, hy - hr - 36 * S, hx + hr + 6 * S, hy + hr - 70 * S), 180, 360, fill=hair)
    for side in (-1, 1):
        ex, ey = hx + side * 82 * S, hy + 70 * S
        d.ellipse((ex - 34 * S, ey - 52 * S, ex + 34 * S, ey + 52 * S), fill=ink)
        d.ellipse((ex - 16 * S, ey - 34 * S, ex + 4 * S, ey - 12 * S), fill=(255, 255, 255))
        d.ellipse((ex + side * 30 * S - 30 * S, ey + 62 * S, ex + side * 30 * S + 30 * S, ey + 92 * S),
                  fill=(250, 170, 190))
    d.arc((hx - 44 * S, hy + 108 * S, hx + 44 * S, hy + 170 * S), 20, 160, fill=ink, width=12 * S)
    star(d, 760 * S, 250 * S, 70 * S, (255, 229, 138))
    star(d, 830 * S, 360 * S, 34 * S, (255, 240, 190))
    alpha = face.getchannel("A")
    face.putalpha(Image.composite(alpha, Image.new("L", (N, N), 0), shape))
    icon = Image.alpha_composite(icon, face)
    return icon.resize((1024, 1024), Image.LANCZOS)


def main():
    icon = draw_icon()
    icon.save(os.path.join(HERE, "icon.png"))
    icon.save(os.path.join(HERE, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(os.path.join(HERE, "icon.icns"))
    print("wrote icon.png, icon.ico and icon.icns in", HERE)


if __name__ == "__main__":
    main()
