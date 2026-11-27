#!/usr/bin/env python3
"""Short cover, the SOP standard: finished-room still, 1080x1920, the Short's own
hook in 2 to 4 words of white uppercase Oswald Bold on green pills in the upper
middle, logo top right. No dollar figures.

    python scripts/make_short_cover.py out.jpg still.jpg --x 0.45 "LINE ONE" "LINE TWO"
"""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
ROOT = Path(__file__).resolve().parents[1]
GREEN = (14, 147, 70); W, H = 1080, 1920
ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("still"); ap.add_argument("lines", nargs="+")
ap.add_argument("--x", type=float, default=0.5); ap.add_argument("--size", type=int, default=150); ap.add_argument("--y", type=float, default=0.30)
a = ap.parse_args()
im = ImageOps.exif_transpose(Image.open(a.still)).convert("RGB")
s = H / im.height; im = im.resize((round(im.width * s), H), Image.LANCZOS)
x0 = int(min(max(a.x * im.width - W / 2, 0), im.width - W)); im = im.crop((x0, 0, x0 + W, H)).convert("RGBA")
over = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(over)
sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(sh)
f = ImageFont.truetype(str(ROOT / "assets/fonts/Oswald-Bold.ttf"), a.size)
rows = [(t.upper(),) + d.textbbox((0, 0), t.upper(), font=f) for t in a.lines]
px, py, gap = 40, 22, 20
total = sum(b - t + 2 * py for _, l, t, r, b in rows) + gap * (len(rows) - 1)
y = a.y * H - total / 2
for text, l, t, r, b in rows:
    w, h = r - l, b - t; x = (W - w - 2 * px) / 2
    sd.rounded_rectangle((x + 8, y + 10, x + w + 2 * px + 8, y + h + 2 * py + 10), 24, fill=(0, 0, 0, 130))
    d.rounded_rectangle((x, y, x + w + 2 * px, y + h + 2 * py), 24, fill=GREEN + (255,))
    d.text((x + px - l, y + py - t), text, font=f, fill="white"); y += h + 2 * py + gap
im = Image.alpha_composite(Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(10))), over)
logo = next(p for p in (ROOT / "assets").iterdir() if "logo" in p.name.lower())
m = Image.open(logo).convert("RGBA"); m = m.resize((150, round(150 * m.height / m.width)), Image.LANCZOS)
im.alpha_composite(m, (W - m.width - 30, 40)); im.convert("RGB").save(a.out, "JPEG", quality=92)
print(a.out)
