#!/usr/bin/env python3
"""Build the 10 to 15 second cold open for a LONG video, 1920x1080, ready to drop
in front of the body in the editor.

    python scripts/build_intro.py intros/east-bench-phase-3.json

The intro is a separate piece from the Shorts pipeline and never touches it. It
borrows only the voice and caption helpers from build_short.py, so Mike's voice,
the respelling list and the caption grouping stay identical across both.

What it does, in order:

    1  voice     one ElevenLabs take of the whole script, cached by its text
    2  picture   each script line owns a stretch of the take, and its shots split
                 that stretch by weight: before/after wipes, side by side splits,
                 reveal clips, and the tease card over the last line
    3  mix       the VO, plus impact, whoosh and music if they sit in assets/
    4  sheet     one frame per shot, to check before calling it done

Finished files land in output/[slug]-intro.mp4 and output/[slug]-intro-sheet.jpg.
The picture matches the long video body: 1920x1080, 30 fps, H.264, AAC 48k stereo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import warnings  # noqa: E402
with warnings.catch_warnings():
    warnings.simplefilter("ignore", SyntaxWarning)
    import build_short as bs  # noqa: E402  voice, captions and asset helpers only

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps  # noqa: E402

REPO_ROOT = bs.REPO_ROOT
OUTPUT = bs.OUTPUT
W, H = 1920, 1080
FPS = 30

LEAD = 0.25                  # picture runs this long before the first word
TAIL = 0.55                  # held after the last word, the body cut lands here
TARGET = (10.0, 15.0)        # the brief, warned on rather than enforced
STILL_PUSH = 0.06            # slow push on a still, the only zoom there is
WIPE_AT = 0.45               # where in a wipe shot the after starts to come in
WIPE_SECONDS = 0.5
DIVIDER = 6                  # white line on a wipe edge and down a split

LABEL_SIZE = 46
LABEL_PAD_X, LABEL_PAD_Y = 18, 8
LABEL_MARGIN = 40
BEFORE_PLATE = (24, 24, 24)
AFTER_PLATE = bs.CAPTION_GREEN

CAPTION_SIZE = 50
CAPTION_LINE = 60
CAPTION_BOTTOM = 0.92        # bottom edge of the plate, fraction of height
CAPTION_WRAP = 0.8

CARD_TITLE_SIZE = 132
CARD_KICKER_SIZE = 46
CARD_DIM = 0.55
CARD_IN = 0.3
CARD_BLUR = 14             # background softens behind the card, so no word sits on a face

LOGO_WIDTH = 0.085           # of frame width, never enlarged past native pixels
LOGO_MARGIN = 40


def say(message: str) -> None:
    print(f"  {message}", flush=True)


def ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def font(path: str | None, size: int):
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


# --------------------------------------------------------------------------
# media
# --------------------------------------------------------------------------

def is_clip(ref) -> bool:
    return isinstance(ref, dict) and "src" in ref


def media_path(root: Path, ref) -> Path:
    path = root / (ref["src"] if is_clip(ref) else ref)
    if not path.exists():
        bs.die(f"missing media {path}, download it into {root} first")
    return path


class Still:
    """A photo, pre-scaled once, then cropped per frame for a slow push."""

    def __init__(self, path: Path, box: tuple[int, int], focus, push: float):
        image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        bw, bh = box
        scale = max(bw / image.width, bh / image.height) * (1 + push) * 1.05
        if scale < 1:
            image = image.resize((max(bw, round(image.width * scale)),
                                  max(bh, round(image.height * scale))), Image.LANCZOS)
        self.image, self.box, self.push = image, box, push
        self.focus = focus or (0.5, 0.5)

    def frame(self, t: float) -> Image.Image:
        bw, bh = self.box
        iw, ih = self.image.size
        base = min(iw / bw, ih / bh)           # cover: the box fits inside the image
        zoom = 1 + self.push * ease(t)
        cw, ch = bw * base / zoom, bh * base / zoom
        cx = min(max(self.focus[0] * iw, cw / 2), iw - cw / 2)
        cy = min(max(self.focus[1] * ih, ch / 2), ih - ch / 2)
        return self.image.transform(self.box, Image.EXTENT,
                                    (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2),
                                    Image.BILINEAR)


class Clip:
    """A stretch of a video, decoded frame by frame at the box size. No push, the
    footage is handheld and already moves."""

    def __init__(self, path: Path, at: float, seconds: float, box: tuple[int, int], focus):
        bw, bh = box
        fx = (focus or (0.5, 0.5))[0]
        fy = (focus or (0.5, 0.5))[1]
        crop = (f"scale={bw}:{bh}:force_original_aspect_ratio=increase,"
                f"crop={bw}:{bh}:(iw-{bw})*{fx:.3f}:(ih-{bh})*{fy:.3f}")
        self.box = box
        self.size = bw * bh * 3
        self.proc = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.3f}",
             "-i", str(path), "-t", f"{seconds + 0.5:.3f}", "-an",
             "-vf", f"fps={FPS},{crop}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.last = Image.new("RGB", box)

    def frame(self, t: float) -> Image.Image:
        data = self.proc.stdout.read(self.size)
        if len(data) == self.size:
            self.last = Image.frombytes("RGB", self.box, data)
        return self.last

    def close(self) -> None:
        self.proc.stdout.close()
        self.proc.kill()
        self.proc.wait()


def open_media(root: Path, ref, seconds: float, box, focus, push: float):
    path = media_path(root, ref)
    if is_clip(ref):
        return Clip(path, bs.to_seconds(str(ref["at"])), seconds, box,
                    ref.get("focus") or focus)
    return Still(path, box, focus, push)


# --------------------------------------------------------------------------
# graphics
# --------------------------------------------------------------------------

def draw_label(canvas: Image.Image, text: str, x: int, y: int, plate, fnt) -> None:
    draw = ImageDraw.Draw(canvas)
    l, t, r, b = draw.textbbox((0, 0), text, font=fnt)
    w, h = r - l, b - t
    draw.rectangle((x, y, x + w + 2 * LABEL_PAD_X, y + h + 2 * LABEL_PAD_Y), fill=plate)
    draw.text((x + LABEL_PAD_X - l, y + LABEL_PAD_Y - t), text, font=fnt, fill="white")


def wrap(text: str, fnt, width: int, draw) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and draw.textlength(trial, font=fnt) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


def caption_layer(text: str, fnt) -> Image.Image:
    """Spoken words on the house green plate, lower third, centred."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    lines = wrap(text.upper(), fnt, int(W * CAPTION_WRAP), draw)
    bottom = int(H * CAPTION_BOTTOM)
    top = bottom - CAPTION_LINE * len(lines)
    for index, line in enumerate(lines):
        l, t, r, b = draw.textbbox((0, 0), line, font=fnt)
        w = r - l
        x = (W - w) // 2
        y = top + index * CAPTION_LINE
        draw.rectangle((x - 14, y, x + w + 14, y + CAPTION_LINE), fill=bs.CAPTION_GREEN)
        draw.text((x - l, y + (CAPTION_LINE - (b - t)) // 2 - t), line, font=fnt,
                  fill="white", stroke_width=bs.CAPTION_STROKE, stroke_fill="black")
    return layer


def card_layer(card: dict, display: str | None, body: str | None) -> Image.Image:
    """The tease. Says what is coming, never the number."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    title = font(display, CARD_TITLE_SIZE)
    kicker = font(body, CARD_KICKER_SIZE)
    lines = card.get("title") or ["WHAT IT COST", "HOW LONG IT TOOK"]
    pitch = int(CARD_TITLE_SIZE * 1.12)
    block = pitch * len(lines) + 40 + CARD_KICKER_SIZE + 2 * LABEL_PAD_Y
    y = (H - block) // 2
    for line in lines:
        l, t, r, b = draw.textbbox((0, 0), line, font=title)
        draw.text(((W - (r - l)) // 2 - l, y - t), line, font=title, fill="white",
                  stroke_width=3, stroke_fill="black")
        y += pitch
    text = card.get("kicker") or "STAY TO THE END"
    l, t, r, b = draw.textbbox((0, 0), text, font=kicker)
    w = r - l + 2 * LABEL_PAD_X
    draw_label(layer, text, (W - w) // 2, y + 40, bs.CAPTION_GREEN, kicker)
    return layer


def logo_layer() -> Image.Image | None:
    path = bs.find_logo(None)
    if not path:
        say("no logo in assets/, building without the watermark")
        return None
    logo = Image.open(path).convert("RGBA")
    box = logo.getchannel("A").getbbox()
    if box:
        logo = logo.crop(box)
    target = min(int(W * LOGO_WIDTH), logo.width)
    logo = logo.resize((target, round(logo.height * target / logo.width)), Image.LANCZOS)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x, y = W - target - LOGO_MARGIN, LOGO_MARGIN
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", logo.size, (0, 0, 0, 130)), (x, y + 4), logo)
    layer = Image.alpha_composite(layer, shadow.filter(ImageFilter.GaussianBlur(6)))
    layer.paste(logo, (x, y), logo)
    return layer


# --------------------------------------------------------------------------
# voice
# --------------------------------------------------------------------------

def stage_voice(spec: dict, work: Path, force: bool) -> tuple[Path, list[tuple[float, float]], dict]:
    """One take of the whole script. Returns the mp3, each line's span, alignment."""
    bs.load_dotenv()
    texts = [bs.respell_for_voice(" ".join(line["vo"].split())) for line in spec["lines"]]
    joined = " ".join(texts)
    settings = spec.get("voice_settings") or {"stability": bs.VOICE_STABILITY,
                                              "style": bs.VOICE_STYLE,
                                              "similarity": bs.VOICE_SIMILARITY}
    key = hashlib.sha1(json.dumps([joined, settings], sort_keys=True).encode()).hexdigest()[:10]
    take = work / f"vo-{key}.mp3"
    alignment_path = take.with_suffix(".alignment.json")
    if force or not take.exists():
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        voice_id = os.environ.get("ELEVENLABS_VOICE_ID")
        if not api_key or not voice_id:
            bs.die("ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID are needed for the VO")
        say(f"rendering the VO, {len(joined.split())} words")
        bs.eleven_tts(joined, "", "", api_key, voice_id, bs.ELEVEN_DEFAULT_MODEL, take, settings)
    else:
        say(f"reusing {take.name}, the script has not changed")
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])
    if "".join(chars) != joined:
        say("alignment text differs from the script, line timings may drift")
    spans = bs.split_alignment_by_line(chars, starts, ends, texts)
    return take, spans, alignment


