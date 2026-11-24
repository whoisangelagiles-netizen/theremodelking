#!/usr/bin/env python3
"""Final touches on an edited LONG video body: chapter labels, feature callouts,
before insets, link pills and flash transitions, in the house look, kept light.

    python scripts/finish_body.py finishes/east-bench-phase-3.json
    python scripts/finish_body.py finishes/east-bench-phase-3.json --full

The body is never re-cut. Every touch is a graphic laid OVER the picture at a
timestamp, so the edit, the audio and the stats slides stay exactly as Mike left
them. That also means each touch can be nudged, trimmed or deleted in the editor.

What it writes, under output/[slug]-finish/:

    overlays/NN-kind-name.mov   one 1920x1080 clip per touch, QuickTime Animation
                                with alpha, drops on V2 above the body
    [slug]-finish.xml           Premiere / Resolve timeline (FCP 7 XML): the body on
                                V1, the overlays above it at their exact frames, V2
                                and up only where two of them touch
    markers.csv                 the same list as timecodes, for placing by hand
    [slug]-finish-reel.mp4      every touch over its stretch of the body, back to
                                back, to review without opening the editor
    [slug]-finish-sheet.jpg     one frame per touch at full strength

--full also renders the whole body with every touch burned in, in one ffmpeg pass,
to output/[slug]-body-finished.mp4.

This is a separate process. It shares only the brand constants and the font and
logo lookups with build_short.py and changes nothing in the Shorts or the intro.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import warnings  # noqa: E402
with warnings.catch_warnings():
    warnings.simplefilter("ignore", SyntaxWarning)
    import build_short as bs  # noqa: E402  brand constants, fonts and helpers only

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

REPO_ROOT = bs.REPO_ROOT
OUTPUT = bs.OUTPUT
W, H = 1920, 1080
FPS = 30

GREEN = bs.CAPTION_GREEN       # the plate green the captions and AFTER labels use
EMPHASIS = bs.EMPHASIS_GREEN   # green lifted so small type reads over footage
DARK = (24, 24, 24)            # the BEFORE plate
MARGIN_X, MARGIN_Y = 72, 64    # clear of the YouTube player chrome

IN, OUT = 0.35, 0.30           # every graphic animates in and out this fast
HOLD = {"chapter": 3.2, "label": 3.0, "pill": 4.0, "inset": 4.0, "pointer": 2.4}
POINTER_RING = 54             # radius of the ring on the feature, px

CHAPTER_SIZE = 66
KICKER_SIZE = 32
LABEL_SIZE = 40
PILL_SIZE = 34
INSET_WIDTH = 0.30             # of frame width
INSET_BORDER = 6

FLASH_PEAK = 0.85              # white at the cut, never a full whiteout
FLASH_UP, FLASH_DOWN = 3, 8    # frames either side of the cut

REEL_PAD = 1.5                 # body shown before and after each touch in the reel


def say(message: str) -> None:
    print(f"  {message}", flush=True)


def ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def font(path: str | None, size: int):
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


def timecode(seconds: float) -> str:
    frames = round(seconds * FPS)
    s, f = divmod(frames, FPS)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        bs.die(f"{' '.join(cmd[:3])} failed\n" + "\n".join(result.stderr.splitlines()[-12:]))


# --------------------------------------------------------------------------
# graphics, each returns an RGBA layer for an animation progress 0..1 in, and
# a fade multiplier for the way out
# --------------------------------------------------------------------------

def place(corner: str, w: int, h: int) -> tuple[int, int]:
    x = MARGIN_X if "left" in corner else W - MARGIN_X - w
    y = MARGIN_Y if "top" in corner else H - MARGIN_Y - h
    return x, y


def text_size(draw, text: str, fnt) -> tuple[int, int, int, int]:
    l, t, r, b = draw.textbbox((0, 0), text, font=fnt)
    return l, t, r - l, b - t


def chapter_art(touch: dict, fonts: dict) -> Image.Image:
    """The look of the titles already cut into the body: a green bar on the left,
    the stage name in white Montserrat, a small green kicker under it."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    title = touch["text"].upper()
    kicker = touch.get("kicker", "").upper()
    tl, tt, tw, th = text_size(probe, title, fonts["chapter"])
    kl, kt, kw, kh = text_size(probe, kicker, fonts["kicker"]) if kicker else (0, 0, 0, 0)
    bar, gap, pad = 10, 26, 24
    height = th + (kh + 16 if kicker else 0)
    art = Image.new("RGBA", (bar + gap + max(tw, kw) + 2 * pad, height + 2 * pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(art)
    x = pad + bar + gap
    draw.text((x - tl, pad - tt), title, font=fonts["chapter"], fill="white")
    if kicker:
        draw.text((x - kl, pad + th + 16 - kt), kicker, font=fonts["kicker"], fill=EMPHASIS)
    # soft shadow so white holds over a white wall, the way the opener needs it
    shadow = Image.new("RGBA", art.size, (0, 0, 0, 0))
    shadow.putalpha(art.getchannel("A").point(lambda v: int(v * 0.75)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(7))
    out = Image.new("RGBA", art.size, (0, 0, 0, 0))
    out.alpha_composite(shadow, (0, 3))
    out.alpha_composite(art)
    ImageDraw.Draw(out).rectangle((pad, pad - 4, pad + bar, pad + height + 4), fill=GREEN)
    return out


def label_art(touch: dict, fonts: dict) -> Image.Image:
    """A feature name on the house green plate, the AFTER label look."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text = touch["text"].upper()
    l, t, w, h = text_size(probe, text, fonts["label"])
    pad_x, pad_y = 22, 14
    art = Image.new("RGBA", (w + 2 * pad_x, h + 2 * pad_y), (0, 0, 0, 0))
    draw = ImageDraw.Draw(art)
    draw.rectangle((0, 0, art.width, art.height), fill=GREEN)
    draw.text((pad_x - l, pad_y - t), text, font=fonts["label"], fill="white",
              stroke_width=bs.CAPTION_STROKE, stroke_fill="black")
    return art


def pill_art(touch: dict, fonts: dict) -> Image.Image:
    """White pill, green words, a small arrow pointing down at the description."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text = touch["text"].upper()
    l, t, w, h = text_size(probe, text, fonts["pill"])
    pad_x, pad_y = 34, 18
    arrow = h
    height = h + 2 * pad_y
    art = Image.new("RGBA", (w + arrow + 18 + 2 * pad_x, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(art)
    draw.rounded_rectangle((0, 0, art.width - 1, height - 1), radius=height // 2, fill="white")
    draw.text((pad_x - l, pad_y - t), text, font=fonts["pill"], fill=bs.BRAND_GREEN)
    if touch.get("arrow", True):
        ax = pad_x + w + 18
        cy = height // 2
        s = arrow
        draw.rectangle((ax + s * 0.38, cy - s * 0.45, ax + s * 0.62, cy + s * 0.05),
                       fill=bs.BRAND_GREEN)
        draw.polygon([(ax + s * 0.1, cy), (ax + s * 0.9, cy), (ax + s * 0.5, cy + s * 0.5)],
                     fill=bs.BRAND_GREEN)
    shadow = Image.new("RGBA", (art.width + 40, art.height + 40), (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", art.size, (0, 0, 0, 110)), (20, 26), art)
    shadow = shadow.filter(ImageFilter.GaussianBlur(9))
    shadow.alpha_composite(art, (20, 20))
    return shadow


def inset_art(touch: dict, fonts: dict, body: Path) -> Image.Image:
    """A still of the old room in a white frame, BEFORE on the dark plate."""
    at = bs.to_seconds(str(touch["before"]))
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.3f}",
                          "-i", str(body), "-frames:v", "1", "-f", "image2pipe",
                          "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    still = Image.open(BytesIO(raw)).convert("RGB")
    inner_w = int(W * float(touch.get("width", INSET_WIDTH)))
    inner_h = round(inner_w * 9 / 16)
    focus = touch.get("focus", [0.5, 0.5])
    scale = max(inner_w / still.width, inner_h / still.height)
    still = still.resize((round(still.width * scale), round(still.height * scale)), Image.LANCZOS)
    cx = min(max(focus[0] * still.width, inner_w / 2), still.width - inner_w / 2)
    cy = min(max(focus[1] * still.height, inner_h / 2), still.height - inner_h / 2)
    still = still.crop((round(cx - inner_w / 2), round(cy - inner_h / 2),
                        round(cx - inner_w / 2) + inner_w, round(cy - inner_h / 2) + inner_h))
    b = INSET_BORDER
    framed = Image.new("RGBA", (inner_w + 2 * b, inner_h + 2 * b), "white")
    framed.paste(still, (b, b))
    draw = ImageDraw.Draw(framed)
    text = touch.get("text", "BEFORE").upper()
    l, t, w, h = text_size(draw, text, fonts["inset"])
    draw.rectangle((b, b, b + w + 28, b + h + 16), fill=DARK)
    draw.text((b + 14 - l, b + 8 - t), text, font=fonts["inset"], fill="white")
    pad = 30
    art = Image.new("RGBA", (framed.width + 2 * pad, framed.height + 2 * pad), (0, 0, 0, 0))
    art.paste(Image.new("RGBA", framed.size, (0, 0, 0, 120)), (pad, pad + 8), framed)
    art = art.filter(ImageFilter.GaussianBlur(10))
    art.alpha_composite(framed, (pad, pad))
    return art


def pointer_geometry(touch: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    """Tail and head in pixels. `to` is the feature, [x, y] from 0 to 1. `from`
    is where the arrow starts; left out, it comes in from the clearer side, a
    third of the frame away, angled down onto the feature."""
    tx, ty = touch["to"][0] * W, touch["to"][1] * H
    if "from" in touch:
        fx, fy = touch["from"][0] * W, touch["from"][1] * H
    else:
        fx = tx - 0.18 * W if tx > W / 2 else tx + 0.18 * W
        fy = ty - 0.20 * H if ty > H * 0.4 else ty + 0.20 * H
    return (fx, fy), (tx, ty)


def paint_pointer(frame: Image.Image, tail, head, reveal: float, ring: float,
                  alpha: float) -> None:
    """A thick green arrow over a soft black halo, drawn on from the tail, and a
    ring around the head that pops out once the arrow arrives."""
    if alpha <= 0:
        return
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    (x1, y1), (x2, y2) = tail, head
    angle = math.atan2(y2 - y1, x2 - x1)
    stop = POINTER_RING * 1.25   # the arrow stops short of the ring
    ex, ey = x2 - math.cos(angle) * stop, y2 - math.sin(angle) * stop
    hx, hy = x1 + (ex - x1) * reveal, y1 + (ey - y1) * reveal
    green = bs.BRAND_GREEN + (255,)
    if reveal > 0.02:
        head_len = 46
        sx, sy = hx - math.cos(angle) * head_len * 0.8, hy - math.sin(angle) * head_len * 0.8
        spread = math.radians(28)
        tip = [(hx, hy),
               (hx - math.cos(angle - spread) * head_len, hy - math.sin(angle - spread) * head_len),
               (hx - math.cos(angle + spread) * head_len, hy - math.sin(angle + spread) * head_len)]
        for colour, width, grow in (((0, 0, 0, 150), 22, 6), (green, 12, 0)):
            draw.line([x1, y1, sx, sy], fill=colour, width=width)
            if grow:
                draw.polygon([(px + math.cos(angle) * grow, py + math.sin(angle) * grow)
                              for px, py in tip], fill=colour)
            else:
                draw.polygon(tip, fill=colour)
    if ring > 0:
        r = POINTER_RING * (0.6 + 0.4 * ring)
        box = [x2 - r, y2 - r, x2 + r, y2 + r]
        draw.ellipse(box, outline=(0, 0, 0, 150), width=16)
        draw.ellipse(box, outline=green, width=9)
    halo = layer.filter(ImageFilter.GaussianBlur(1.2))
    if alpha < 1:
        halo.putalpha(halo.getchannel("A").point(lambda v: int(v * alpha)))
    frame.alpha_composite(halo)


TRACK_FPS = 15                 # how often the camera move is measured under a pointer
TRACK_W = 384                  # analysis width, the frame height follows 16:9


def _phase_shift(a, b):
    """How far the picture moved from frame a to frame b, in analysis pixels."""
    import numpy as np
    a = a - a.mean()
    b = b - b.mean()
    window = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    r = np.fft.fft2(a * window) * np.conj(np.fft.fft2(b * window))
    r /= np.abs(r) + 1e-9
    c = np.fft.ifft2(r).real
    y, x = np.unravel_index(c.argmax(), c.shape)
    h, w = c.shape
    return -(x - w if x > w / 2 else x), -(y - h if y > h / 2 else y)


def track_camera(body: Path, start: float, seconds: float, seen: float) -> list:
    """Follow the handheld camera under a pointer: per output frame, the (dx, dy)
    in full frame pixels that the picture has moved since `seen`, the moment the
    target coordinates were read off. Small successive steps are chained, so a
    slow pan of half the frame still tracks."""
    import numpy as np
    first = min(start, seen)
    span = max(start + seconds, seen) - first + 0.2
    h = round(TRACK_W * 9 / 16)
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{first:.3f}",
                          "-t", f"{span:.3f}", "-i", str(body), "-an", "-vf",
                          f"fps={TRACK_FPS},scale={TRACK_W}:{h},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, TRACK_W).astype(float)
    path = [(0.0, 0.0)]
    for a, b in zip(frames, frames[1:]):
        dx, dy = _phase_shift(a, b)
        if abs(dx) > TRACK_W * 0.25 or abs(dy) > h * 0.25:
            dx, dy = 0, 0            # a cut or a blur frame, hold rather than jump
        path.append((path[-1][0] + dx, path[-1][1] + dy))
    scale = W / TRACK_W

    def at(t: float):
        k = min(len(path) - 1, max(0.0, (t - first) * TRACK_FPS))
        i = int(k)
        j = min(len(path) - 1, i + 1)
        f = k - i
        return (path[i][0] * (1 - f) + path[j][0] * f) * scale, \
               (path[i][1] * (1 - f) + path[j][1] * f) * scale

    zero = at(seen)
    total = round(seconds * FPS)
    return [(at(start + n / FPS)[0] - zero[0], at(start + n / FPS)[1] - zero[1])
            for n in range(total)]


def pointer_frames(touch: dict, art: Image.Image | None):
    """Draws on, the ring pops, holds, fades. The label, when there is one,
    sits at the tail of the arrow so it never covers the feature."""
    tail0, head0 = pointer_geometry(touch)
    hold = float(touch.get("hold", HOLD["pointer"]))
    draw_on, pop = 0.40, 0.25
    total = round((draw_on + pop + hold + OUT) * FPS)
    motion = touch.get("_motion") or [(0.0, 0.0)] * total
    tail, head = tail0, head0
    if art is not None:
        lx = int(tail[0] - art.width / 2)
        ly = int(tail[1] - art.height - 18) if tail[1] < head[1] else int(tail[1] + 18)
        lx = max(MARGIN_X, min(W - MARGIN_X - art.width, lx))
        ly = max(MARGIN_Y, min(H - MARGIN_Y - art.height, ly))
    for n in range(total):
        t = n / FPS
        reveal = ease(t / draw_on)
        ring = ease((t - draw_on) / pop) if t > draw_on else 0.0
        alpha = ease((draw_on + pop + hold + OUT - t) / OUT)
        mx, my = motion[min(n, len(motion) - 1)]
        tail = (tail0[0] + mx, tail0[1] + my)
        head = (head0[0] + mx, head0[1] + my)
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        paint_pointer(frame, tail, head, reveal, ring, alpha)
        if art is not None and t > draw_on * 0.5:
            k = min(ease((t - draw_on * 0.5) / IN), alpha)
            piece = art.copy()
            piece.putalpha(piece.getchannel("A").point(lambda v, k=k: int(v * k)))
            frame.alpha_composite(piece, (round(lx + mx), round(ly + my + 16 * (1 - k))))
        yield frame


def frames_for(touch: dict, art: Image.Image | None):
    """Yield every RGBA frame of one touch, 1920x1080."""
    kind = touch["kind"]
    if kind == "flash":
        total = FLASH_UP + FLASH_DOWN
        for n in range(total + 1):
            k = n / FLASH_UP if n <= FLASH_UP else 1 - (n - FLASH_UP) / FLASH_DOWN
            yield Image.new("RGBA", (W, H), (255, 255, 255, int(255 * FLASH_PEAK * max(0, k))))
        return

    if kind == "pointer":
        yield from pointer_frames(touch, art)
        return

    hold = float(touch.get("hold", HOLD[kind]))
    total = round((IN + hold + OUT) * FPS)
    corner = touch.get("corner", "bottom-left")
    x, y = place(corner, art.width, art.height)
    if "offset" in touch:
        x += int(touch["offset"][0])
        y += int(touch["offset"][1])
    from_left = "left" in corner
    for n in range(total):
        t = n / FPS
        k_in = ease(t / IN)
        k_out = ease((IN + hold + OUT - t) / OUT)
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if kind == "chapter":
            # wipes on from its own edge, slides back off the same way
            k = min(k_in, k_out)
            visible = max(1, round(art.width * k))
            # the bar leads on the left, the far edge leads on the right
            piece = art.crop((0, 0, visible, art.height)) if from_left \
                else art.crop((art.width - visible, 0, art.width, art.height))
            frame.alpha_composite(piece, (x, y) if from_left else (x + art.width - visible, y))
        elif kind in ("label", "pill"):
            k = min(k_in, k_out)
            rise = round(24 * (1 - k))
            piece = art.copy()
            piece.putalpha(piece.getchannel("A").point(lambda v, k=k: int(v * k)))
            frame.alpha_composite(piece, (x, y + rise))
        elif kind == "inset":
            k = min(k_in, k_out)
            s = 0.88 + 0.12 * k
            piece = art.resize((max(1, round(art.width * s)), max(1, round(art.height * s))),
                               Image.BILINEAR)
            piece.putalpha(piece.getchannel("A").point(lambda v, k=k: int(v * k)))
            frame.alpha_composite(piece, (x + (art.width - piece.width) // 2,
                                          y + (art.height - piece.height) // 2))
        else:
            bs.die(f"unknown touch kind {kind}")
        yield frame


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------

def touch_start(touch: dict) -> float:
    at = bs.to_seconds(str(touch["at"]))
    if touch["kind"] == "flash":
        return max(0.0, at - FLASH_UP / FPS)   # the peak lands on the cut frame
    return at


def render_overlays(spec: dict, body: Path, folder: Path, fonts: dict) -> list[dict]:
    folder.mkdir(parents=True, exist_ok=True)
    placed = []
    touches = sorted(spec["touches"], key=touch_start)
    for index, touch in enumerate(touches, 1):
        kind = touch["kind"]
        art = None
        if kind == "chapter":
            art = chapter_art(touch, fonts)
        elif kind == "label":
            art = label_art(touch, fonts)
        elif kind == "pill":
            art = pill_art(touch, fonts)
        elif kind == "inset":
            art = inset_art(touch, fonts, body)
        elif kind == "pointer":
            art = label_art(touch, fonts) if touch.get("text") else None
            if touch.get("track", True):
                at = bs.to_seconds(str(touch["at"]))
                seen = bs.to_seconds(str(touch.get("seen", touch["at"])))
                length = 0.65 + float(touch.get("hold", HOLD["pointer"])) + OUT
                touch = {**touch, "_motion": track_camera(body, at, length, seen)}
        name = touch.get("text") or {"inset": "before", "flash": "cut"}.get(kind, kind)
        stem = f"{index:02d}-{kind}-{bs.slugify(name)[:28]}"
        path = folder / f"{stem}.mov"
        encoder = subprocess.Popen(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo",
             "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
             "-c:v", "qtrle", "-pix_fmt", "argb", str(path)], stdin=subprocess.PIPE)
        count = 0
        peak = None
        for frame in frames_for(touch, art):
            encoder.stdin.write(frame.tobytes())
            count += 1
            if count == {"flash": FLASH_UP + 1, "pointer": round(0.75 * FPS)}.get(
                    kind, round(IN * FPS) + 2):
                peak = frame
        encoder.stdin.close()
        encoder.wait()
        start = touch_start(touch)
        placed.append({**touch, "file": path, "start": start, "frames": count,
                       "end": start + count / FPS, "peak": peak, "stem": stem})
        say(f"{timecode(start)}  {kind:7}  {touch.get('text', '')}")
    return placed


def write_markers(placed: list[dict], destination: Path) -> None:
    with destination.open("w", newline="", encoding="utf-8") as handle:
        out = csv.writer(handle)
        out.writerow(["timecode in", "timecode out", "kind", "text", "overlay file", "notes"])
        for touch in placed:
            out.writerow([timecode(touch["start"]), timecode(touch["end"]), touch["kind"],
                          touch.get("text", ""), touch["file"].name, touch.get("notes", "")])


def write_xml(spec: dict, placed: list[dict], body_name: str, body_frames: int,
              destination: Path) -> None:
    """FCP 7 XML. Premiere and Resolve both import it. Media paths point at the
    files by name, the editor asks for the folder once and relinks the rest."""
    rate = f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"
    fmt = ("<format><samplecharacteristics>" + rate +
           f"<width>{W}</width><height>{H}</height><pixelaspectratio>square</pixelaspectratio>"
           "</samplecharacteristics></format>")

    def clip(cid: str, fid: str, name: str, start: int, frames: int, path: str,
             audio: bool = False) -> str:
        media = f"<media><video><samplecharacteristics><width>{W}</width><height>{H}</height>" \
                "</samplecharacteristics></video>"
        if audio:
            media += "<audio><channelcount>2</channelcount></audio>"
        media += "</media>"
        return (f'<clipitem id="{cid}"><name>{escape(name)}</name><enabled>TRUE</enabled>'
                f"<duration>{frames}</duration>{rate}<start>{start}</start>"
                f"<end>{start + frames}</end><in>0</in><out>{frames}</out>"
                f'<file id="{fid}"><name>{escape(name)}</name>'
                f"<pathurl>{escape(path)}</pathurl>{rate}<duration>{frames}</duration>"
                f"{media}</file></clipitem>")

    v1 = clip("body-v", "body-file", body_name, 0, body_frames,
              f"file://localhost/{body_name}", audio=True)
    # one track holds no overlaps, so a touch that starts before the last one on
    # a track ends goes up a track (a flash under its chapter label, say)
    lanes: list[list[str]] = []
    lane_end: list[int] = []
    for n, t in enumerate(placed, 1):
        start = round(t["start"] * FPS)
        item = clip(f"touch-{n}", f"touch-file-{n}", t["file"].name, start, t["frames"],
                    f"file://localhost/overlays/{t['file'].name}")
        lane = next((i for i, end in enumerate(lane_end) if end <= start), None)
        if lane is None:
            lanes.append([])
            lane_end.append(0)
            lane = len(lanes) - 1
        lanes[lane].append(item)
        lane_end[lane] = start + t["frames"]
    overlays = "".join(f"<track>{''.join(items)}</track>" for items in lanes)
    audio = "".join(
        f'<track><clipitem id="body-a{ch}"><name>{escape(body_name)}</name>'
        f"<duration>{body_frames}</duration>{rate}<start>0</start><end>{body_frames}</end>"
        f'<in>0</in><out>{body_frames}</out><file id="body-file"/>'
        f"<sourcetrack><mediatype>audio</mediatype><trackindex>{ch}</trackindex></sourcetrack>"
        "</clipitem></track>" for ch in (1, 2))
    markers = "".join(f"<marker><name>{escape(t['kind'] + ' ' + t.get('text', ''))}</name>"
                      f"<in>{round(t['start'] * FPS)}</in><out>-1</out></marker>"
                      for t in placed if t["kind"] == "chapter")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
           f"<sequence><name>{escape(spec['project'])} finished body</name>"
           f"<duration>{body_frames}</duration>{rate}{markers}<media>"
           f"<video>{fmt}<track>{v1}</track>{overlays}</video>"
           f"<audio>{audio}</audio></media></sequence></xmeml>\n")
    destination.write_text(xml, encoding="utf-8")


def overlay_chain(placed: list[dict], offset: float = 0.0) -> tuple[list[str], str, str]:
    """Inputs and a filter graph that lays every overlay over [0:v] at its time."""
    inputs, chain, last = [], [], "[0:v]"
    for n, touch in enumerate(placed, 1):
        inputs += ["-itsoffset", f"{touch['start'] - offset:.3f}", "-i", str(touch["file"])]
        out = f"[v{n}]"
        chain.append(f"{last}[{n}:v]overlay=eof_action=pass:format=auto{out}")
        last = out
    return inputs, ";".join(chain), last


def render_reel(placed: list[dict], body: Path, work: Path, destination: Path) -> None:
    """Each touch over its own stretch of the body, then all of them back to back."""
    parts = []
    for touch in placed:
        begin = max(0.0, touch["start"] - REEL_PAD)
        length = (touch["end"] - touch["start"]) + 2 * REEL_PAD
        part = work / f"reel-{touch['stem']}.mp4"
        stampf = bs.find_font()
        label = f"{timecode(touch['start'])}  {touch['kind']}".replace(":", r"\:")
        draw = (f"drawtext=fontfile='{stampf}':text='{label}':x=24:y=h-52:fontsize=26:"
                "fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=8")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{begin:.3f}",
             "-t", f"{length:.3f}", "-i", str(body), "-itsoffset",
             f"{touch['start'] - begin:.3f}", "-i", str(touch["file"]),
             "-filter_complex", f"[0:v][1:v]overlay=eof_action=pass:format=auto,{draw},"
             "scale=1280:720[v]", "-map", "[v]", "-map", "0:a?", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "26", "-r", str(FPS), "-c:a", "aac", "-b:a",
             "96k", "-ar", "48000", "-ac", "2", str(part)])
        parts.append(part)
    listing = work / "reel.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(destination)])


def render_sheet(placed: list[dict], body: Path, destination: Path) -> None:
    tiles = []
    stampf = font(bs.find_font(), 22)
    for touch in placed:
        at = touch["start"] + {"flash": FLASH_UP / FPS, "pointer": 0.75}.get(touch["kind"], IN + 0.1)
        raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.3f}",
                              "-i", str(body), "-frames:v", "1", "-f", "image2pipe",
                              "-vcodec", "png", "-"], capture_output=True, check=True).stdout
        frame = Image.open(BytesIO(raw)).convert("RGBA")
        if touch["peak"] is not None:
            frame.alpha_composite(touch["peak"])
        tile = Image.new("RGB", (640, 392), "black")   # the stamp sits under the picture
        tile.paste(frame.convert("RGB").resize((640, 360), Image.LANCZOS), (0, 0))
        draw = ImageDraw.Draw(tile)
        draw.text((8, 364), f"{timecode(touch['start'])}  {touch['kind']}  {touch.get('text', '')}",
                  font=stampf, fill="white")
        tiles.append(tile)
    cols = 3
    rows = math.ceil(len(tiles) / cols)
    sheet = Image.new("RGB", (cols * 640, rows * 392), "black")
    for n, tile in enumerate(tiles):
        sheet.paste(tile, ((n % cols) * 640, (n // cols) * 392))
    sheet.save(destination, quality=86)


def render_full(placed: list[dict], body: Path, destination: Path) -> None:
    """The whole body with every touch burned in. Audio is copied untouched."""
    inputs, graph, last = overlay_chain(placed)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats", "-i", str(body),
         *inputs, "-filter_complex", graph, "-map", last, "-map", "0:a?",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-profile:v", "high", "-r", str(FPS), "-c:a", "copy", "-movflags", "+faststart",
         str(destination)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path, help="finishes/[slug].json")
    parser.add_argument("--full", action="store_true",
                        help="also render the whole body with the touches burned in")
    parser.add_argument("--no-reel", action="store_true", help="skip the review reel")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    slug = spec["slug"]
    body = REPO_ROOT / spec["body_file"]
    if not body.exists():
        bs.die(f"missing {body}, fetch the body first:\n"
               f"  python scripts/fetch_drive.py work/{slug} body/body.mp4=<body file id>")
    size = bs.probe(body, "v:0", "stream=width,height,r_frame_rate")
    if not size.startswith(f"{W},{H},{FPS}/1"):
        say(f"WARNING the body is {size}, the overlays are {W}x{H} at {FPS} fps")
    duration = bs.media_duration(body)
    body_frames = round(duration * FPS)

    folder = OUTPUT / f"{slug}-finish"
    work = REPO_ROOT / "work" / slug / "finish"
    if (folder / "overlays").exists():
        shutil.rmtree(folder / "overlays")   # numbering follows the spec, stale files mislead
    work.mkdir(parents=True, exist_ok=True)

    display = bs.find_font(bs.DISPLAY_FONT_CANDIDATES)
    body_font = bs.find_font()
    fonts = {"chapter": font(body_font, CHAPTER_SIZE), "kicker": font(body_font, KICKER_SIZE),
             "label": font(body_font, LABEL_SIZE), "pill": font(body_font, PILL_SIZE),
             "inset": font(display, 36)}

    print("Overlays", flush=True)
    placed = render_overlays(spec, body, folder / "overlays", fonts)
    for a, b in zip(placed, placed[1:]):
        if a["kind"] != "flash" and b["kind"] != "flash" and b["start"] < a["end"] \
                and a.get("corner", "bottom-left") == b.get("corner", "bottom-left"):
            say(f"WARNING {a['stem']} and {b['stem']} overlap in the same corner")
    minutes = duration / 60
    say(f"{len(placed)} touches over {minutes:.0f} minutes, "
        f"one every {minutes / max(1, len(placed)):.1f} minutes")

    print("Timeline", flush=True)
    xml = folder / f"{slug}-finish.xml"
    write_xml(spec, placed, spec.get("body_name", body.name), body_frames, xml)
    write_markers(placed, folder / "markers.csv")
    package = OUTPUT / f"{slug}-finish-package.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix in {".mov", ".xml", ".csv"}:
                archive.write(path, path.relative_to(folder))
    say(f"package {package}  {package.stat().st_size / 1e6:.1f}MB")

    print("Review", flush=True)
    sheet = OUTPUT / f"{slug}-finish-sheet.jpg"
    render_sheet(placed, body, sheet)
    say(f"sheet   {sheet}")
    if not args.no_reel:
        reel = OUTPUT / f"{slug}-finish-reel.mp4"
        render_reel(placed, body, work, reel)
        say(f"reel    {reel}  {reel.stat().st_size / 1e6:.1f}MB")

    if args.full:
        print("Full body", flush=True)
        final = OUTPUT / f"{slug}-body-finished.mp4"
        render_full(placed, body, final)
        say(f"full    {final}")


if __name__ == "__main__":
    main()
