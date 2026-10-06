#!/usr/bin/env python3
"""Show every shot of a Short at several framing widths, before choosing one.

A full bleed 9:16 window is 31.6 percent of a 16:9 frame blown up 1.78 times,
which is the "zoomed in too much" Mike keeps flagging. The fix is per shot, not
a flat number: each shot gets the widest view that still reads. This writes one
sheet with a row per scene and a tile per candidate view, rendered the way the
build renders it, picture on a blurred fill, so the choice is made by eye.

    python scripts/frame_views.py work/<id>/short1

Writes work/<id>/short1/frame-views.jpg. Then set "view" per scene in
edits.json and rebuild.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from build_short import W, H, full_bleed_view, parse_range  # noqa: E402

VIEWS = (0.0, 0.45, 0.60, 0.80, 1.0)


def render_view(frame: Image.Image, view: float, crop_x: float) -> Image.Image:
    sw, sh = frame.size
    floor = full_bleed_view(sw, sh)
    view = max(floor, min(1.0, view or floor))
    crop_w = min(sw, int(round(view * sw)))
    left = max(0, min(sw - crop_w, int(round(crop_x * sw - crop_w / 2))))
    fg = frame.crop((left, 0, left + crop_w, sh))
    fg_h = min(H, int(round(W * sh / crop_w)))
    fg = fg.resize((W, fg_h), Image.LANCZOS)
    if fg_h >= H - 2:
        return fg.resize((W, H))
    bg = fg.resize((W // 8, max(1, fg_h // 8))).resize((W, H), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(26))
    bg = ImageEnhance.Brightness(bg).enhance(0.62)
    canvas = bg.copy()
    canvas.paste(fg, (0, (H - fg_h) // 2))
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("short_dir", type=Path)
    parser.add_argument("--views", default=",".join(str(v) for v in VIEWS))
    parser.add_argument("--width", type=int, default=150, help="tile width")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    short_dir = args.short_dir.resolve()
    edits = json.loads((short_dir / "edits.json").read_text())
    source = short_dir.parent / "source.mp4"
    if not source.exists():
        sys.exit(f"no source at {source}")
    views = [float(v) for v in args.views.split(",")]
    tw = args.width
    th = int(H * tw / W)

    rows = []
    with tempfile.TemporaryDirectory() as td:
        for entry in edits["scenes"]:
            start, end = parse_range(entry["source"])
            mid = start + (end - start) * 0.5
            grab = Path(td) / f"s{entry['scene']:02d}.jpg"
            subprocess.run(["ffmpeg", "-v", "quiet", "-ss", f"{mid:.2f}", "-i", str(source),
                            "-frames:v", "1", "-q:v", "2", str(grab)], check=True)
            frame = Image.open(grab).convert("RGB")
            pan = entry.get("pan") or {}
            crop_x = float(pan.get("from", entry.get("crop_x", 0.5)) or 0.5)
            tiles = [render_view(frame, v, crop_x).resize((tw, th), Image.LANCZOS)
                     for v in views]
            rows.append((entry["scene"], entry.get("source", ""), float(entry.get("view") or 0), tiles))

    gap = 6
    label_h = 20
    sheet_w = len(views) * (tw + gap) + 150
    sheet_h = len(rows) * (th + label_h + gap)
    sheet = Image.new("RGB", (sheet_w, sheet_h), "black")
    draw = ImageDraw.Draw(sheet)
    floor_pct = None
    y = 0
    for number, src_label, chosen, tiles in rows:
        draw.text((4, y + 4), f"scene {number:02d}", fill="white")
        draw.text((4, y + 18), src_label, fill=(180, 180, 180))
        draw.text((4, y + 34), f"now: {'full' if chosen == 0 else chosen}", fill=(120, 220, 120))
        x = 150
        for v, tile in zip(views, tiles):
            sheet.paste(tile, (x, y + label_h))
            label = "full bleed" if v == 0 else f"{int(round(v * 100))}%"
            draw.text((x + 3, y + 3), label, fill="white")
            x += tw + gap
        y += th + label_h + gap

    out = args.out or (short_dir / "frame-views.jpg")
    sheet.save(out, quality=86)
    print(out)


if __name__ == "__main__":
    main()
