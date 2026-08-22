#!/usr/bin/env python3
"""Sample every rendered scene across its whole length, into one sheet.

The contact sheet grabs one frame per scene, from its middle. The source is
handheld, so a crop that is right in the middle of a four second shot can be
wrong at both ends. This samples each clip at several points so drift shows up
before the Short goes out.

    python scripts/check_frames.py work/<video_id>/short<n> [--per 3]
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True)
    return float(out.stdout.strip() or 0.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("short_dir", type=Path)
    parser.add_argument("--per", type=int, default=3, help="frames per scene, default 3")
    parser.add_argument("--width", type=int, default=210, help="tile width, default 210")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    from PIL import Image, ImageDraw, ImageFont

    parts = args.short_dir / "parts"
    clips = sorted(parts.glob("shot*.mp4")) + sorted(parts.glob("cta.mp4"))
    if not clips:
        raise SystemExit(f"no rendered clips in {parts}, build the Short first")

    scratch = parts / ".check"
    scratch.mkdir(exist_ok=True)
    tiles = []
    for clip in clips:
        span = duration(clip)
        for order in range(args.per):
            at = span * (order + 0.5) / args.per
            grab = scratch / f"{clip.stem}_{order}.jpg"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}",
                            "-i", str(clip), "-frames:v", "1", "-q:v", "3", str(grab)],
                           check=False)
            if grab.exists():
                tiles.append((f"{clip.stem} {at:.1f}s", grab))

    tw = args.width
    th = int(tw * 16 / 9)
    label = 22
    cols = args.per
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + label)), (14, 14, 14))
    pen = ImageDraw.Draw(sheet)
    face = REPO_ROOT / "assets" / "fonts" / "Montserrat-ExtraBold.ttf"
    font = ImageFont.truetype(str(face), 13) if face.exists() else ImageFont.load_default(13)
    for index, (name, grab) in enumerate(tiles):
        x, y = (index % cols) * tw, (index // cols) * (th + label)
        with Image.open(grab) as img:
            sheet.paste(img.convert("RGB").resize((tw, th)), (x, y))
        pen.text((x + 5, y + th + 4), name, font=font, fill=(235, 235, 235))
        if index % cols == 0:
            pen.rectangle([x, y, x + 3, y + th], fill=(22, 163, 74))

    destination = args.out or (args.short_dir / "frame-check.jpg")
    sheet.save(destination, quality=86)
    for grab in scratch.glob("*.jpg"):
        grab.unlink()
    scratch.rmdir()
    print(destination)


if __name__ == "__main__":
    main()
