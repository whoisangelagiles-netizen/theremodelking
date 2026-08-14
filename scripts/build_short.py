#!/usr/bin/env python3
"""Build a FINISHED, publish-ready Short from a YouTube URL. No editing pass after.

    python scripts/build_short.py "https://www.youtube.com/watch?v=VIDEO_ID" 1

The run has two points where it stops and hands back to Claude, because both
steps need judgement rather than arithmetic:

    stage 1  guide      transcript is fetched, then Claude writes the guide JSON
    stage 2  download   source video pulled at highest quality with yt-dlp
    stage 3  analyze    keyframes extracted per scene, then Claude LOOKS at them
                        and fills in crop offsets, punch-in targets, and arrow
                        and highlight box coordinates in edits.json
    stage 4  vo         ElevenLabs synthesis of the full combined read
    stage 5  assemble   cut, crop, punch in, annotate, caption, mix, export
    stage 6  sheet      contact sheet, one frame per scene

Rerun the same command after each pause and it picks up where it stopped.
Pass --auto to skip the frame analysis and take safe center-crop defaults.

Everything intermediate lives in work/[video_id]/, finished files in output/.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import subprocess
import sys
import textwrap
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
GUIDES = REPO_ROOT / "guides"
WORK = REPO_ROOT / "work"
OUTPUT = REPO_ROOT / "output"
ASSETS = REPO_ROOT / "assets"

BRAND_GREEN = (14, 147, 70)
W, H = 1080, 1920
FPS = 30
CTA_SECONDS = 2.4
MIN_SCENE_SECONDS = 1.2

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

ELEVEN_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVEN_DEFAULT_MODEL = "eleven_multilingual_v2"


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def say(message: str) -> None:
    print(f"  {message}", flush=True)


def stage(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def die(message: str, code: int = 1):
    print(f"\nSTOPPED: {message}\n", file=sys.stderr)
    sys.exit(code)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-15:]
        die(f"command failed: {' '.join(cmd[:3])} ...\n" + "\n".join(tail))
    return result


def to_seconds(value: str) -> float:
    parts = [p.strip() for p in str(value).replace(",", ".").split(":")]
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part or 0)
    return seconds


def stamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def parse_range(value: str) -> tuple[float, float]:
    text = str(value).replace("to", "-").replace("\u2013", "-")
    bits = [b.strip() for b in text.split("-") if b.strip()]
    if len(bits) < 2:
        die(f"cannot read a timestamp range from {value!r}, expected MM:SS - MM:SS")
    return to_seconds(bits[0]), to_seconds(bits[1])


def slugify(value: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower() or "short"


def probe(path: Path, stream: str, entries: str) -> str:
    result = run(["ffprobe", "-v", "error", "-select_streams", stream,
                  "-show_entries", entries, "-of", "csv=p=0", str(path)])
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def media_duration(path: Path) -> float:
    value = probe(path, "v:0", "format=duration") or probe(path, "a:0", "format=duration")
    if not value:
        result = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", str(path)])
        value = result.stdout.strip()
    return float(value.split(",")[0])


def has_audio(path: Path) -> bool:
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                            capture_output=True, text=True)
    return bool(result.stdout.strip())


def find_font() -> str | None:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def asset(*names: str) -> Path | None:
    """First existing asset among the given names, else None."""
    for name in names:
        path = ASSETS / name
        if path.exists():
            return path
        matches = sorted(ASSETS.glob(f"{Path(name).stem}.*"))
        if matches:
            return matches[0]
    return None


# --------------------------------------------------------------------------
# guide and scene model
# --------------------------------------------------------------------------

@dataclass
class Scene:
    number: int
    start: float
    end: float
    vo: str
    caption: str
    notes: str
    caption_zone: str = "support"
    overlay: str | None = None
    transition: str | None = None
    punch_in: dict | None = None
    annotations: list = field(default_factory=list)
    crop_x: float = 0.5
    source_label: str = ""

    @property
    def duration(self) -> float:
        return max(0.4, self.end - self.start)


def wants_punch_in(notes: str) -> bool:
    return any(word in notes.lower() for word in ("punch", "push in", "zoom"))


def wanted_annotations(notes: str) -> list[dict]:
    lowered = notes.lower()
    wanted = []
    if "arrow" in lowered:
        wanted.append({"type": "arrow", "target": "", "from": None, "to": None})
    if "highlight" in lowered or "box" in lowered:
        wanted.append({"type": "box", "target": "", "x": None, "y": None, "w": None, "h": None})
    return wanted


def find_guide(video_id: str, explicit: Path | None) -> Path | None:
    if explicit:
        return explicit if explicit.exists() else None
    if not GUIDES.exists():
        return None
    for path in sorted(GUIDES.glob("*.json")):
        if path.name == "example.schema.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if video_id in json.dumps(data.get("video_url", "")) or video_id == data.get("video_id"):
            return path
    return None


def load_short(guide_path: Path, index: int) -> tuple[dict, dict]:
    guide = json.loads(guide_path.read_text(encoding="utf-8"))
    shorts = guide.get("shorts") or []
    if not 1 <= index <= len(shorts):
        die(f"{guide_path.name} holds {len(shorts)} Shorts, cannot build number {index}")
    return guide, shorts[index - 1]


def scenes_from_short(short: dict) -> list[Scene]:
    scenes = []
    for position, raw in enumerate(short.get("scenes") or [], start=1):
        start, end = parse_range(raw.get("source", ""))
        notes = raw.get("notes", "") or ""
        scenes.append(Scene(
            number=int(raw.get("number") or position),
            start=start,
            end=end,
            vo=raw.get("vo", "") or "",
            caption=raw.get("caption", "") or "",
            notes=notes,
            caption_zone=raw.get("caption_zone") or ("hook" if position == 1 else "support"),
            overlay=raw.get("overlay"),
            transition=raw.get("transition"),
            source_label=raw.get("source", ""),
        ))
    if not scenes:
        die("this Short has no scenes in the guide JSON")
    return scenes


# --------------------------------------------------------------------------
# stage 1: transcript and guide
# --------------------------------------------------------------------------

def stage_guide(url: str, video_id: str, guide_arg: Path | None, render_pdf: bool) -> Path:
    stage("Stage 1, transcript and production guide")
    transcript = REPO_ROOT / "transcripts" / f"{video_id}.json"
    if not transcript.exists():
        say("fetching transcript...")
        run([sys.executable, str(SCRIPTS / "fetch_transcript.py"), url])
    say(f"transcript: {transcript.relative_to(REPO_ROOT)}")

    guide_path = find_guide(video_id, guide_arg)
    if guide_path is None:
        die(
            "no production guide found for this video.\n"
            f"  Read {transcript.relative_to(REPO_ROOT)}, build the guide with the\n"
            "  shorts-production-guide skill, save it to guides/[slug].json with\n"
            f'  "video_url" carrying {video_id}, then run this command again.'
        )
    say(f"guide: {guide_path.relative_to(REPO_ROOT)}")

    if render_pdf:
        subprocess.run([sys.executable, str(SCRIPTS / "render_guide.py"), str(guide_path)],
                       capture_output=True, text=True)
    return guide_path


# --------------------------------------------------------------------------
# stage 2: source video
# --------------------------------------------------------------------------

def stage_download(url: str, work: Path, force: bool) -> Path:
    stage("Stage 2, source video")
    source = work / "source.mp4"
    if source.exists() and not force:
        say(f"cached: {source.relative_to(REPO_ROOT)}")
        return source
    say("downloading highest quality source with yt-dlp, this can take a while...")
    run(["yt-dlp",
         "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
         "--merge-output-format", "mp4",
         "-o", str(source), url])
    if not source.exists():
        die("yt-dlp finished but no source.mp4 landed in the work folder")
    say(f"source: {source.relative_to(REPO_ROOT)}, {stamp(media_duration(source))}")
    return source


# --------------------------------------------------------------------------
# stage 3: keyframes and edit decisions
# --------------------------------------------------------------------------

def extract_keyframes(source: Path, scene: Scene, frames_dir: Path, count: int = 4) -> list[Path]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob(f"scene{scene.number:02d}_*.jpg"):
        old.unlink()
    span = scene.duration
    offsets = [scene.start + span * (index + 0.5) / count for index in range(count)]
    written = []
    for index, offset in enumerate(offsets, start=1):
        target = frames_dir / f"scene{scene.number:02d}_{index}.jpg"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{offset:.2f}", "-i", str(source),
             "-frames:v", "1", "-q:v", "3", str(target)])
        if target.exists():
            written.append(target)
    return written


def edit_skeleton(scenes: list[Scene], video_id: str, index: int, frames_dir: Path) -> dict:
    return {
        "video_id": video_id,
        "short": index,
        "analyzed": False,
        "_how_to_fill_this_in": [
            "Look at every frame listed under each scene before writing numbers.",
            "All coordinates are normalized 0 to 1 against the FULL SOURCE frame you "
            "are looking at, not the cropped Short. The build maps them for you.",
            "crop_x is the horizontal center of the 9:16 window. 0.5 is dead center. "
            "Move it so the subject and the feature the VO names stay in frame.",
            "punch_in is null when the editor notes do not ask for one, otherwise "
            '{"zoom": 1.15 to 1.6, "focus": [x, y]} aimed at the feature.',
            'box annotations are {"type":"box","target":"...","x":..,"y":..,"w":..,"h":..} '
            "with x and y the top left corner.",
            'arrow annotations are {"type":"arrow","target":"...","from":[x,y],"to":[x,y]} '
            "with the arrowhead landing on the feature.",
            "If the frames do not show what the VO line describes, change source to a "
            "better range from the transcript and rerun with --rescan to re-extract.",
            'Set "analyzed": true when every scene is done.',
        ],
        "scenes": [
            {
                "scene": scene.number,
                "vo": scene.vo,
                "editor_notes": scene.notes,
                "source": scene.source_label or f"{stamp(scene.start)} - {stamp(scene.end)}",
                "frames": [str((frames_dir / f"scene{scene.number:02d}_{i}.jpg")
                               .relative_to(REPO_ROOT)) for i in range(1, 5)],
                "crop_x": 0.5,
                "punch_in": {"zoom": 1.28, "focus": [0.5, 0.45]} if wants_punch_in(scene.notes) else None,
                "annotations": wanted_annotations(scene.notes),
                "frames_show_what_the_vo_says": None,
                "analysis_note": "",
            }
            for scene in scenes
        ],
    }


def stage_analyze(source: Path, scenes: list[Scene], work: Path, video_id: str,
                  index: int, auto: bool, rescan: set[int] | None) -> dict:
    stage("Stage 3, frame analysis")
    frames_dir = work / f"short{index}" / "frames"
    edits_path = work / f"short{index}" / "edits.json"
    edits_path.parent.mkdir(parents=True, exist_ok=True)

    existing = json.loads(edits_path.read_text(encoding="utf-8")) if edits_path.exists() else None

    if existing and rescan:
        by_number = {entry["scene"]: entry for entry in existing["scenes"]}
        for scene in scenes:
            if scene.number in rescan and scene.number in by_number:
                revised = by_number[scene.number].get("source")
                if revised:
                    scene.start, scene.end = parse_range(revised)
                say(f"re-extracting scene {scene.number} at {revised}")
                extract_keyframes(source, scene, frames_dir)
        die("frames re-extracted. Look at the new ones, update edits.json, rerun without --rescan.",
            code=2)

    if existing is None:
        for scene in scenes:
            say(f"scene {scene.number}: keyframes from {stamp(scene.start)} to {stamp(scene.end)}")
            extract_keyframes(source, scene, frames_dir)
        skeleton = edit_skeleton(scenes, video_id, index, frames_dir)
        edits_path.write_text(json.dumps(skeleton, indent=2), encoding="utf-8")
        existing = skeleton

    if auto:
        say("--auto, taking center crop defaults without visual analysis")
        return existing

    if not existing.get("analyzed"):
        die(
            "frames are waiting on your eyes.\n"
            f"  Frames:    {frames_dir.relative_to(REPO_ROOT)}\n"
            f"  Decisions: {edits_path.relative_to(REPO_ROOT)}\n"
            "  Look at every frame, fill in crop_x, punch_in, and annotation coordinates,\n"
            '  set "analyzed": true, then run this same command again.',
            code=2,
        )
    say(f"edit decisions: {edits_path.relative_to(REPO_ROOT)}")
    return existing


def apply_edits(scenes: list[Scene], edits: dict) -> None:
    by_number = {int(entry["scene"]): entry for entry in edits.get("scenes", [])}
    for scene in scenes:
        entry = by_number.get(scene.number)
        if not entry:
            continue
        if entry.get("source"):
            scene.start, scene.end = parse_range(entry["source"])
            scene.source_label = entry["source"]
        scene.crop_x = float(entry.get("crop_x", 0.5) or 0.5)
        punch = entry.get("punch_in")
        if punch and punch.get("zoom"):
            focus = punch.get("focus") or [0.5, 0.5]
            scene.punch_in = {"zoom": float(punch["zoom"]),
                              "focus": [float(focus[0]), float(focus[1])]}
        wanted = entry.get("annotations") or []
        scene.annotations = [a for a in wanted if annotation_is_placed(a)]
        for dropped in [a for a in wanted if not annotation_is_placed(a)]:
            say(f"scene {scene.number}: {dropped.get('type', 'annotation')} for "
                f"{dropped.get('target') or 'an unnamed feature'} has no coordinates, dropped")
        if entry.get("frames_show_what_the_vo_says") is False:
            say(f"scene {scene.number}: marked as not matching the VO line, "
                "the footage still needs a better range")
        if entry.get("overlay"):
            scene.overlay = entry["overlay"]


def annotation_is_placed(annotation: dict) -> bool:
    if annotation.get("type") == "box":
        return all(annotation.get(key) is not None for key in ("x", "y", "w", "h"))
    if annotation.get("type") == "arrow":
        return annotation.get("from") is not None and annotation.get("to") is not None
    return False


# --------------------------------------------------------------------------
# stage 4: voice over
# --------------------------------------------------------------------------

def stage_vo(short: dict, work: Path, index: int, skip: bool, force: bool,
             voice_id: str | None, model_id: str) -> Path | None:
    stage("Stage 4, ElevenLabs voice over")
    vo_path = work / f"short{index}" / "vo.mp3"
    if vo_path.exists() and not force:
        say(f"cached: {vo_path.relative_to(REPO_ROOT)}, {media_duration(vo_path):.1f}s")
        return vo_path
    if skip:
        say("--skip-vo, building picture with no narration track")
        return None

    text = (short.get("full_vo") or "").strip()
    if not text:
        die("the guide has no full_vo block for this Short, nothing to synthesize")

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        die("ELEVENLABS_API_KEY is not set. Export it in your shell, never commit it.\n"
            "  Or rerun with --skip-vo to build the picture without narration.")
    voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID")
    if not voice_id:
        die("no voice id. Pass --voice-id or export ELEVENLABS_VOICE_ID with Mike's voice.")

    payload = json.dumps({
        "text": text,
        "model_id": model_id,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8,
                           "style": 0.35, "use_speaker_boost": True},
    }).encode("utf-8")
    request = urllib.request.Request(
        ELEVEN_ENDPOINT.format(voice_id=voice_id) + "?output_format=mp3_44100_128",
        data=payload,
        headers={"xi-api-key": api_key, "Content-Type": "application/json",
                 "Accept": "audio/mpeg"},
    )
    ca_bundle = (os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
                 or os.environ.get("CURL_CA_BUNDLE"))
    context = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else ssl.create_default_context()

    say(f"synthesizing {len(text.split())} words with {model_id}...")
    try:
        with urllib.request.urlopen(request, context=context, timeout=180) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:  # noqa: PERF203
        die(f"ElevenLabs returned {exc.code}: {exc.read()[:400].decode('utf-8', 'replace')}")
    except Exception as exc:  # noqa: BLE001
        die(f"ElevenLabs request failed: {type(exc).__name__}: {exc}")

    vo_path.parent.mkdir(parents=True, exist_ok=True)
    vo_path.write_bytes(audio)
    say(f"voice over: {vo_path.relative_to(REPO_ROOT)}, {media_duration(vo_path):.1f}s")
    return vo_path


def fit_scenes_to_vo(scenes: list[Scene], vo_seconds: float, source_seconds: float) -> None:
    """Stretch or tighten scene out-points so picture and narration land together."""
    body = sum(scene.duration for scene in scenes)
    if vo_seconds <= 0 or abs(vo_seconds - body) < 0.25:
        return
    factor = vo_seconds / body
    say(f"fitting picture to narration, {body:.1f}s of footage against {vo_seconds:.1f}s of VO")
    if factor > 1.5:
        say("the narration runs well past the footage in the guide. Scenes are being "
            "stretched hard, consider longer source ranges in the scene table.")
    for scene in scenes:
        wanted = max(MIN_SCENE_SECONDS, scene.duration * factor)
        scene.end = min(source_seconds, scene.start + wanted)
    drift = vo_seconds - sum(scene.duration for scene in scenes)
    if drift > 0.2:
        last = scenes[-1]
        last.end = min(source_seconds, last.end + drift)


# --------------------------------------------------------------------------
# overlays drawn with Pillow
# --------------------------------------------------------------------------

def crop_window(src_w: int, src_h: int, crop_x: float) -> tuple[int, int, int, int]:
    target = 9 / 16
    crop_w = min(src_w, int(round(src_h * target)))
    crop_h = min(src_h, int(round(crop_w / target)))
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2
    x0 = int(round(crop_x * src_w - crop_w / 2))
    x0 = max(0, min(src_w - crop_w, x0))
    y0 = max(0, (src_h - crop_h) // 2)
    return crop_w, crop_h, x0, y0


def to_frame(sx: float, sy: float, src_w: int, src_h: int, window) -> tuple[float, float]:
    """Source normalized coordinates into final 1080x1920 pixel coordinates."""
    crop_w, crop_h, x0, y0 = window
    fx = (sx * src_w - x0) / crop_w
    fy = (sy * src_h - y0) / crop_h
    return max(0.0, min(1.0, fx)) * W, max(0.0, min(1.0, fy)) * H


def draw_annotations(scene: Scene, src_w: int, src_h: int, window, path: Path) -> Path | None:
    from PIL import Image, ImageDraw

    if not scene.annotations:
        return None
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    drew = False

    for annotation in scene.annotations:
        kind = annotation.get("type")
        if kind == "box":
            x1, y1 = to_frame(annotation["x"], annotation["y"], src_w, src_h, window)
            x2, y2 = to_frame(annotation["x"] + annotation["w"],
                              annotation["y"] + annotation["h"], src_w, src_h, window)
            if x2 - x1 < 8 or y2 - y1 < 8:
                say(f"scene {scene.number}: highlight box falls outside the crop, skipped")
                continue
            draw.rounded_rectangle([x1, y1, x2, y2], radius=18,
                                   outline=BRAND_GREEN + (255,), width=8)
            drew = True
        elif kind == "arrow":
            x1, y1 = to_frame(*annotation["from"], src_w, src_h, window)
            x2, y2 = to_frame(*annotation["to"], src_w, src_h, window)
            drew = draw_arrow(draw, x1, y1, x2, y2) or drew

    if not drew:
        return None
    canvas.save(path)
    return path


def draw_arrow(draw, x1: float, y1: float, x2: float, y2: float) -> bool:
    import math

    length = math.hypot(x2 - x1, y2 - y1)
    if length < 30:
        return False
    angle = math.atan2(y2 - y1, x2 - x1)
    head = min(58.0, length * 0.34)
    shaft_x = x2 - math.cos(angle) * head * 0.82
    shaft_y = y2 - math.sin(angle) * head * 0.82
    draw.line([x1, y1, shaft_x, shaft_y], fill=BRAND_GREEN + (255,), width=11)
    spread = math.radians(26)
    draw.polygon([
        (x2, y2),
        (x2 - math.cos(angle - spread) * head, y2 - math.sin(angle - spread) * head),
        (x2 - math.cos(angle + spread) * head, y2 - math.sin(angle + spread) * head),
    ], fill=BRAND_GREEN + (255,))
    return True


def wrap_caption(text: str, font, max_width: int, draw) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_caption(text: str, zone: str, font_path: str | None, path: Path) -> Path | None:
    from PIL import Image, ImageDraw, ImageFont

    text = (text or "").strip()
    if not text:
        return None
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    size = 86 if zone == "hook" else 68
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size)

    lines = wrap_caption(text.upper(), font, int(W * 0.84), draw)
    line_height = size * 1.22
    block = line_height * len(lines)
    top = H * 0.20 - block / 2 if zone == "hook" else H * 0.78 - block / 2

    for row, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        draw.text((W / 2 - width / 2, top + row * line_height), line, font=font,
                  fill=(255, 255, 255, 255), stroke_width=max(6, size // 12),
                  stroke_fill=(0, 0, 0, 255))
    canvas.save(path)
    return path


def draw_cta_frame(text: str, font_path: str | None, path: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.new("RGB", (W, H), (22, 24, 26))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(font_path, 92) if font_path else ImageFont.load_default(92)

    lines = wrap_caption(text.strip().upper(), font, int(W * 0.8), draw)
    line_height = 92 * 1.24
    top = H / 2 - (line_height * len(lines)) / 2
    for row, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        draw.text((W / 2 - width / 2, top + row * line_height), line, font=font,
                  fill=(255, 255, 255))
    bar = 14
    draw.rectangle([0, H // 2 - int(line_height * len(lines) / 2) - 90,
                    W, H // 2 - int(line_height * len(lines) / 2) - 90 + bar], fill=BRAND_GREEN)
    canvas.save(path)
    return path


# --------------------------------------------------------------------------
# stage 5: assembly
# --------------------------------------------------------------------------

def render_scene(scene: Scene, source: Path, src_w: int, src_h: int, src_has_audio: bool,
                 work: Path, font_path: str | None, destination: Path) -> None:
    window = crop_window(src_w, src_h, scene.crop_x)
    crop_w, crop_h, x0, y0 = window
    parts = work / "parts"
    parts.mkdir(parents=True, exist_ok=True)

    annotation_png = draw_annotations(scene, src_w, src_h, window,
                                      parts / f"ann{scene.number:02d}.png")
    caption_png = draw_caption(scene.caption, scene.caption_zone, font_path,
                               parts / f"cap{scene.number:02d}.png")
    overlay_mov = None
    if scene.overlay:
        overlay_mov = asset(f"overlays/{scene.overlay}", scene.overlay)
        if overlay_mov is None:
            say(f"scene {scene.number}: overlay {scene.overlay} missing from assets/, skipped")

    duration = scene.duration
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{scene.start:.2f}", "-t", f"{duration:.2f}", "-i", str(source)]
    index = 1
    ann_index = cap_index = ov_index = None
    if annotation_png:
        cmd += ["-loop", "1", "-t", f"{duration:.2f}", "-i", str(annotation_png)]
        ann_index = index
        index += 1
    if caption_png:
        cmd += ["-loop", "1", "-t", f"{duration:.2f}", "-i", str(caption_png)]
        cap_index = index
        index += 1
    if overlay_mov:
        cmd += ["-i", str(overlay_mov)]
        ov_index = index
        index += 1

    chain = [f"[0:v]crop={crop_w}:{crop_h}:{x0}:{y0},scale={W}:{H},setsar=1,fps={FPS}[base]"]
    label = "base"

    if ann_index is not None:
        chain.append(f"[{ann_index}:v]scale={W}:{H}[ann]")
        chain.append(f"[{label}][ann]overlay=0:0:format=auto[anned]")
        label = "anned"

    if scene.punch_in:
        zoom = max(1.01, min(2.0, float(scene.punch_in["zoom"])))
        fx, fy = scene.punch_in["focus"]
        px, py = to_frame(fx, fy, src_w, src_h, window)
        fx_n, fy_n = px / W, py / H
        frames = max(2, int(duration * FPS))
        step = (zoom - 1.0) / (frames - 1)
        zexpr = f"min(1+{step:.6f}*on,{zoom:.4f})"
        xexpr = f"max(0,min(iw-iw/zoom,{fx_n:.4f}*iw*(1-1/zoom)))"
        yexpr = f"max(0,min(ih-ih/zoom,{fy_n:.4f}*ih*(1-1/zoom)))"
        chain.append(f"[{label}]zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':"
                     f"d=1:s={W}x{H}:fps={FPS}[zoomed]")
        label = "zoomed"

    if cap_index is not None:
        chain.append(f"[{cap_index}:v]scale={W}:{H}[cap]")
        chain.append(f"[{label}][cap]overlay=0:0:format=auto[capped]")
        label = "capped"

    if ov_index is not None:
        chain.append(f"[{ov_index}:v]scale={W}:{H},setsar=1[ovl]")
        chain.append(f"[{label}][ovl]overlay=0:0:format=auto:shortest=0:eof_action=pass[out]")
        label = "out"

    chain.append(f"[{label}]format=yuv420p[v]")

    if src_has_audio:
        chain.append("[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a]")
    else:
        cmd += ["-f", "lavfi", "-t", f"{duration:.2f}",
                "-i", "anullsrc=r=48000:cl=stereo"]
        chain.append(f"[{index}:a]anull[a]")

    cmd += ["-filter_complex", ";".join(chain), "-map", "[v]", "-map", "[a]",
            "-t", f"{duration:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-video_track_timescale", "30000", str(destination)]
    run(cmd)


def render_cta(text: str, font_path: str | None, work: Path, destination: Path) -> None:
    png = draw_cta_frame(text, font_path, work / "parts" / "cta.png")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-loop", "1", "-t", f"{CTA_SECONDS}", "-i", str(png),
         "-f", "lavfi", "-t", f"{CTA_SECONDS}", "-i", "anullsrc=r=48000:cl=stereo",
         "-vf", f"scale={W}:{H},setsar=1,fps={FPS},format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         "-video_track_timescale", "30000", str(destination)])


def mix_audio(body: Path, vo: Path | None, whoosh_at: float | None,
              music: Path | None, destination: Path) -> None:
    whoosh = asset("whoosh.wav", "whoosh.mp3")
    impact = asset("impact.wav", "impact.mp3")
    duration = media_duration(body)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(body)]
    chain, mix_labels = [], []
    index = 1

    chain.append("[0:a]volume=0.03[orig]")
    mix_labels.append("[orig]")

    if vo:
        cmd += ["-i", str(vo)]
        chain.append(f"[{index}:a]aresample=48000,volume=1.0[vo]")
        mix_labels.append("[vo]")
        index += 1

    if impact:
        cmd += ["-i", str(impact)]
        chain.append(f"[{index}:a]aresample=48000,volume=0.7[imp]")
        mix_labels.append("[imp]")
        index += 1
    else:
        say("assets/impact.wav missing, hook lands without the impact hit")

    if whoosh and whoosh_at is not None:
        cmd += ["-i", str(whoosh)]
        delay = int(max(0.0, whoosh_at - 0.12) * 1000)
        chain.append(f"[{index}:a]aresample=48000,adelay={delay}|{delay},volume=0.55[whoosh]")
        mix_labels.append("[whoosh]")
        index += 1
    elif whoosh_at is not None:
        say("assets/whoosh.wav missing, the transition plays without a whoosh")

    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        chain.append(f"[{index}:a]aresample=48000,atrim=0:{duration:.2f},"
                     f"asetpts=PTS-STARTPTS,volume=0.06[music]")
        mix_labels.append("[music]")
        index += 1

    chain.append("".join(mix_labels) +
                 f"amix=inputs={len(mix_labels)}:duration=first:normalize=0,"
                 "alimiter=limit=0.95,aresample=48000[aout]")

    cmd += ["-filter_complex", ";".join(chain), "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(destination)]
    run(cmd)


def stage_assemble(scenes: list[Scene], short: dict, source: Path, vo: Path | None,
                   work: Path, index: int, slug: str, font_path: str | None,
                   music: Path | None) -> tuple[Path, list[float]]:
    stage("Stage 5, assembly")
    src_w = int(probe(source, "v:0", "stream=width"))
    src_h = int(probe(source, "v:0", "stream=height"))
    src_audio = has_audio(source)
    source_seconds = media_duration(source)
    say(f"source is {src_w}x{src_h}, cropping to {W}x{H}")

    for scene in scenes:
        if scene.end > source_seconds:
            scene.end = source_seconds
        if scene.start >= source_seconds:
            die(f"scene {scene.number} starts past the end of the source video")

    if vo:
        fit_scenes_to_vo(scenes, media_duration(vo), source_seconds)

    parts = work / "parts"
    if parts.exists():
        shutil.rmtree(parts)
    parts.mkdir(parents=True)

    clips, starts, elapsed = [], [], 0.0
    for scene in scenes:
        clip = parts / f"scene{scene.number:02d}.mp4"
        say(f"scene {scene.number}: {stamp(scene.start)} to {stamp(scene.end)}, "
            f"crop_x {scene.crop_x:.2f}"
            f"{', punch in' if scene.punch_in else ''}"
            f"{', ' + str(len(scene.annotations)) + ' annotation(s)' if scene.annotations else ''}")
        render_scene(scene, source, src_w, src_h, src_audio, work, font_path, clip)
        clips.append(clip)
        starts.append(elapsed)
        elapsed += media_duration(clip)

    cta_text = short.get("cta_frame") or short.get("cta", {}).get("primary") or "Follow for more"
    cta_clip = parts / "cta.mp4"
    render_cta(cta_text, font_path, work, cta_clip)
    clips.append(cta_clip)

    listing = parts / "concat.txt"
    listing.write_text("".join(f"file '{clip.name}'\n" for clip in clips), encoding="utf-8")
    body = parts / "body.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
         "-safe", "0", "-i", str(listing), "-c", "copy", str(body)])

    whoosh_at = None
    for position, scene in enumerate(scenes):
        if scene.transition:
            whoosh_at = starts[position]
            break

    OUTPUT.mkdir(parents=True, exist_ok=True)
    final = OUTPUT / f"{slug}-short-{index}-FINAL.mp4"
    mix_audio(body, vo, whoosh_at, music, final)
    say(f"final: {final.relative_to(REPO_ROOT)}, {media_duration(final):.1f}s")
    return final, starts


# --------------------------------------------------------------------------
# stage 6: contact sheet
# --------------------------------------------------------------------------

def stage_contact_sheet(final: Path, scenes: list[Scene], starts: list[float],
                        work: Path, slug: str, index: int, font_path: str | None) -> Path:
    stage("Stage 6, contact sheet")
    from PIL import Image, ImageDraw, ImageFont

    shots = work / "parts" / "sheet"
    shots.mkdir(parents=True, exist_ok=True)
    total = media_duration(final)

    grabs = []
    marks = [starts[i] + (scenes[i].duration / 2) for i in range(len(scenes))]
    marks.append(min(total - 0.3, (starts[-1] + scenes[-1].duration) + CTA_SECONDS / 2))
    labels = [f"{scene.number}. {scene.caption or scene.vo[:40]}" for scene in scenes] + ["CTA"]

    for position, mark in enumerate(marks):
        target = shots / f"cell{position:02d}.jpg"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{max(0.0, min(mark, total - 0.1)):.2f}", "-i", str(final),
             "-frames:v", "1", "-q:v", "3", str(target)])
        grabs.append(target)

    columns = min(5, len(grabs))
    rows = (len(grabs) + columns - 1) // columns
    cell_w, cell_h = 320, 569
    pad, caption_h, header = 16, 54, 92

    sheet = Image.new("RGB", (columns * (cell_w + pad) + pad,
                              header + rows * (cell_h + caption_h + pad) + pad),
                      (24, 26, 28))
    draw = ImageDraw.Draw(sheet)
    title_font = ImageFont.truetype(font_path, 34) if font_path else ImageFont.load_default(34)
    label_font = ImageFont.truetype(font_path, 20) if font_path else ImageFont.load_default(20)

    draw.rectangle([0, 0, sheet.width, 8], fill=BRAND_GREEN)
    draw.text((pad, 34), f"{slug} short {index}, {total:.1f}s, {len(scenes)} scenes",
              font=title_font, fill=(255, 255, 255))

    for position, grab in enumerate(grabs):
        row, column = divmod(position, columns)
        x = pad + column * (cell_w + pad)
        y = header + row * (cell_h + caption_h + pad)
        with Image.open(grab) as image:
            sheet.paste(image.resize((cell_w, cell_h)), (x, y))
        draw.rectangle([x, y, x + cell_w, y + cell_h], outline=BRAND_GREEN, width=3)
        text = labels[position]
        for line_no, line in enumerate(textwrap.wrap(text, 34)[:2]):
            draw.text((x, y + cell_h + 8 + line_no * 22), line, font=label_font,
                      fill=(214, 219, 223))

    destination = OUTPUT / f"{slug}-short-{index}-contact-sheet.jpg"
    sheet.save(destination, quality=88)
    say(f"contact sheet: {destination.relative_to(REPO_ROOT)}")
    return destination


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="YouTube URL of the source episode")
    parser.add_argument("number", type=int, nargs="?", default=1,
                        help="which Short from the guide, default 1")
    parser.add_argument("--guide", type=Path, default=None, help="explicit guide JSON path")
    parser.add_argument("--auto", action="store_true",
                        help="skip the visual analysis pause and take center crop defaults")
    parser.add_argument("--rescan", default="",
                        help="comma separated scene numbers to re-extract keyframes for")
    parser.add_argument("--skip-vo", action="store_true",
                        help="assemble with no narration, for a picture only check")
    parser.add_argument("--voice-id", default=None, help="ElevenLabs voice id for Mike")
    parser.add_argument("--model-id", default=ELEVEN_DEFAULT_MODEL)
    parser.add_argument("--music", type=Path, default=None, help="music bed override")
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--font", default=None, help="bold TTF for captions")
    parser.add_argument("--redownload", action="store_true")
    parser.add_argument("--revoice", action="store_true", help="resynthesize the VO")
    args = parser.parse_args()

    for binary in ("ffmpeg", "ffprobe", "yt-dlp"):
        if shutil.which(binary) is None:
            die(f"{binary} is not installed and this pipeline cannot run without it")

    sys.path.insert(0, str(SCRIPTS))
    from fetch_transcript import extract_video_id  # noqa: E402

    video_id = extract_video_id(args.url)
    work = WORK / video_id
    work.mkdir(parents=True, exist_ok=True)

    guide_path = stage_guide(args.url, video_id, args.guide, render_pdf=True)
    guide, short = load_short(guide_path, args.number)
    slug = slugify(guide.get("episode") or guide_path.stem)
    scenes = scenes_from_short(short)

    source = stage_download(args.url, work, args.redownload)

    rescan = {int(n) for n in args.rescan.split(",") if n.strip()} if args.rescan else None
    edits = stage_analyze(source, scenes, work, video_id, args.number, args.auto, rescan)
    apply_edits(scenes, edits)

    vo = stage_vo(short, work, args.number, args.skip_vo, args.revoice,
                  args.voice_id, args.model_id)

    font_path = args.font or find_font()
    if font_path is None:
        say("no bold TTF found, captions fall back to the built in font")

    music = None
    if not args.no_music:
        music = args.music or asset("music.mp3", "music.wav", "music.m4a")
        if music is None:
            say("no music bed in assets/, building without one")

    final, starts = stage_assemble(scenes, short, source, vo, work, args.number,
                                   slug, font_path, music)
    sheet = stage_contact_sheet(final, scenes, starts, work, slug, args.number, font_path)

    print("\nDone.")
    print(f"  Short:        {final.relative_to(REPO_ROOT)}")
    print(f"  Contact sheet:{sheet.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
