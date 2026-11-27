#!/usr/bin/env python3
"""Long video thumbnail, the SOP standard: 1280x720 JPG under 2MB, before on the
left third, finished result on the right two thirds, small white BEFORE and AFTER
tags, the hook in 2 to 4 words of white uppercase Oswald Bold on green pills,
logo in a corner. No dollar figures.

    python scripts/make_thumbnail.py out.jpg before.jpg after.jpg "LINE ONE" ["LINE TWO"] \
        [--before-focus 0.5] [--after-focus 0.5] [--split 0.333]
"""
from __future__ import annotations
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
GREEN = (14, 147, 70)
W, H = 1280, 720


def cover(img: Image.Image, w: int, h: int, fx: float, fy: float) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    s = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x = int(min(max(fx * img.width - w / 2, 0), img.width - w))
    y = int(min(max(fy * img.height - h / 2, 0), img.height - h))
    return img.crop((x, y, x + w, y + h))


def tag(draw, text, x, y, font):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.rounded_rectangle((x, y, x + r - l + 28, y + b - t + 18), 8, fill=(0, 0, 0, 150))
    draw.text((x + 14 - l, y + 9 - t), text, font=font, fill="white")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("before"); ap.add_argument("after")
    ap.add_argument("lines", nargs="+")
    ap.add_argument("--before-focus", type=float, default=0.5)
    ap.add_argument("--after-focus", type=float, default=0.5)
    ap.add_argument("--split", type=float, default=1 / 3)
    ap.add_argument("--size", type=int, default=104)
    ap.add_argument("--pill-x", type=float, default=0.5, help="centre of the pills, share of width")
    ap.add_argument("--pill-y", type=float, default=0.70, help="centre of the pill stack, share of height")
    a = ap.parse_args()
    sx = round(W * a.split)
    canvas = Image.new("RGB", (W, H))
    canvas.paste(cover(Image.open(a.before), sx, H, a.before_focus, 0.5), (0, 0))
    canvas.paste(cover(Image.open(a.after), W - sx, H, a.after_focus, 0.5), (sx, 0))
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    d.rectangle((sx - 4, 0, sx + 4, H), fill="white")
    small = ImageFont.truetype(str(ROOT / "assets/fonts/Oswald-Bold.ttf"), 34)
    tag(d, "BEFORE", 18, 18, small)
    tag(d, "AFTER", sx + 20, 18, small)
    big = ImageFont.truetype(str(ROOT / "assets/fonts/Oswald-Bold.ttf"), a.size)
    boxes = []
    for line in a.lines:
        l, t, r, b = d.textbbox((0, 0), line.upper(), font=big)
        boxes.append((line.upper(), l, t, r - l, b - t))
    gap, padx, pady = 14, 30, 16
    total = sum(h + 2 * pady for *_, h in boxes) + gap * (len(boxes) - 1)
    y = a.pill_y * H - total / 2
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(shadow)
    for text, l, t, w, h in boxes:
        x = a.pill_x * W - (w + 2 * padx) / 2
        sd.rounded_rectangle((x + 6, y + 8, x + w + 2 * padx + 6, y + h + 2 * pady + 8), 18, fill=(0, 0, 0, 120))
        d.rounded_rectangle((x, y, x + w + 2 * padx, y + h + 2 * pady), 18, fill=GREEN + (255,))
        d.text((x + padx - l, y + pady - t), text, font=big, fill="white")
        y += h + 2 * pady + gap
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    canvas = Image.alpha_composite(Image.alpha_composite(canvas.convert("RGBA"), shadow), over)
    logo = next(p for p in (ROOT / "assets").iterdir() if "logo" in p.name.lower())
    mark = Image.open(logo).convert("RGBA"); mark = mark.resize((120, round(120 * mark.height / mark.width)), Image.LANCZOS)
    canvas.alpha_composite(mark, (W - mark.width - 14, 10))
    canvas.convert("RGB").save(a.out, "JPEG", quality=90, optimize=True)
    print(a.out, Path(a.out).stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