# --------------------------------------------------------------------------
# picture
# --------------------------------------------------------------------------

def plan(spec: dict, spans: list[tuple[float, float]], vo_end: float) -> tuple[list[dict], float]:
    """Each line owns from its first word to the next line's first word, and its
    shots split that by weight. The first line also owns the lead in."""
    total = LEAD + vo_end + TAIL
    bounds = [0.0] + [LEAD + start for start, _ in spans[1:]] + [total]
    shots = []
    for index, line in enumerate(spec["lines"]):
        start, end = bounds[index], bounds[index + 1]
        weights = [float(shot.get("weight", 1.0)) for shot in line["shots"]]
        cursor = start
        for shot, weight in zip(line["shots"], weights):
            length = (end - start) * weight / sum(weights)
            shots.append({**shot, "line": index, "start": cursor, "end": cursor + length})
            cursor += length
    return shots, total


def render_shot(shot: dict, root: Path, canvas_frames, fonts: dict) -> None:
    """Yields nothing, pushes frames into canvas_frames(t, image)."""
    kind = shot.get("type", "clip")
    seconds = shot["end"] - shot["start"]
    push = float(shot.get("push", STILL_PUSH))
    count = max(1, round(seconds * FPS))
    label_font = fonts["label"]

    if kind == "clip":
        media = open_media(root, shot["media"], seconds, (W, H), shot.get("focus"), push)
        for n in range(count):
            canvas_frames(shot["start"] + n / FPS, media.frame(n / count))
        getattr(media, "close", lambda: None)()
        return

    if kind == "split":
        half = (W - DIVIDER) // 2
        left = open_media(root, shot["before"], seconds, (half, H),
                          shot.get("before_focus"), push)
        right = open_media(root, shot["after"], seconds, (W - half - DIVIDER, H),
                           shot.get("after_focus"), push)
        for n in range(count):
            frame = Image.new("RGB", (W, H), "white")
            frame.paste(left.frame(n / count), (0, 0))
            frame.paste(right.frame(n / count), (half + DIVIDER, 0))
            draw_label(frame, "BEFORE", LABEL_MARGIN, LABEL_MARGIN, BEFORE_PLATE, label_font)
            draw_label(frame, "AFTER", half + DIVIDER + LABEL_MARGIN, LABEL_MARGIN,
                       AFTER_PLATE, label_font)
            canvas_frames(shot["start"] + n / FPS, frame)
        for media in (left, right):
            getattr(media, "close", lambda: None)()
        return

    if kind == "wipe":
        before = open_media(root, shot["before"], seconds, (W, H), shot.get("before_focus"), push)
        after = open_media(root, shot["after"], seconds, (W, H), shot.get("after_focus"), push)
        wipe_at = seconds * float(shot.get("wipe_at", WIPE_AT))
        for n in range(count):
            t = n / FPS
            progress = ease((t - wipe_at) / WIPE_SECONDS)
            # the after comes in from the right, so the BEFORE label in the top
            # left stays on before footage until the edge reaches it
            edge = round(W * (1 - progress))
            frame = before.frame(n / count).copy()
            after_frame = after.frame(n / count)
            if edge < W:
                frame.paste(after_frame.crop((edge, 0, W, H)), (edge, 0))
            if 0 < edge < W:
                ImageDraw.Draw(frame).rectangle((edge - DIVIDER // 2, 0, edge + DIVIDER // 2, H),
                                                fill="white")
            if edge > LABEL_MARGIN + 220:
                draw_label(frame, "BEFORE", LABEL_MARGIN, LABEL_MARGIN, BEFORE_PLATE, label_font)
            else:
                draw_label(frame, "AFTER", LABEL_MARGIN, LABEL_MARGIN, AFTER_PLATE, label_font)
            canvas_frames(shot["start"] + t, frame)
        return

    bs.die(f"unknown shot type {kind}")


def stage_picture(spec: dict, shots: list[dict], total: float, root: Path,
                  alignment: dict, spans, destination: Path, captions: bool) -> list[float]:
    body = bs.find_font()
    display = bs.find_font(bs.DISPLAY_FONT_CANDIDATES)
    fonts = {"label": font(display, LABEL_SIZE), "caption": font(body, CAPTION_SIZE)}
    logo = logo_layer()

    # caption cards in timeline seconds, none under a line that carries the card
    cards = []
    if captions:
        chars = alignment.get("characters", [])
        starts = alignment.get("character_start_times_seconds", [])
        ends = alignment.get("character_end_times_seconds", [])
        for index, (start, end) in enumerate(spans):
            if spec["lines"][index].get("card"):
                continue
            for phrase in bs.phrases_from_alignment(chars, starts, ends, start, end):
                text = " ".join(w["text"] for w in phrase["words"])
                cards.append((LEAD + phrase["start"], LEAD + phrase["end"],
                              caption_layer(text, fonts["caption"])))

    tease = []
    for index, line in enumerate(spec["lines"]):
        if line.get("card"):
            begin = LEAD + spans[index][0] + float(line["card"].get("delay", 0.0))
            tease.append((begin, card_layer(line["card"], display, body)))

    encoder = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p",
         str(destination)], stdin=subprocess.PIPE)
    frame_total = round(total * FPS)
    written = [0]
    held = [Image.new("RGB", (W, H))]
    grabs = [(shot["start"] + shot["end"]) / 2 for shot in shots]

    def emit(t: float, image: Image.Image) -> None:
        if written[0] >= frame_total:
            return
        t = written[0] / FPS
        held[0] = image
        frame = image.convert("RGBA")
        for begin, layer in tease:
            if t >= begin:
                k = ease((t - begin) / CARD_IN)
                frame = frame.filter(ImageFilter.GaussianBlur(CARD_BLUR * k))
                dim = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * CARD_DIM * k)))
                frame = Image.alpha_composite(frame, dim)
                card = layer
                if k < 1:
                    scale = 0.92 + 0.08 * k
                    card = layer.resize((round(W * scale), round(H * scale)), Image.BILINEAR)
                    pad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    pad.paste(card, ((W - card.width) // 2, (H - card.height) // 2))
                    alpha = pad.getchannel("A").point(lambda v, k=k: int(v * k))
                    pad.putalpha(alpha)
                    card = pad
                frame = Image.alpha_composite(frame, card)
        for begin, end, layer in cards:
            if begin <= t < end:
                frame = Image.alpha_composite(frame, layer)
        if logo:
            frame = Image.alpha_composite(frame, logo)
        encoder.stdin.write(frame.convert("RGB").tobytes())
        written[0] += 1

    for shot in shots:
        say(f"line {shot['line'] + 1}  {shot.get('type', 'clip'):5}  "
            f"{shot['start']:5.2f} to {shot['end']:5.2f}")
        render_shot(shot, root, emit, fonts)
    # rounding can leave a frame or two short, hold the last picture
    while written[0] < frame_total:
        emit(0, held[0])
    encoder.stdin.close()
    encoder.wait()
    return grabs


# --------------------------------------------------------------------------
# sound and finish
# --------------------------------------------------------------------------

def stage_mix(picture: Path, take: Path, shots: list[dict], total: float, destination: Path) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(picture),
           "-i", str(take)]
    lead = int(LEAD * 1000)
    chain = [f"[1:a]aresample=48000,adelay={lead}|{lead}[vo]"]
    labels = ["[vo]"]
    index = 2
    impact = bs.asset("impact.wav", "impact.mp3")
    if impact:
        cmd += ["-i", str(impact)]
        chain.append(f"[{index}:a]aresample=48000,volume=0.7[imp]")
        labels.append("[imp]")
        index += 1
    whoosh = bs.asset("whoosh.wav", "whoosh.mp3")
    wipes = [s["start"] + (s["end"] - s["start"]) * float(s.get("wipe_at", WIPE_AT))
             for s in shots if s.get("type") == "wipe"]
    if whoosh:
        for n, at in enumerate(wipes):
            cmd += ["-i", str(whoosh)]
            delay = int(max(0.0, at - 0.12) * 1000)
            chain.append(f"[{index}:a]aresample=48000,adelay={delay}|{delay},volume=0.55[w{n}]")
            labels.append(f"[w{n}]")
            index += 1
    music = bs.asset("music.mp3", "music.wav", "music.m4a")
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        chain.append(f"[{index}:a]aresample=48000,atrim=0:{total:.2f},asetpts=PTS-STARTPTS,"
                     "volume=0.06[music]")
        labels.append("[music]")
        index += 1
    missing = [name for name, found in (("impact", impact), ("whoosh", whoosh), ("music", music))
               if not found]
    if missing:
        say(f"not in assets/, built without: {', '.join(missing)}")
    chain.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
                 f"alimiter=limit=0.95,aresample=48000,apad,atrim=0:{total:.3f},"
                 "asetpts=N/SR/TB[aout]")
    cmd += ["-filter_complex", ";".join(chain), "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(destination)]
    subprocess.run(cmd, check=True)


def stage_sheet(final: Path, grabs: list[float], destination: Path) -> None:
    tiles = []
    for at in grabs:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.3f}",
                              "-i", str(final), "-frames:v", "1", "-vf", "scale=640:-2",
                              "-f", "image2pipe", "-vcodec", "png", "-"],
                             capture_output=True, check=True).stdout
        from io import BytesIO
        tiles.append(Image.open(BytesIO(out)).convert("RGB"))
    cols = 3
    rows = math.ceil(len(tiles) / cols)
    sheet = Image.new("RGB", (cols * 640, rows * 360), "black")
    for n, tile in enumerate(tiles):
        sheet.paste(tile, ((n % cols) * 640, (n // cols) * 360))
    sheet.save(destination, quality=88)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path, help="intros/[slug].json")
    parser.add_argument("--revoice", action="store_true", help="render the VO again")
    parser.add_argument("--no-captions", action="store_true", help="no spoken word captions")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    slug = spec["slug"]
    root = REPO_ROOT / spec.get("media_root", f"work/{slug}")
    work = REPO_ROOT / "work" / slug / "intro"
    work.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)

    print("Voice", flush=True)
    take, spans, alignment = stage_voice(spec, work, args.revoice)
    vo_end = spans[-1][1]
    shots, total = plan(spec, spans, vo_end)
    words = sum(len(line["vo"].split()) for line in spec["lines"])
    say(f"{words} words, read runs {vo_end:.2f}s, intro runs {total:.2f}s")
    if not TARGET[0] <= total <= TARGET[1]:
        say(f"WARNING the intro is {total:.1f}s, the brief is {TARGET[0]:.0f} to "
            f"{TARGET[1]:.0f}s. Cut or add words, not pauses.")

    print("Picture", flush=True)
    picture = work / "picture.mp4"
    grabs = stage_picture(spec, shots, total, root, alignment, spans, picture,
                          not args.no_captions)

    print("Mix", flush=True)
    final = OUTPUT / f"{slug}-intro.mp4"
    stage_mix(picture, take, shots, total, final)

    print("Sheet", flush=True)
    sheet = OUTPUT / f"{slug}-intro-sheet.jpg"
    stage_sheet(final, grabs, sheet)
    say(f"intro  {final}")
    say(f"sheet  {sheet}")


if __name__ == "__main__":
    main()
