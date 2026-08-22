#!/usr/bin/env python3
"""Rank (timestamp, crop) pairs in a range by how much of the project they show.

Mike wears a black polo and a black cap and the finished rooms are pale, so a
large very dark mass inside a candidate 9:16 window is almost always him. That
plus a detail measure is enough to sort a range from "the feature fills the
frame" down to "this is his shirt", which is the call the build kept getting
wrong from single keyframes.

    python scripts/scan_shots.py work/<id>/source.mp4 10:00-12:15 --top 12

Prints the best windows, and writes a sheet of them to work/<id>/shot-scan.jpg.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CROPS = (0.16, 0.24, 0.32, 0.40, 0.50, 0.60, 0.68, 0.76, 0.84)


def to_seconds(value: str) -> float:
    parts = [float(p) for p in value.replace(",", ".").split(":")]
    total = 0.0
    for part in parts:
        total = total * 60 + part
    return total


def stamp(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def score_window(frame, crop_x: float):
    """(dark fraction, detail) for the 9:16 window centred on crop_x."""
    import numpy as np

    height, width = frame.shape[:2]
    window = int(round(height * 9 / 16))
    left = int(round(crop_x * width - window / 2))
    left = max(0, min(width - window, left))
    view = frame[:, left:left + window]
    grey = view.mean(axis=2)
    dark = float((grey < 62).mean())
    detail = float(np.abs(np.diff(grey, axis=1)).mean() + np.abs(np.diff(grey, axis=0)).mean())
    return dark, detail


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("range", help="start-end, e.g. 10:00-12:15")
    parser.add_argument("--step", type=float, default=1.0, help="seconds between probes")
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--max-dark", type=float, default=0.16,
                        help="reject a window with more than this fraction of near black")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    begin, end = [to_seconds(p) for p in args.range.split("-")]
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        at = begin
        while at <= end:
            grab = Path(tmp) / "f.jpg"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}",
                            "-i", str(args.source), "-frames:v", "1", "-q:v", "3", str(grab)],
                           check=False)
            if grab.exists():
                with Image.open(grab) as img:
                    frame = np.asarray(img.convert("RGB"), dtype=np.float32)
                for crop_x in CROPS:
                    dark, detail = score_window(frame, crop_x)
                    rows.append({"at": at, "crop_x": crop_x, "dark": dark, "detail": detail})
                grab.unlink()
            at += args.step

    clean = [r for r in rows if r["dark"] <= args.max_dark]
    if not clean:
        print(f"nothing under {args.max_dark:.0%} dark in {args.range}, "
              "Mike is in every window. Widen the range or raise --max-dark.")
        clean = rows
    clean.sort(key=lambda r: (-r["detail"], r["dark"]))

    picked = []
    for row in clean:
        if any(abs(row["at"] - other["at"]) < 1.5 for other in picked):
            continue
        picked.append(row)
        if len(picked) >= args.top:
            break
    picked.sort(key=lambda r: r["at"])

    print(f"{'time':>8}  {'crop_x':>6}  {'dark':>5}  detail")
    for row in picked:
        print(f"{stamp(row['at']):>8}  {row['crop_x']:>6.2f}  {row['dark']:>5.1%}  {row['detail']:.1f}")

    destination = args.out or (args.source.parent / "shot-scan.jpg")
    tile_w, cols = 250, 4
    tile_h = int(tile_w * 16 / 9)
    label = 26
    sheet_rows = (len(picked) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, sheet_rows * (tile_h + label)), (14, 14, 14))
    pen = ImageDraw.Draw(sheet)
    face = REPO_ROOT / "assets" / "fonts" / "Montserrat-ExtraBold.ttf"
    font = ImageFont.truetype(str(face), 15) if face.exists() else ImageFont.load_default(15)

    with tempfile.TemporaryDirectory() as tmp:
        for index, row in enumerate(picked):
            grab = Path(tmp) / f"{index}.jpg"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{row['at']:.2f}", "-i", str(args.source),
                 "-frames:v", "1", "-q:v", "3",
                 "-vf", f"crop=ih*9/16:ih:max(0\\,min(iw-ih*9/16\\,{row['crop_x']}*iw-ih*9/32)):0",
                 str(grab)], check=False)
            if not grab.exists():
                continue
            x, y = (index % cols) * tile_w, (index // cols) * (tile_h + label)
            with Image.open(grab) as img:
                sheet.paste(img.convert("RGB").resize((tile_w, tile_h)), (x, y))
            pen.text((x + 5, y + tile_h + 5),
                     f"{stamp(row['at'])}  x={row['crop_x']:.2f}  dark {row['dark']:.0%}",
                     font=font, fill=(235, 235, 235))
    sheet.save(destination, quality=86)
    print(destination)


if __name__ == "__main__":
    main()
