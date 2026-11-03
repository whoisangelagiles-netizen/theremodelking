#!/usr/bin/env python3
"""The long video thumbnail, in the channel's look.

    python scripts/long_thumbnail.py work/heated-floor/final/final.mp4 5:44 "Heated floor install"
    python scripts/long_thumbnail.py photo.jpg - "Master bathroom remodel" --focus 0.4

1280x720: the frame fills the picture, a green band across the top and the
bottom, and a green plate a little below centre with the label in white
Montserrat ExtraBold capitals, underlined, one or two lines. Matches the
Basement Finish, Master Bathroom Remodel and Jack and Jill thumbnails already on
the channel. The duration badge is YouTube's, never drawn here.

The source is a video (with a timestamp) or a still (with "-"). Pick a frame of
the finished room with nobody in it when one exists. Writes
output/[stem]-long-thumbnail.jpg unless --out says otherwise.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
FONT = REPO_ROOT / "assets" / "fonts" / "Montserrat-ExtraBold.ttf"
W, H = 1280, 720
GREEN = (14, 147, 70)
BAND = 0.085          # top and bottom band, share of the height
PLATE_CENTRE = 0.65   # the plate sits below the middle
PLATE_X = 0.528       # and a touch right of centre, as on the Master Suite thumbnail
PLATE_WIDTH = 0.745   # of the frame width
PLATE_HEIGHT = 0.34   # of the frame height
SIZE = 72
SHADOW = (6, 70, 34)  # the dark green drop under each letter


def to_seconds(stamp: str) -> float:
    total = 0.0
    for part in stamp.split(":"):
        total = total * 60 + float(part)
    return total


def grab(source: Path, at: str) -> Image.Image:
    if at == "-":
        return Image.open(source).convert("RGB")
    with tempfile.TemporaryDirectory() as tmp:
        still = Path(tmp) / "frame.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(to_seconds(at)),
                        "-i", str(source), "-frames:v", "1", str(still)], check=True)
        return Image.open(still).convert("RGB")


def fill(image: Image.Image, focus: float) -> Image.Image:
    scale = max(W / image.width, H / image.height)
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left = round((image.width - W) * min(max(focus, 0.0), 1.0))
    top = (image.height - H) // 2
    return image.crop((left, top, left + W, top + H))


def wrap(text: str, font, width: int, draw) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines[:2]


def render(image: Image.Image, label: str) -> Image.Image:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    band = round(H * BAND)
    draw.rectangle([0, 0, W, band], fill=GREEN)
    draw.rectangle([0, H - band, W, H], fill=GREEN)

    font = ImageFont.truetype(str(FONT), SIZE)
    plate_w = round(W * PLATE_WIDTH)
    lines = wrap(label.upper(), font, plate_w - 60, draw)
    pitch = round(SIZE * 1.25)
    plate_h = max(round(H * PLATE_HEIGHT), pitch * len(lines) + 40)
    x0 = round(W * PLATE_X - plate_w / 2)
    y0 = round(H * PLATE_CENTRE - plate_h / 2)
    draw.rectangle([x0, y0, x0 + plate_w, y0 + plate_h], fill=GREEN)
    y = y0 + (plate_h - pitch * len(lines)) / 2
    for line in lines:
        width = draw.textlength(line, font=font)
        x = x0 + (plate_w - width) / 2
        underline = y + SIZE + 6
        for dx, colour in ((4, SHADOW), (0, "white")):
            draw.text((x + dx, y + dx), line, font=font, fill=colour)
            draw.rectangle([x + dx, underline + dx, x + width + dx, underline + 4 + dx], fill=colour)
        y += pitch
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("at", help="timestamp in the video, or - for a still")
    parser.add_argument("label", help="two to four words, plain case")
    parser.add_argument("--focus", type=float, default=0.5,
                        help="horizontal crop centre when the source is not 16:9, 0 to 1")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if not args.source.exists():
        sys.exit(f"not found: {args.source}")
    out = args.out or REPO_ROOT / "output" / f"{args.source.stem}-long-thumbnail.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    render(fill(grab(args.source, args.at), args.focus), args.label).save(out, quality=92)
    print(out)


if __name__ == "__main__":
    main()
