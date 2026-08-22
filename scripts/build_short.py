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
import base64
import json
import os
import re
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
TRANSCRIPTS = REPO_ROOT / "transcripts"

BRAND_GREEN = (14, 147, 70)
EMPHASIS_GREEN = (46, 214, 116)   # brand green lifted so it reads over dark footage
W, H = 1080, 1920
FPS = 30
CTA_SECONDS = 3.0
# End card geometry, measured off the reference Short: a stack of rotated
# stickers alternating white and green, then the handle pill under it.
CTA_FONT_SIZE = 112
CTA_PAD_X = 30
CTA_PAD_Y = 16
CTA_TILTS = (-1.6, 1.4, -1.2, 1.8, -1.0)
CTA_HANDLE = "@theremodelking"
# One beat per sticker. Newlines in the guide's cta_frame are honoured as written.
CTA_DEFAULT = "Follow\nfor more\nbefore\nand afters"
DEFAULT_LOGO_WIDTH = 0.16
MIN_SCENE_SECONDS = 1.2

# Captions run in Montserrat ExtraBold and the end card in Anton, the two faces
# the channel's own Shorts use. Both ship in assets/fonts, so a fresh container
# renders identically to a local one. The system faces are only a fallback.
FONT_CANDIDATES = [
    str(REPO_ROOT / "assets" / "fonts" / "Montserrat-ExtraBold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
DISPLAY_FONT_CANDIDATES = [
    str(REPO_ROOT / "assets" / "fonts" / "Anton-Regular.ttf"),
    *FONT_CANDIDATES,
]

ELEVEN_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
SUB_MAX_WORDS = 6            # words per subtitle card
SUB_MAX_CHARS = 34           # characters per subtitle card

# The caption look, measured off the reference Short the channel already
# publishes: a solid green plate sitting on a fixed baseline, white Montserrat
# ExtraBold on top, no outline. Keep these numbers, they are the house style.
CAPTION_GREEN = (22, 163, 74)
CAPTION_BASELINE = 0.746     # bottom edge of the plate, as a fraction of height
CAPTION_SIZE = 48
CAPTION_LINE = 57            # line pitch inside the plate
CAPTION_PAD_X = 12
CAPTION_WRAP = 0.72          # widest a text line may run, fraction of width
SUB_TAIL = 0.30              # how long a card may linger before the next one
HANGING_WORDS = {
    "the", "a", "an", "and", "or", "but", "so", "to", "of", "in", "on", "at", "for",
    "with", "is", "was", "were", "we", "it", "that", "this", "your", "our", "my",
    "you", "i", "he", "she", "they", "had", "has", "have", "could", "would", "can",
    "just", "some", "out", "up", "into", "how",
}
ELEVEN_DEFAULT_MODEL = "eleven_multilingual_v2"
# Mike found the read flat. Lower stability lets the delivery move, higher style
# exaggerates the emphasis the script marks in caps.
VOICE_STABILITY = 0.28
VOICE_STYLE = 0.70
VOICE_SIMILARITY = 0.80


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


def find_font(candidates: list[str] | None = None) -> str | None:
    for candidate in (candidates or FONT_CANDIDATES):
        if Path(candidate).exists():
            return candidate
    return None


def load_dotenv() -> None:
    """Read a gitignored .env at the repo root, for credentials kept out of git."""
    path = REPO_ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        entry = raw.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def find_logo(explicit: Path | None) -> Path | None:
    """assets/logo.png, or any file in assets/ with 'logo' in the name."""
    if explicit:
        return explicit if explicit.exists() else None
    for name in ("logo.png", "logo.webp", "logo.jpg"):
        if (ASSETS / name).exists():
            return ASSETS / name
    matches = sorted(path for path in ASSETS.glob("*")
                     if "logo" in path.stem.lower()
                     and path.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"})
    return matches[0] if matches else None


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
    pan: dict | None = None
    annotations: list = field(default_factory=list)
    crop_x: float = 0.5
    crop_y: float = 0.5
    zoom: float = 1.0
    continues_previous: bool = False
    source_label: str = ""
    face: dict | None = None

    @property
    def duration(self) -> float:
        return max(0.4, self.end - self.start)


def wants_punch_in(notes: str) -> bool:
    """Punch in is opt in only. Mike does not want extra zoom on top of the
    vertical crop, so the default motion is a pan across the frame instead."""
    return False


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
        if (video_id in json.dumps(data.get("video_url", ""))
                or video_id == data.get("video_id")
                or video_id == data.get("work_id")):
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

def stage_guide(url: str, video_id: str, guide_arg: Path | None, render_pdf: bool,
                cookies: Path | None) -> Path:
    stage("Stage 1, transcript and production guide")
    transcript = REPO_ROOT / "transcripts" / f"{video_id}.json"
    guide_path = find_guide(video_id, guide_arg)

    if not transcript.exists():
        if guide_path is not None:
            # The guide already carries the timestamps, so the transcript is
            # only needed to write one. Do not block the build on it.
            say("no transcript cached, continuing from the existing guide")
        else:
            say("fetching transcript...")
            cmd = [sys.executable, str(SCRIPTS / "fetch_transcript.py"), url]
            if cookies:
                cmd += ["--cookies", str(cookies)]
            run(cmd)
            guide_path = find_guide(video_id, guide_arg)
    else:
        say(f"transcript: {transcript.relative_to(REPO_ROOT)}")
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

def stage_download(url: str, work: Path, force: bool, local: Path | None,
                   cookies: Path | None) -> Path:
    stage("Stage 2, source video")

    if local is not None:
        if not local.exists():
            die(f"source file not found: {local}")
        say(f"using local source: {local}")
        return local

    source = work / "source.mp4"
    if source.exists() and not force:
        say(f"cached: {source.relative_to(REPO_ROOT)}")
        return source

    say("downloading highest quality source with yt-dlp, this can take a while...")
    cmd = ["yt-dlp",
           "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
           "--merge-output-format", "mp4", "-o", str(source)]
    if cookies:
        cmd += ["--cookies", str(cookies)]
        say(f"using cookies from {cookies.name}")
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not source.exists():
        detail = (result.stderr or "").strip().splitlines()[-3:]
        blocked = any("not a bot" in line or "Sign in" in line for line in detail)
        message = "yt-dlp could not download the source.\n  " + "\n  ".join(detail)
        if blocked:
            message += (
                "\n\n  YouTube is refusing downloads from this IP, which is normal for a "
                "cloud container.\n"
                "  Two ways around it:\n"
                "    1. Pass the master file you already have: --source /path/to/episode.mp4\n"
                "    2. Export your YouTube cookies to cookies.txt at the repo root, it is\n"
                "       gitignored, and rerun. The build picks it up automatically."
            )
        die(message)
    say(f"source: {source.relative_to(REPO_ROOT)}, {stamp(media_duration(source))}")
    return source


def find_cookies(explicit: Path | None) -> Path | None:
    if explicit:
        return explicit if explicit.exists() else None
    for name in ("cookies.txt", "youtube-cookies.txt"):
        if (REPO_ROOT / name).exists():
            return REPO_ROOT / name
    return None


# --------------------------------------------------------------------------
# stage 3: keyframes and edit decisions
# --------------------------------------------------------------------------

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "so", "then", "we", "i", "you", "they",
    "it", "its", "this", "that", "these", "those", "is", "are", "was", "were",
    "be", "been", "to", "of", "in", "on", "at", "for", "with", "from", "into",
    "just", "all", "up", "out", "our", "your", "their", "there", "here", "have",
    "has", "had", "got", "get", "put", "went", "go", "going", "do", "did", "not",
    "no", "very", "really", "some", "one", "two", "now", "right", "like", "what",
    "how", "when", "where", "which", "who", "can", "will", "would", "could",
    "about", "over", "under", "through", "across", "down", "off", "more", "most",
}


def content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def load_transcript(video_id: str) -> list[dict]:
    path = TRANSCRIPTS / f"{video_id}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("lines", [])
    except (ValueError, OSError):
        return []


def rank_transcript_windows(vo: str, lines: list[dict], taken: list[tuple[float, float]],
                            avoid: list[tuple[float, float]], want: int = 3) -> list[float]:
    """Where in the episode does Mike talk about this? Best moments first.

    Mike narrates while he points, so the frames around the words are the frames
    that show the thing. Overlap on content words is a blunt instrument, but it
    beats guessing, and the picked windows still go past a pair of eyes.
    """
    wanted = content_words(vo)
    if not wanted or not lines:
        return []
    scored = []
    for line in lines:
        overlap = wanted & content_words(line.get("text", ""))
        if not overlap:
            continue
        start = float(line.get("start", 0.0))
        if any(start < end and (start + 4.0) > begin for begin, end in avoid):
            continue
        if any(start < end and (start + 4.0) > begin for begin, end in taken):
            continue
        scored.append((len(overlap) / len(wanted), start, sorted(overlap)))
    scored.sort(key=lambda row: (-row[0], row[1]))

    picked: list[float] = []
    for score, start, _ in scored:
        if any(abs(start - other) < 6.0 for other in picked):
            continue
        picked.append(start)
        if len(picked) >= want:
            break
    return picked


def contact_strip(source: Path, marks: list[float], destination: Path,
                  columns: int = 4, tile_width: int = 360) -> Path | None:
    """One image holding every candidate frame, each stamped with its timestamp.

    Reading one strip beats opening twelve files, and the timestamp under each
    tile is what gets written back into the edit decisions.
    """
    from PIL import Image, ImageDraw, ImageFont

    if not marks:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    scratch = destination.parent / f".{destination.stem}_tiles"
    scratch.mkdir(exist_ok=True)
    grabs = []
    for order, mark in enumerate(marks):
        tile = scratch / f"{order:02d}.jpg"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{mark:.2f}", "-i", str(source), "-frames:v", "1", "-q:v", "3",
             str(tile)])
        if tile.exists():
            grabs.append((mark, tile))
    if not grabs:
        shutil.rmtree(scratch, ignore_errors=True)
        return None

    with Image.open(grabs[0][1]) as probe_img:
        ratio = probe_img.height / probe_img.width
    tile_h = int(tile_width * ratio)
    label_h = 30
    rows = (len(grabs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_h + label_h)), (16, 16, 16))
    pen = ImageDraw.Draw(sheet)
    font_path = find_font()
    font = ImageFont.truetype(font_path, 20) if font_path else ImageFont.load_default(20)

    for order, (mark, tile) in enumerate(grabs):
        with Image.open(tile) as img:
            frame = img.convert("RGB").resize((tile_width, tile_h))
        x = (order % columns) * tile_width
        y = (order // columns) * (tile_h + label_h)
        sheet.paste(frame, (x, y))
        # the 9:16 window at centre crop, so the tile shows what actually survives
        window = int(tile_h * 9 / 16)
        left = x + tile_width // 2 - window // 2
        pen.rectangle([left, y, left + window, y + tile_h], outline=CAPTION_GREEN, width=2)
        pen.text((x + 8, y + tile_h + 6), f"{stamp(mark)}  ({mark:.1f}s)",
                 font=font, fill=(235, 235, 235))
    sheet.save(destination, quality=86)
    shutil.rmtree(scratch, ignore_errors=True)
    return destination


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


def scene_candidates(scenes: list[Scene], video_id: str, guide: dict,
                     source_seconds: float) -> dict[int, list[float]]:
    """For every line, the moments in the episode where Mike is on that subject.

    The line's own source range always leads, because the guide writer chose it,
    then transcript matches follow. Nothing that overlaps an avoid_range or a
    window already claimed by another line is offered.
    """
    lines = load_transcript(video_id)
    avoid = [parse_range(entry.get("range", "0 - 0"))
             for entry in (guide.get("avoid_ranges") or [])]
    taken: list[tuple[float, float]] = []
    proposals: dict[int, list[float]] = {}

    for scene in scenes:
        marks = [scene.start] if scene.start else []
        for start in rank_transcript_windows(scene.vo, lines, taken, avoid, want=3):
            if all(abs(start - other) > 5.0 for other in marks):
                marks.append(start)
        spread = []
        for mark in marks[:4]:
            for step in (0.0, 1.6, 3.2):
                moment = mark + step
                if moment + 0.2 < source_seconds:
                    spread.append(round(moment, 2))
        proposals[scene.number] = spread[:12]
        taken.extend((mark - 2.0, mark + 5.0) for mark in marks[:4])
        if not lines:
            say(f"scene {scene.number}: no transcript to anchor against, "
                "candidates are the guide's range only")
    return proposals


def edit_skeleton(scenes: list[Scene], video_id: str, index: int, frames_dir: Path,
                  candidates: dict[int, list[float]] | None = None) -> dict:
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
            "pan is the house style: {\"from\": x, \"to\": x} slides that window across "
            "the shot, starting wide on the subject and settling on whatever Mike is "
            "talking about. Keep the move gentle, 0.08 to 0.18 of frame width, and set "
            "both ends so the feature is never out of frame at either end. Leave pan null "
            "only for a shot under about 2 seconds.",
            "zoom frames the shot. 1.0 is the widest that still fills the frame, "
            "Premiere's 178 percent. 1.12 matches Premiere's 200 percent. Go to 1.3 or "
            "1.6 when the line is about a FEATURE, so the feature fills the frame "
            "instead of sitting in a wide shot of the room with Mike in it. Only the "
            "hook and the closing wide should sit near 1.0.",
            "crop_y is the vertical centre, only meaningful above zoom 1.0. Drop it to "
            "0.65 for something low in frame like a vanity or a toilet, raise it for a "
            "niche or a shower head.",
            "punch_in is OFF and stays OFF. Framing is chosen, not animated.",
            "Never use the same footage twice, in this Short or the others from this "
            "episode. If two consecutive lines want the same shot, do not cut between "
            "them, run it as ONE continuous take: start the second scene exactly where "
            "the first ends and continue the pan from where it stopped. A cut between "
            "two nearly identical frames reads as a glitch.",
            "punch_in is null when the editor notes do not ask for one, otherwise "
            '{"zoom": 1.15 to 1.6, "focus": [x, y]} aimed at the feature.',
            'box annotations are {"type":"box","target":"...","x":..,"y":..,"w":..,"h":..} '
            "with x and y the top left corner.",
            'arrow annotations are {"type":"arrow","target":"...","from":[x,y],"to":[x,y]} '
            "with the arrowhead landing on the feature.",
            "face is Mike's head INCLUDING the cap and jaw, normalized to the source "
            "frame. Captions are never allowed to touch it, the build moves them clear.",
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
                "candidate_strip": str((frames_dir / f"scene{scene.number:02d}_candidates.jpg")
                                       .relative_to(REPO_ROOT)),
                "candidate_times": (candidates or {}).get(scene.number, []),
                "continues_previous": scene.continues_previous,
                "crop_x": 0.5,
                "crop_y": 0.5,
                "zoom": 1.0,
                "pan": {"from": None, "to": None},
                "punch_in": None,
                "annotations": wanted_annotations(scene.notes),
                "face": {"x": None, "y": None, "w": None, "h": None},
                "frames_show_what_the_vo_says": None,
                "analysis_note": "",
            }
            for scene in scenes
        ],
    }


def stage_analyze(source: Path, scenes: list[Scene], work: Path, video_id: str,
                  index: int, auto: bool, rescan: set[int] | None,
                  guide: dict | None = None) -> dict:
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
        source_seconds = media_duration(source)
        candidates = scene_candidates(scenes, video_id, guide or {}, source_seconds)
        for scene in scenes:
            say(f"scene {scene.number}: keyframes from {stamp(scene.start)} to {stamp(scene.end)}")
            extract_keyframes(source, scene, frames_dir)
            marks = candidates.get(scene.number) or []
            if marks:
                contact_strip(source, marks,
                              frames_dir / f"scene{scene.number:02d}_candidates.jpg")
                say(f"  {len(marks)} candidate moments: "
                    + ", ".join(stamp(m) for m in marks[:6])
                    + ("..." if len(marks) > 6 else ""))
        skeleton = edit_skeleton(scenes, video_id, index, frames_dir, candidates)
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
            "  Read each scene's candidate_strip first. It holds every moment in the\n"
            "  episode where Mike is on that subject, one tile per moment, timestamped,\n"
            "  with the 9:16 window drawn on. Pick the tile that shows the FEATURE and\n"
            "  write its timestamp into source, then set crop_x, pan, and face.\n"
            '  Set "analyzed": true and run this same command again.',
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
        scene.crop_y = float(entry.get("crop_y", 0.5) or 0.5)
        scene.zoom = max(1.0, float(entry.get("zoom", 1.0) or 1.0))
        pan = entry.get("pan")
        if pan and pan.get("from") is not None and pan.get("to") is not None:
            scene.pan = {"from": float(pan["from"]), "to": float(pan["to"])}
            scene.crop_x = float(pan["from"])
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
        # only the guide decides this unless the analysis explicitly overrides it,
        # otherwise a skeleton written before the flag existed silently drops it
        if "continues_previous" in entry:
            scene.continues_previous = bool(entry["continues_previous"])
        face = entry.get("face")
        if face and all(face.get(k) is not None for k in ("x", "y", "w", "h")):
            scene.face = {k: float(face[k]) for k in ("x", "y", "w", "h")}
        elif entry.get("face", "missing") is None:
            scene.face = None


def annotation_is_placed(annotation: dict) -> bool:
    if annotation.get("type") == "box":
        return all(annotation.get(key) is not None for key in ("x", "y", "w", "h"))
    if annotation.get("type") == "arrow":
        return annotation.get("from") is not None and annotation.get("to") is not None
    return False


# --------------------------------------------------------------------------
# stage 4: voice over
# --------------------------------------------------------------------------

# Words the model reads wrong no matter how the sentence is built. The left side
# is what the script says, the right side is what gets sent to ElevenLabs. The
# captions still show the real spelling, the swap is reversed on the way back.
PRONUNCIATION = {
    "niche": "nitch",
    "niches": "nitches",
    "quartzite": "kwartz-ite",
    "soffit": "sof-it",
    "shiplap": "ship-lap",
}


def _match_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement.capitalize()
    return replacement


def respell_for_voice(text: str) -> str:
    """Spell the awkward words the way the voice model needs to hear them."""
    def swap(match):
        word = match.group(0)
        return _match_case(word, PRONUNCIATION[word.lower()])
    if not PRONUNCIATION:
        return text
    pattern = r"\b(" + "|".join(sorted(PRONUNCIATION, key=len, reverse=True)) + r")\b"
    return re.sub(pattern, swap, text, flags=re.IGNORECASE)


def respell_for_screen(text: str) -> str:
    """Undo respell_for_voice, so a caption never shows the phonetic spelling."""
    back = {v.lower(): k for k, v in PRONUNCIATION.items()}
    if not back:
        return text
    pattern = r"\b(" + "|".join(sorted(back, key=len, reverse=True)) + r")\b"
    return re.sub(pattern, lambda m: _match_case(m.group(0), back[m.group(0).lower()]),
                  text, flags=re.IGNORECASE)


def word_is_emphasis(word: str) -> bool:
    letters = "".join(c for c in word if c.isalpha())
    return len(letters) >= 2 and letters.isupper()


def phrases_from_alignment(chars: list[str], starts: list[float], ends: list[float],
                           window_start: float | None = None,
                           window_end: float | None = None) -> list[dict]:
    """Character timings into short subtitle cards that follow the read.

    window_start and window_end cut one line out of a continuous take, so a
    single render still produces per line cards.
    """
    words, current = [], None
    for char, start, end in zip(chars, starts, ends):
        if window_start is not None and end < window_start - 1e-6:
            continue
        if window_end is not None and start > window_end + 1e-6:
            break
        if char.isspace():
            if current:
                words.append(current)
                current = None
            continue
        if current is None:
            current = {"text": "", "start": start, "end": end}
        current["text"] += char
        current["end"] = end
    if current:
        words.append(current)
    return phrases_from_words(words)


def phrases_from_words(words: list[dict]) -> list[dict]:
    """Timed words into short subtitle cards. words carry text, start and end."""
    soft_words, soft_chars = SUB_MAX_WORDS, SUB_MAX_CHARS
    hard_words, hard_chars = SUB_MAX_WORDS + 2, SUB_MAX_CHARS + 10

    def hanging(word):
        return word["text"].strip(".,!?:;").lower() in HANGING_WORDS

    groups, group = [], []
    for word in words:
        group.append(word)
        joined = " ".join(w["text"] for w in group)
        clause = word["text"].rstrip()[-1:] in ".,!?:;"
        at_soft = len(group) >= soft_words or len(joined) >= soft_chars or clause
        at_hard = len(group) >= hard_words or len(joined) >= hard_chars
        # never end a card on a hanging word while there is room for one more
        if at_hard or (at_soft and not hanging(word)):
            groups.append(group)
            group = []
    if group:
        groups.append(group)

    # a lone word is not a subtitle, fold it into a neighbour that has room
    index = 0
    while index < len(groups):
        if len(groups[index]) == 1 and len(groups) > 1:
            back = groups[index - 1] if index > 0 else None
            forward = groups[index + 1] if index + 1 < len(groups) else None
            def fits(other):
                if other is None:
                    return False
                merged = " ".join(w["text"] for w in other + groups[index])
                return len(other) + 1 <= hard_words and len(merged) <= hard_chars
            if fits(back):
                groups[index - 1] = back + groups.pop(index)
                continue
            if fits(forward):
                lone = groups.pop(index)
                groups[index] = lone + groups[index]
                continue
        index += 1

    phrases = [{
        "words": [{"text": respell_for_screen(w["text"]),
                   "emph": word_is_emphasis(w["text"])} for w in g],
        "start": round(g[0]["start"], 3),
        "end": round(g[-1]["end"], 3),
    } for g in groups if g]

    # hold each card until the next one starts, so the screen is never empty
    for index, phrase in enumerate(phrases):
        limit = phrases[index + 1]["start"] if index + 1 < len(phrases) else phrase["end"] + SUB_TAIL
        phrase["end"] = round(min(limit, phrase["end"] + SUB_TAIL), 3)
    return phrases


def eleven_tts(text: str, previous_text: str, next_text: str, api_key: str,
               voice_id: str, model_id: str, destination: Path,
               settings: dict | None = None) -> list[dict]:
    """One ElevenLabs render. previous_text and next_text keep prosody continuous
    across separately rendered lines, so a per line read still sounds like one take."""
    settings = settings or {"stability": VOICE_STABILITY, "style": VOICE_STYLE,
                            "similarity": VOICE_SIMILARITY}
    body = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {"stability": settings["stability"],
                           "similarity_boost": settings["similarity"],
                           "style": settings["style"],
                           "use_speaker_boost": True},
    }
    if previous_text:
        body["previous_text"] = previous_text
    if next_text:
        body["next_text"] = next_text

    request = urllib.request.Request(
        ELEVEN_ENDPOINT.format(voice_id=voice_id) + "?output_format=mp3_44100_128",
        data=json.dumps(body).encode("utf-8"),
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    ca_bundle = (os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
                 or os.environ.get("CURL_CA_BUNDLE"))
    context = (ssl.create_default_context(cafile=ca_bundle) if ca_bundle
               else ssl.create_default_context())
    try:
        with urllib.request.urlopen(request, context=context, timeout=180) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        die(f"ElevenLabs returned {exc.code}: {exc.read()[:400].decode('utf-8', 'replace')}")
    except Exception as exc:  # noqa: BLE001
        die(f"ElevenLabs request failed: {type(exc).__name__}: {exc}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(base64.b64decode(payload["audio_base64"]))

    alignment = payload.get("alignment") or payload.get("normalized_alignment") or {}
    # keep the raw timing so cards can be regrouped later without paying for
    # another render
    destination.with_suffix(".alignment.json").write_text(json.dumps(alignment),
                                                          encoding="utf-8")
    phrases = phrases_from_alignment(alignment.get("characters", []),
                                     alignment.get("character_start_times_seconds", []),
                                     alignment.get("character_end_times_seconds", []))
    destination.with_suffix(".phrases.json").write_text(json.dumps(phrases, indent=2),
                                                        encoding="utf-8")
    return phrases


def normalise_word(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def split_alignment_by_line(chars: list[str], starts: list[float], ends: list[float],
                            texts: list[str], joiner: str = " ") -> list[tuple[float, float]]:
    """Where each script line begins and ends inside one continuous render.

    ElevenLabs returns a character per character of exactly the text it was
    sent, so walking the cursor through the joined script lands on the right
    boundaries without any matching.
    """
    spans, cursor = [], 0
    for position, text in enumerate(texts):
        length = len(text)
        first, last = cursor, cursor + length - 1
        if length == 0 or first >= len(starts):
            spans.append((starts[-1] if starts else 0.0, ends[-1] if ends else 0.0))
        else:
            last = min(last, len(ends) - 1)
            spans.append((starts[first], ends[last]))
        cursor += length + (len(joiner) if position + 1 < len(texts) else 0)
    return spans


def align_supplied_vo(audio: Path, texts: list[str], model_size: str = "small") -> list[dict]:
    """Word timings for a VO file somebody else recorded.

    The supplied read is never cut or retimed, the picture is cut to it. All this
    does is find where each script line lands so the scenes can be laid against it.
    """
    sys.path.insert(0, str(SCRIPTS))
    from fetch_transcript import ensure_faster_whisper  # noqa: E402
    if not ensure_faster_whisper(True):
        die("faster-whisper is needed to line a supplied VO up with the script.\n"
            "  Install it with: pip install -r requirements-whisper.txt")
    from faster_whisper import WhisperModel

    say(f"transcribing the supplied VO with faster-whisper ({model_size}) to find "
        "where each line lands")
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(audio), word_timestamps=True, vad_filter=False)
    heard = []
    for seg in segments:
        for word in (seg.words or []):
            token = normalise_word(word.word)
            if token:
                heard.append({"token": token, "start": word.start, "end": word.end})
    if not heard:
        die("nothing audible in the supplied VO file")

    spans, cursor = [], 0
    for text in texts:
        script_words = [w for w in text.split() if normalise_word(w)]
        if not script_words:
            spans.append(None)
            continue
        wanted = [normalise_word(w) for w in script_words]
        # find the line's first word, then take its words in order, tolerating a
        # word the model misheard rather than losing the rest of the line
        start_at = next((probe for probe in range(cursor, min(len(heard), cursor + 80))
                         if heard[probe]["token"] == wanted[0]), cursor)
        at, timed = start_at, []
        for script_word, token in zip(script_words, wanted):
            hit = next((probe for probe in range(at, min(len(heard), at + 4))
                        if heard[probe]["token"] == token), None)
            if hit is None:
                timed.append({"text": script_word, "start": None, "end": None})
                continue
            timed.append({"text": script_word, "start": heard[hit]["start"],
                          "end": heard[hit]["end"]})
            at = hit + 1
        matched = sum(1 for w in timed if w["start"] is not None)
        if not matched:
            spans.append(None)
            continue
        spans.append({"start": next(w["start"] for w in timed if w["start"] is not None),
                      "end": next(w["end"] for w in reversed(timed) if w["end"] is not None),
                      "words": timed, "matched": matched, "of": len(timed)})
        cursor = at

    total = media_duration(audio)
    for position, span in enumerate(spans):
        if span and span["matched"] < max(2, span["of"] // 2):
            say(f"line {position + 1}: only {span['matched']} of {span['of']} words "
                "matched the supplied read, check the script against the recording")

    # every line runs to where the next one starts, so no audio is ever skipped
    for position, span in enumerate(spans):
        if span is None:
            continue
        nxt = next((other for other in spans[position + 1:] if other), None)
        span["end_hold"] = nxt["start"] if nxt else total
        # a word the model missed gets slid between its timed neighbours
        words = span["words"]
        for order, word in enumerate(words):
            if word["start"] is not None:
                continue
            before = next((w for w in reversed(words[:order]) if w["end"] is not None), None)
            after = next((w for w in words[order + 1:] if w["start"] is not None), None)
            left = before["end"] if before else span["start"]
            right = after["start"] if after else span["end"]
            word["start"], word["end"] = left, max(left + 0.08, right)
    return spans


def stage_vo(short: dict, scenes: list[Scene], work: Path, index: int, skip: bool,
             force: bool, voice_id: str | None, model_id: str, gap: float,
             settings: dict | None = None,
             supplied: Path | None = None) -> tuple[list[dict] | None, Path | None]:
    """One continuous narration take, plus where each script line falls inside it.

    The read is never chopped into per line files any more. Rendering line by line
    and butting the pieces together put an audible seam at every cut, because each
    render carries its own lead in, room tone and level. One take has no seams, and
    the character timings say exactly where each line ends, which is all the picture
    needs in order to cut with the words.

    Returns (lines, master). Each line carries hold, the seconds of the take that
    belong to it, and phrases, its subtitle cards with times relative to the line.
    """
    lines_dir = work / f"short{index}" / "vo_lines"
    lines_dir.mkdir(parents=True, exist_ok=True)
    # per line renders are how this used to work and they left seams at every
    # join, clear any left behind so nothing stale can be picked up
    for stale in lines_dir.glob("line*"):
        stale.unlink()
    # The voice hears the respelled text, the screen always shows the real one.
    texts = [respell_for_voice(" ".join((scene.vo or "").split())) for scene in scenes]
    if not any(texts):
        die("no per scene VO lines in the guide, nothing to synthesize")

    if skip:
        stage("Stage 4, voice over")
        say("--skip-vo, building picture with no narration track")
        return None, None

    if supplied:
        stage("Stage 4, supplied voice over")
        if not supplied.exists():
            die(f"no VO file at {supplied}")
        master = lines_dir / "master.wav"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(supplied),
             "-vn", "-ac", "2", "-ar", "48000", str(master)])
        say(f"supplied VO: {supplied.name}, {media_duration(master):.1f}s, used as recorded")
        spans = align_supplied_vo(master, texts)
        rendered = []
        for position, scene in enumerate(scenes):
            span = spans[position]
            if span is None:
                rendered.append({"scene": scene.number, "path": None, "speech": 0.0,
                                 "hold": max(MIN_SCENE_SECONDS, scene.duration),
                                 "phrases": [], "at": 0.0})
                continue
            hold = max(MIN_SCENE_SECONDS, span["end_hold"] - span["start"])
            cards = phrases_from_words([dict(w) for w in span["words"]])
            for card in cards:
                card["start"] -= span["start"]
                card["end"] -= span["start"]
            rendered.append({"scene": scene.number, "path": None,
                             "speech": span["end"] - span["start"], "hold": hold,
                             "at": span["start"], "phrases": cards})
            say(f"line {scene.number}: {span['start']:5.2f}s to {span['end']:5.2f}s "
                f"in the supplied read, holds {hold:.2f}s, {len(cards)} cards")
        say(f"narration total {sum(i['hold'] for i in rendered):.1f}s, one continuous take")
        return rendered, master

    stage("Stage 4, ElevenLabs voice over, one continuous take")
    settings = settings or {"stability": VOICE_STABILITY, "style": VOICE_STYLE,
                            "similarity": VOICE_SIMILARITY}
    say(f"voice settings: stability {settings['stability']}, style {settings['style']}, "
        f"similarity {settings['similarity']}")

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        die("ELEVENLABS_API_KEY is not set. Export it in your shell, never commit it.\n"
            "  Or rerun with --skip-vo to build the picture without narration.")
    voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID")
    if not voice_id:
        die("no voice id. Pass --voice-id or export ELEVENLABS_VOICE_ID with Mike's voice.")

    master = lines_dir / "master.mp3"
    script = " ".join(texts)
    alignment_file = master.with_suffix(".alignment.json")
    if master.exists() and alignment_file.exists() and not force:
        alignment = json.loads(alignment_file.read_text(encoding="utf-8"))
        say(f"cached take, {media_duration(master):.2f}s")
    else:
        eleven_tts(script, "", "", api_key, voice_id, model_id, master, settings)
        alignment = json.loads(alignment_file.read_text(encoding="utf-8"))
        say(f"one take, {len(script.split())} words, {media_duration(master):.2f}s")

    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])
    spans = split_alignment_by_line(chars, starts, ends, texts)
    total = media_duration(master)

    rendered = []
    for position, scene in enumerate(scenes):
        begin, finish = spans[position]
        # the line owns the take right up to where the next one starts, so the
        # breath after it stays with the picture it belongs to
        finish = spans[position + 1][0] if position + 1 < len(spans) else total
        hold = max(MIN_SCENE_SECONDS, finish - begin)
        cards = phrases_from_alignment(chars, starts, ends, begin, spans[position][1])
        for card in cards:
            card["start"] -= begin
            card["end"] -= begin
            for word in card["words"]:
                word["text"] = respell_for_screen(word["text"])
        rendered.append({"scene": scene.number, "path": None, "speech": hold,
                         "hold": hold, "at": begin, "phrases": cards})
        say(f"line {scene.number}: {begin:5.2f}s to {finish:5.2f}s, "
            f"{len(cards)} subtitle cards")
    say(f"narration total {total:.1f}s, one continuous take, no joins")
    return rendered, master


def fit_scenes_to_lines(scenes: list[Scene], vo_lines: list[dict],
                        source_seconds: float) -> None:
    """Cut every scene to the exact length of its own narration line.

    A scene that continues the previous one starts where that one ends, whatever
    the guide says, so the shared take stays exactly as long as the lines it
    carries. Without this, a change in line length silently overlaps them.
    """
    for position, (scene, item) in enumerate(zip(scenes, vo_lines)):
        if scene.continues_previous and position:
            previous = scenes[position - 1]
            if abs(scene.start - previous.end) > 0.01:
                say(f"scene {scene.number}: chained to scene {previous.number}, "
                    f"starting at {stamp(previous.end)} so the shared take stays continuous")
                scene.start = previous.end
        wanted = item["hold"]
        available = source_seconds - scene.start
        if wanted > available:
            say(f"scene {scene.number}: only {available:.1f}s of source left, "
                f"line needs {wanted:.1f}s")
            wanted = available
        if wanted > scene.duration + 0.05:
            say(f"scene {scene.number}: extending picture to {wanted:.1f}s to cover its line")
        elif wanted < scene.duration - 0.05:
            say(f"scene {scene.number}: trimming picture to {wanted:.1f}s to match its line")
        scene.end = scene.start + wanted


# --------------------------------------------------------------------------
# overlays drawn with Pillow
# --------------------------------------------------------------------------

def crop_window(src_w: int, src_h: int, crop_x: float, zoom: float = 1.0,
                crop_y: float = 0.5) -> tuple[int, int, int, int]:
    """The 9:16 window. zoom 1.0 is the widest the frame can be and still fill
    vertically, which is Premiere's 178 percent on a 16:9 clip. zoom 1.12 is
    Premiere's 200 percent, and anything above that is a detail framing."""
    target = 9 / 16
    zoom = max(1.0, float(zoom))
    widest = min(src_w, src_h * target)
    crop_w = widest / zoom
    crop_h = crop_w / target
    if crop_h > src_h:
        crop_h = src_h
        crop_w = crop_h * target
    crop_w = int(crop_w) - int(crop_w) % 2
    crop_h = int(crop_h) - int(crop_h) % 2
    x0 = max(0, min(src_w - crop_w, int(round(crop_x * src_w - crop_w / 2))))
    y0 = max(0, min(src_h - crop_h, int(round(crop_y * src_h - crop_h / 2))))
    return crop_w, crop_h, x0, y0


def to_frame(sx: float, sy: float, src_w: int, src_h: int, window) -> tuple[float, float]:
    """Source normalized coordinates into final 1080x1920 pixel coordinates."""
    crop_w, crop_h, x0, y0 = window
    fx = (sx * src_w - x0) / crop_w
    fy = (sy * src_h - y0) / crop_h
    return max(0.0, min(1.0, fx)) * W, max(0.0, min(1.0, fy)) * H


def face_rect_in_frame(scene: Scene, src_w: int, src_h: int, window):
    """Mike's head in final frame pixels, covering the whole punch in if there is one."""
    if not scene.face:
        return None
    f = scene.face
    x0, y0 = to_frame(f["x"], f["y"], src_w, src_h, window)
    x1, y1 = to_frame(f["x"] + f["w"], f["y"] + f["h"], src_w, src_h, window)
    rect = [x0, y0, x1, y1]

    if scene.punch_in:
        zoom = max(1.01, min(2.0, float(scene.punch_in["zoom"])))
        fx, fy = scene.punch_in["focus"]
        px, py = to_frame(fx, fy, src_w, src_h, window)
        ox, oy = (px / W) * W * (1 - 1 / zoom), (py / H) * H * (1 - 1 / zoom)
        zoomed = [(x0 - ox) * zoom, (y0 - oy) * zoom, (x1 - ox) * zoom, (y1 - oy) * zoom]
        rect = [min(rect[0], zoomed[0]), min(rect[1], zoomed[1]),
                max(rect[2], zoomed[2]), max(rect[3], zoomed[3])]

    # the box comes from one frame, but Mike moves inside the shot, so give the
    # head room to drift before a caption is allowed anywhere near it
    if (rect[2] - rect[0]) < 0.04 * W:
        # clamped to nothing, Mike is outside this crop
        return None

    drift_x, drift_y = 0.03 * W, 0.045 * H
    return [max(0.0, rect[0] - drift_x), max(0.0, rect[1] - drift_y),
            min(W, rect[2] + drift_x), min(H, rect[3] + drift_y)]


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


TOP_SAFE = 0.06 * H          # clear of the YouTube chrome
BOTTOM_SAFE = 0.86 * H       # clear of the title and action rail
FACE_PAD = 34                # never closer than this to Mike's head


def place_caption(block: float, zone: str, face) -> float:
    """Top y for the caption block. Mike's face is off limits, always."""
    preferred = (H * 0.20 if zone == "hook" else H * 0.78) - block / 2
    lowest = BOTTOM_SAFE - block

    def clamp(value):
        return max(TOP_SAFE, min(lowest, value))

    if not face:
        return clamp(preferred)

    top, bottom = face[1] - FACE_PAD, face[3] + FACE_PAD

    def clear(candidate):
        return candidate + block <= top or candidate >= bottom

    if TOP_SAFE <= preferred <= lowest and clear(preferred):
        return preferred

    above, below = top - block, bottom
    options = []
    if above >= TOP_SAFE:
        options.append(above)
    if below <= lowest:
        options.append(below)
    if options:
        # hook text wants to be high, supporting text wants to be low
        return min(options) if zone == "hook" else max(options)

    # Mike fills the frame top to bottom, take the larger gap and hug the edge
    return TOP_SAFE if (top - TOP_SAFE) >= (lowest - bottom) else clamp(lowest)


def caption_plate(draw, canvas, lines: list[str], font, path_unused=None,
                  baseline: float = CAPTION_BASELINE, face=None) -> None:
    """Draw the house caption: one green plate, white text, sitting on a baseline.

    The plate is as wide as its longest line and grows upward, so the bottom
    edge never moves between cards. If Mike's head is in the band the whole
    plate lifts above it rather than crossing his face.
    """
    from PIL import Image, ImageDraw

    widths = [draw.textlength(line, font=font) for line in lines]
    plate_w = int(max(widths) + CAPTION_PAD_X * 2)
    plate_h = int(CAPTION_LINE * len(lines))
    bottom = H * baseline
    top = bottom - plate_h

    if face:
        head_top, head_bottom = face[1] - FACE_PAD, face[3] + FACE_PAD
        if top < head_bottom and bottom > head_top:
            lifted = head_top - plate_h
            if lifted >= TOP_SAFE:
                top, bottom = lifted, head_top
            elif head_bottom + plate_h <= BOTTOM_SAFE:
                top, bottom = head_bottom, head_bottom + plate_h

    x0 = int(W / 2 - plate_w / 2)
    draw.rectangle([x0, int(top), x0 + plate_w, int(top + plate_h)],
                   fill=CAPTION_GREEN + (255,))

    ascent, descent = font.getmetrics()
    for row, line in enumerate(lines):
        row_top = top + row * CAPTION_LINE
        y = row_top + (CAPTION_LINE - (ascent + descent)) / 2
        draw.text((W / 2 - widths[row] / 2, y), line, font=font,
                  fill=(255, 255, 255, 255))


def draw_caption(text: str, zone: str, font_path: str | None, path: Path,
                 face=None) -> Path | None:
    from PIL import Image, ImageDraw, ImageFont

    text = (text or "").strip()
    if not text:
        return None
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = (ImageFont.truetype(font_path, CAPTION_SIZE) if font_path
            else ImageFont.load_default(CAPTION_SIZE))
    lines = wrap_caption(text.upper(), font, int(W * CAPTION_WRAP), draw)
    caption_plate(draw, canvas, lines, font, face=face)
    canvas.save(path)
    return path


def build_watermark(logo_path: Path, destination: Path, width_frac: float | None,
                    margin_right: int, margin_top: int, opacity: float) -> Path:
    """Lay the channel logo into the top right of a transparent 1080x1920 plate."""
    from PIL import Image, ImageFilter

    logo = Image.open(logo_path)
    if logo.mode != "RGBA":
        if "A" not in logo.getbands():
            say(f"{logo_path.name} has no transparency, it will sit in a solid rectangle. "
                "A PNG with an alpha channel looks far better.")
        logo = logo.convert("RGBA")

    box = logo.getchannel("A").getbbox() if "A" in logo.getbands() else None
    native_content_w = (box[2] - box[0]) if box else logo.width

    if width_frac is None:
        # Auto: never enlarge the mark past its native pixels, and never let it
        # shrink below a readable 10 percent of frame width.
        target_w = max(int(W * 0.10), min(int(W * DEFAULT_LOGO_WIDTH), native_content_w))
    else:
        target_w = max(40, int(W * width_frac))
    target_h = max(1, int(round(logo.height * target_w / logo.width)))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    if opacity < 1.0:
        alpha = logo.getchannel("A").point(lambda value: int(value * opacity))
        logo.putalpha(alpha)

    upscale = target_w / max(1, native_content_w)
    if upscale > 1.15:
        say(f"the logo is being enlarged {upscale:.1f}x from its native size, it may look "
            "soft. A bigger export fixes it.")

    x = W - target_w - margin_right
    y = margin_top

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    silhouette = Image.new("RGBA", logo.size, (0, 0, 0, 130))
    shadow.paste(silhouette, (x, y + 5), logo)
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(7)))
    canvas.paste(logo, (x, y), logo)
    canvas.save(destination)

    if y + target_h > H * 0.16:
        say("the logo reaches down toward the hook caption zone, consider a smaller "
            "--logo-width if it crowds the text")
    return destination


def measure_words(words, font, draw, max_width):
    """Wrap words into lines, keeping each word's emphasis flag."""
    space = draw.textlength(" ", font=font)
    lines, current, width = [], [], 0.0
    for word in words:
        w = draw.textlength(word["text"], font=font)
        extra = w if not current else w + space
        if current and width + extra > max_width:
            lines.append(current)
            current, width = [word], w
        else:
            current.append(word)
            width += extra
    if current:
        lines.append(current)
    return lines


def draw_subtitle(words, font_path: str | None, size: int, top: float,
                  path: Path, face=None) -> tuple[Path, float]:
    """One subtitle card, drawn on the same green plate as every other caption.

    top is ignored, the plate sits on the house baseline so the bottom edge
    never moves from card to card. Emphasis is not coloured here, the reference
    Short runs every word in plain white.
    """
    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size)

    text = " ".join(w["text"] for w in words).upper()
    lines = wrap_caption(text, font, int(W * CAPTION_WRAP), draw)
    caption_plate(draw, canvas, lines, font, face=face)
    canvas.save(path)
    return path, CAPTION_LINE * len(lines)


def subtitle_block_height(phrases, font_path: str | None, size: int) -> float:
    """Tallest card in the scene, so the band never jumps between cards."""
    from PIL import Image, ImageDraw, ImageFont

    probe_img = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(probe_img)
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size)
    tallest = 0.0
    for phrase in phrases:
        text = " ".join(w["text"] for w in phrase["words"]).upper()
        lines = wrap_caption(text, font, int(W * CAPTION_WRAP), draw)
        tallest = max(tallest, CAPTION_LINE * len(lines))
    return tallest


def draw_cta_stickers(text: str, handle: str, display_font: str | None,
                      body_font: str | None, path: Path) -> Path:
    """The end card, drawn as a transparent plate to lay over live footage.

    One sticker per line, alternating white plate with green type and green
    plate with white type, each tilted a degree or two so the stack reads as
    stickers rather than a lower third. The handle sits under it in a pill.
    """
    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    probe = ImageDraw.Draw(canvas)
    font = (ImageFont.truetype(display_font, CTA_FONT_SIZE) if display_font
            else ImageFont.load_default(CTA_FONT_SIZE))

    # Short lines. The stack reads as stickers only when each one is a beat of
    # its own, so an explicit newline in the guide wins and the auto wrap is tight.
    raw = [part.strip() for part in text.strip().upper().split("\n") if part.strip()]
    lines = []
    for part in raw:
        lines.extend(wrap_caption(part, font, int(W * 0.52), probe))
    ascent, descent = font.getmetrics()
    cap = ascent - descent // 2
    box_h = cap + CTA_PAD_Y * 2
    green, white = CAPTION_GREEN + (255,), (255, 255, 255, 255)

    plates = []
    for row, line in enumerate(lines):
        text_w = probe.textlength(line, font=font)
        box_w = int(text_w + CTA_PAD_X * 2)
        plate = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        pen = ImageDraw.Draw(plate)
        fill = white if row % 2 == 0 else green
        ink = green if row % 2 == 0 else white
        pen.rounded_rectangle([0, 0, box_w - 1, box_h - 1], radius=16, fill=fill)
        pen.text((CTA_PAD_X, CTA_PAD_Y - descent // 2), line, font=font, fill=ink)
        plates.append(plate.rotate(CTA_TILTS[row % len(CTA_TILTS)], expand=True,
                                   resample=Image.BICUBIC))

    handle_plate = None
    if handle:
        hfont = (ImageFont.truetype(body_font, 34) if body_font
                 else ImageFont.load_default(34))
        label = handle.strip().upper()
        text_w = probe.textlength(label, font=hfont)
        icon = 46
        pill_h, gap = 84, 14
        pill_w = int(text_w + icon + gap + 26 * 2)
        handle_plate = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 0))
        pen = ImageDraw.Draw(handle_plate)
        pen.rounded_rectangle([0, 0, pill_w - 1, pill_h - 1], radius=pill_h // 2, fill=green)
        cx, cy = 26 + icon / 2, pill_h / 2
        pen.ellipse([cx - icon / 2, cy - icon / 2, cx + icon / 2, cy + icon / 2], fill=white)
        pen.polygon([(cx - 7, cy - 11), (cx - 7, cy + 11), (cx + 12, cy)], fill=green)
        ha, hd = hfont.getmetrics()
        pen.text((26 + icon + gap, cy - (ha + hd) / 2 + 2), label, font=hfont, fill=white)

    overlap = 6
    stack_h = sum(plate.height for plate in plates) - overlap * (len(plates) - 1)
    total = stack_h + (handle_plate.height + 30 if handle_plate else 0)
    y = int(H * 0.48 - total / 2)
    for plate in plates:
        canvas.alpha_composite(plate, (int(W / 2 - plate.width / 2), y))
        y += plate.height - overlap
    if handle_plate:
        canvas.alpha_composite(handle_plate,
                               (int(W / 2 - handle_plate.width / 2), y + 30))
    canvas.save(path)
    return path


# --------------------------------------------------------------------------
# stage 5: assembly
# --------------------------------------------------------------------------

def render_scene(scene: Scene, source: Path, src_w: int, src_h: int, src_has_audio: bool,
                 parts: Path, font_path: str | None, watermark: Path | None,
                 destination: Path, phrases: list[dict] | None = None,
                 caption_mode: str = "subtitles",
                 caption_cards: list[tuple] | None = None) -> None:
    duration = scene.duration
    window = crop_window(src_w, src_h, scene.crop_x, scene.zoom, scene.crop_y)
    crop_w, crop_h, x0, y0 = window
    parts.mkdir(parents=True, exist_ok=True)

    # With a pan, anything drawn on the frame belongs where the move ends, and it
    # waits for the move to finish rather than sliding across the shot.
    settle = 0.0
    window_end = window
    if scene.pan:
        window_end = crop_window(src_w, src_h, scene.pan["to"], scene.zoom, scene.crop_y)
        settle = round(duration * 0.60, 2)

    annotation_png = draw_annotations(scene, src_w, src_h, window_end,
                                      parts / f"ann{scene.number:02d}.png")
    face = face_rect_in_frame(scene, src_w, src_h, window)
    if scene.pan:
        face_end = face_rect_in_frame(scene, src_w, src_h, window_end)
        if face and face_end:
            face = [min(face[0], face_end[0]), min(face[1], face_end[1]),
                    max(face[2], face_end[2]), max(face[3], face_end[3])]
        else:
            face = face or face_end

    subtitle_cards = []
    caption_png = None
    if caption_mode in ("subtitles", "both") and phrases:
        size = 72
        block = subtitle_block_height(phrases, font_path, size)
        band = place_caption(block, "support", face)
        for i, phrase in enumerate(phrases):
            card, _ = draw_subtitle(phrase["words"], font_path, size, band,
                                    parts / f"sub{scene.number:02d}_{i:02d}.png")
            subtitle_cards.append((card, phrase["start"], phrase["end"]))
        say(f"scene {scene.number}: {len(subtitle_cards)} subtitle cards, "
            f"band at y {int(band)}" + (", clear of Mike's head" if face else ""))
    timed_captions = []
    if caption_mode in ("labels", "both"):
        if caption_cards:
            # One uninterrupted shot carrying more than one line, so the label
            # changes on time instead of the picture cutting.
            for order, (text, zone, from_t, to_t) in enumerate(caption_cards):
                card = draw_caption(text, zone, font_path,
                                    parts / f"cap{scene.number:02d}_{order}.png", face)
                if card:
                    timed_captions.append((card, from_t, to_t))
        else:
            caption_png = draw_caption(scene.caption, scene.caption_zone, font_path,
                                       parts / f"cap{scene.number:02d}.png", face)
    overlay_mov = None
    if scene.overlay:
        overlay_mov = asset(f"overlays/{scene.overlay}", scene.overlay)
        if overlay_mov is None:
            say(f"scene {scene.number}: overlay {scene.overlay} missing from assets/, skipped")

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
    timed_cap_indexes = []
    for card, _, _ in timed_captions:
        cmd += ["-loop", "1", "-t", f"{duration:.2f}", "-i", str(card)]
        timed_cap_indexes.append(index)
        index += 1

    sub_indexes = []
    for card, _, _ in subtitle_cards:
        cmd += ["-loop", "1", "-t", f"{duration:.2f}", "-i", str(card)]
        sub_indexes.append(index)
        index += 1
    wm_index = None
    if watermark:
        cmd += ["-loop", "1", "-t", f"{duration:.2f}", "-i", str(watermark)]
        wm_index = index
        index += 1

    if scene.pan:
        # Scale first, then slide a full height 9:16 window across the frame. Doing
        # it in output space keeps the move smooth instead of stepping a source pixel
        # at a time, and the scale is exactly what filling the frame needs, no more.
        settle_at = max(duration * 0.60, 0.1)
        span = f"min(t/{settle_at:.3f},1)"
        ease = f"(3*pow({span},2)-2*pow({span},3))"
        start, end = scene.pan["from"], scene.pan["to"]
        centre = f"({start:.4f}+({end - start:.4f})*{ease})"
        x_expr = f"max(0\,min(iw-{W}\,{centre}*iw-{W // 2}))"
        chain = [f"[0:v]scale=-2:{H}:flags=lanczos,"
                 f"crop={W}:{H}:x='{x_expr}':y=0,setsar=1,fps={FPS}[base]"]
    else:
        chain = [f"[0:v]crop={crop_w}:{crop_h}:{x0}:{y0},"
                 f"scale={W}:{H}:flags=lanczos,setsar=1,fps={FPS}[base]"]
    label = "base"

    if ann_index is not None:
        chain.append(f"[{ann_index}:v]scale={W}:{H}[ann]")
        gate = f":enable='gte(t,{settle:.2f})'" if settle > 0 else ""
        chain.append(f"[{label}][ann]overlay=0:0:format=auto{gate}[anned]")
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

    for position, (input_index, (_, from_t, to_t)) in enumerate(zip(timed_cap_indexes,
                                                                    timed_captions)):
        chain.append(f"[{input_index}:v]scale={W}:{H}[capsrc{position}]")
        chain.append(f"[{label}][capsrc{position}]overlay=0:0:format=auto:"
                     f"enable='between(t,{from_t:.3f},{to_t:.3f})'[capped{position}]")
        label = f"capped{position}"

    for position, (input_index, (_, start, end)) in enumerate(zip(sub_indexes, subtitle_cards)):
        chain.append(f"[{input_index}:v]scale={W}:{H}[subsrc{position}]")
        chain.append(f"[{label}][subsrc{position}]overlay=0:0:format=auto:"
                     f"enable='between(t,{start:.3f},{end:.3f})'[sub{position}]")
        label = f"sub{position}"

    if ov_index is not None:
        chain.append(f"[{ov_index}:v]scale={W}:{H},setsar=1[ovl]")
        chain.append(f"[{label}][ovl]overlay=0:0:format=auto:shortest=0:eof_action=pass[out]")
        label = "out"

    if wm_index is not None:
        chain.append(f"[{wm_index}:v]scale={W}:{H}[wm]")
        chain.append(f"[{label}][wm]overlay=0:0:format=auto[marked]")
        label = "marked"

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


def has_alpha(path: Path) -> bool:
    fmt = probe(path, "v:0", "stream=pix_fmt") or ""
    return any(token in fmt for token in ("yuva", "rgba", "argb", "abgr", "bgra", "ya"))


def find_end_card() -> Path | None:
    """A branded end card animation, if the team has supplied one.

    With an alpha channel it is composited over the live tail, replacing the
    drawn sticker stack. Without one it plays as its own clip at the end.
    """
    for folder in (ASSETS / "overlays", ASSETS):
        for path in sorted(folder.glob("end_card.*")) + sorted(folder.glob("endcard.*")):
            if path.suffix.lower() in (".mov", ".webm", ".mp4", ".mkv", ".png", ".gif"):
                return path
    return None


def render_end_card_clip(card: Path, watermark: Path | None, destination: Path) -> float:
    """A supplied end card with no transparency just plays as the closing clip."""
    chain = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
             f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS}[base]"]
    inputs = ["-i", str(card)]
    seconds = media_duration(card)
    if watermark:
        inputs += ["-loop", "1", "-t", f"{seconds:.2f}", "-i", str(watermark)]
        chain.append("[base][1:v]overlay=0:0[v]")
        silence = 2
    else:
        chain.append("[base]copy[v]")
        silence = 1
    inputs += ["-f", "lavfi", "-t", f"{seconds:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
    audio = f"{silence}:a" if not has_audio(card) else "0:a"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
         "-filter_complex", ";".join(chain), "-map", "[v]", "-map", audio,
         "-t", f"{seconds:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         "-video_track_timescale", "30000", str(destination)])
    return seconds


def render_cta(text: str, handle: str, display_font: str | None, body_font: str | None,
               parts: Path, watermark: Path | None, destination: Path,
               source: Path, start: float, src_w: int, src_h: int,
               crop_x: float = 0.5, zoom: float = 1.0,
               animation: Path | None = None) -> float:
    """The end card plays over live footage, not over a black card.

    The reference Short holds the last reveal shot and lays the sticker stack on
    top of it, so the video never goes dead before the viewer decides to follow.
    """
    seconds = CTA_SECONDS
    if animation is not None:
        seconds = max(1.0, media_duration(animation))
        say(f"end card: {animation.name}, {seconds:.1f}s, alpha composited over the "
            "live tail")
        overlay = ["-i", str(animation)]
        cta_filter = "[base][1:v]overlay=0:0:shortest=0[withcta]"
    else:
        png = draw_cta_stickers(text, handle, display_font, body_font, parts / "cta.png")
        overlay = ["-loop", "1", "-t", f"{seconds}", "-i", str(png)]
        cta_filter = "[base][1:v]overlay=0:0[withcta]"

    crop_w, crop_h, x0, y0 = crop_window(src_w, src_h, crop_x, zoom, 0.5)
    chain = [f"[0:v]crop={crop_w}:{crop_h}:{x0}:{y0},scale={W}:{H}:flags=lanczos,"
             f"setsar=1,fps={FPS}[base]",
             cta_filter]
    inputs = ["-ss", f"{start:.3f}", "-t", f"{seconds}", "-i", str(source), *overlay]
    if watermark:
        inputs += ["-loop", "1", "-t", f"{seconds}", "-i", str(watermark)]
        chain.append("[withcta][2:v]overlay=0:0[v]")
    else:
        chain.append("[withcta]copy[v]")
    silence = 3 if watermark else 2
    inputs += ["-f", "lavfi", "-t", f"{seconds}", "-i", "anullsrc=r=48000:cl=stereo"]
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
         "-filter_complex", ";".join(chain), "-map", "[v]", "-map", f"{silence}:a",
         "-t", f"{seconds}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         "-video_track_timescale", "30000", str(destination)])


def mix_audio(body: Path, vo_lines: list[dict] | None, starts: list[float],
              whoosh_at: float | None, music: Path | None, destination: Path,
              location_level: float = 0.0, master: Path | None = None) -> None:
    whoosh = asset("whoosh.wav", "whoosh.mp3")
    impact = asset("impact.wav", "impact.mp3")
    duration = media_duration(body)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(body)]
    chain, mix_labels = [], []
    index = 1

    if location_level > 0:
        chain.append(f"[0:a]volume={location_level:.3f}[orig]")
        mix_labels.append("[orig]")
    else:
        say("original location audio muted, the VO carries the whole track")

    if master:
        # One unbroken take laid at zero. The picture was cut to it, so there is
        # nothing to place and no join anywhere in the narration.
        head = min((item.get("at", 0.0) for item in (vo_lines or []) if item.get("phrases")),
                   default=0.0)
        offset = int(max(0.0, starts[0] if starts else 0.0) * 1000)
        trim = f"atrim={head:.3f},asetpts=PTS-STARTPTS," if head > 0.01 else ""
        chain.append(f"[{index}:a]aresample=48000,{trim}"
                     f"adelay={offset}|{offset},volume=1.0[vo]")
        mix_labels.append("[vo]")
        cmd += ["-i", str(master)]
        index += 1
    elif vo_lines:
        for position, item in enumerate(vo_lines):
            if not item["path"]:
                continue
            cmd += ["-i", str(item["path"])]
            offset = int(max(0.0, starts[position]) * 1000)
            chain.append(f"[{index}:a]aresample=48000,adelay={offset}|{offset},"
                         f"volume=1.0[vo{position}]")
            mix_labels.append(f"[vo{position}]")
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

    if not mix_labels:
        cmd += ["-f", "lavfi", "-t", f"{duration:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
        chain.append(f"[{index}:a]anull[silent]")
        mix_labels.append("[silent]")
        index += 1

    # duration=longest, then pad and trim to the picture. Anchoring to the first
    # input would cut the whole mix at the end of whichever layer happens to be
    # first, which is a VO line once the location track is muted.
    chain.append("".join(mix_labels) +
                 f"amix=inputs={len(mix_labels)}:duration=longest:normalize=0,"
                 "alimiter=limit=0.95,aresample=48000,"
                 f"apad,atrim=0:{duration:.3f},asetpts=N/SR/TB[aout]")

    cmd += ["-filter_complex", ";".join(chain), "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(destination)]
    run(cmd)


def check_reveal_balance(scenes: list[Scene], guide: dict) -> None:
    """The finished house carries the Short. Before footage is the hook only.

    The guide declares reveal_from, the point in the episode after which the
    footage is the finished house, and optionally avoid_ranges for anything that
    must never appear, such as Mike's cost slide.
    """
    reveal = guide.get("reveal_from")
    if reveal:
        cutoff = to_seconds(str(reveal).split("-")[0])
        allowed = int(guide.get("hook_scenes", 1))
        before = [s for s in scenes if s.start < cutoff]
        for scene in before:
            if scene.number > allowed:
                say(f"PRE-DEMO: scene {scene.number} uses footage before the reveal at "
                    f"{stamp(cutoff)}. Only the hook may sit in the before, everything "
                    "else belongs in the finished house.")
        share = sum(s.duration for s in before) / max(sum(s.duration for s in scenes), 0.01)
        if share > 0.35:
            say(f"PRE-DEMO: {share * 100:.0f} percent of the runtime is before footage. "
                "The finished house should carry the Short.")

    for entry in guide.get("avoid_ranges") or []:
        start, end = parse_range(entry.get("range", "0 - 0"))
        for scene in scenes:
            if min(scene.end, end) - max(scene.start, start) > 0.05:
                say(f"AVOID: scene {scene.number} overlaps {entry.get('range')}, "
                    f"{entry.get('reason', 'marked do not use')}")


def check_footage_reuse(scenes: list[Scene], work: Path, index: int) -> None:
    """No frame should appear twice, and no cut should land between two shots
    that look the same. Two beats can share one take, but only as one continuous
    run: the second starts exactly where the first ends."""
    for position, scene in enumerate(scenes):
        for other in scenes[position + 1:]:
            overlap = min(scene.end, other.end) - max(scene.start, other.start)
            if overlap > 0.05:
                say(f"REPEAT: scenes {scene.number} and {other.number} both use "
                    f"{stamp(max(scene.start, other.start))} to "
                    f"{stamp(min(scene.end, other.end))}, {overlap:.1f}s of the same footage")

    for first, second in zip(scenes, scenes[1:]):
        gap = second.start - first.end
        if 0.05 < gap < 0.5:
            say(f"JUMP CUT: scene {second.number} starts {gap:.2f}s after scene "
                f"{first.number} ends, close enough to look like the same frame. "
                "Either start it exactly where the previous scene ends, so the take "
                "runs continuously, or move it somewhere else in the episode.")

    for other in sorted(work.glob("short*/edits.json")):
        if other.parent.name == f"short{index}":
            continue
        try:
            data = json.loads(other.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for entry in data.get("scenes", []):
            start, end = parse_range(entry.get("source", "0 - 0"))
            for scene in scenes:
                overlap = min(scene.end, end) - max(scene.start, start)
                if overlap > 0.05:
                    say(f"REPEAT across Shorts: scene {scene.number} shares {overlap:.1f}s "
                        f"with {other.parent.name} scene {entry.get('scene')}")


def stage_assemble(scenes: list[Scene], short: dict, guide: dict, source: Path,
                   vo_lines: list[dict] | None, work: Path, index: int, slug: str,
                   font_path: str | None, music: Path | None,
                   watermark: Path | None, caption_mode: str = "labels",
                   location_level: float = 0.0,
                   display_font: str | None = None,
                   master: Path | None = None) -> tuple[Path, list[float]]:
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

    if vo_lines:
        fit_scenes_to_lines(scenes, vo_lines, source_seconds)
    check_footage_reuse(scenes, work, index)
    check_reveal_balance(scenes, guide)

    # Each Short of an episode gets its own parts directory. They used to share
    # one, so building Short 2 wiped Short 1's clips out from under it.
    parts = work / f"short{index}" / "parts"
    if parts.exists():
        shutil.rmtree(parts)
    parts.mkdir(parents=True)

    # Consecutive scenes that continue the same take render as ONE clip, so the
    # picture never cuts mid action. Their lines still change on time.
    shots: list[list[int]] = []
    for position, scene in enumerate(scenes):
        if shots and scene.continues_previous:
            shots[-1].append(position)
        else:
            shots.append([position])

    clips, starts, elapsed = [], [0.0] * len(scenes), 0.0
    for shot in shots:
        members = [scenes[i] for i in shot]
        lead = members[0]
        clip = parts / f"shot{lead.number:02d}.mp4"

        held = lead
        if len(members) > 1:
            held = Scene(number=lead.number, start=lead.start, end=members[-1].end,
                         vo=lead.vo, caption=lead.caption, notes=lead.notes,
                         caption_zone=lead.caption_zone, overlay=lead.overlay,
                         transition=lead.transition, crop_x=lead.crop_x,
                         crop_y=lead.crop_y, zoom=lead.zoom, face=lead.face,
                         annotations=[a for m in members for a in m.annotations],
                         source_label=lead.source_label)
            if lead.pan or members[-1].pan:
                held.pan = {"from": (lead.pan or {}).get("from", lead.crop_x),
                            "to": (members[-1].pan or {}).get("to", members[-1].crop_x)}
            say(f"scenes {', '.join(str(m.number) for m in members)}: one continuous take, "
                f"{stamp(held.start)} to {stamp(held.end)}, no cut between them")

        say(f"scene {held.number}: {stamp(held.start)} to {stamp(held.end)}, "
            f"crop {held.crop_x:.2f}/{held.crop_y:.2f} zoom {held.zoom:.2f}"
            f"{', ' + str(len(held.annotations)) + ' annotation(s)' if held.annotations else ''}")

        cards, phrases, offset = [], [], 0.0
        for member in members:
            cards.append((member.caption, member.caption_zone, offset,
                          offset + member.duration))
            if vo_lines:
                for phrase in vo_lines[scenes.index(member)]["phrases"]:
                    phrases.append({**phrase,
                                    "start": phrase["start"] + offset,
                                    "end": phrase["end"] + offset})
            offset += member.duration

        render_scene(held, source, src_w, src_h, src_audio, parts, font_path,
                     watermark, clip, phrases or None, caption_mode,
                     cards if len(members) > 1 else None)
        clips.append(clip)

        measured = media_duration(clip)
        share = elapsed
        for member in members:
            starts[scenes.index(member)] = share
            share += member.duration * (measured / max(held.duration, 0.01))
        elapsed += measured

    cta_text = short.get("cta_frame") or CTA_DEFAULT
    handle = guide.get("handle", CTA_HANDLE)
    # The end card holds live footage. Prefer a range the guide names, otherwise
    # carry on straight out of the last scene so the picture never goes dead.
    cta_start, cta_crop, cta_zoom = scenes[-1].end, scenes[-1].crop_x, scenes[-1].zoom
    if short.get("cta_source"):
        cta_start = parse_range(short["cta_source"])[0]
    if cta_start + CTA_SECONDS > source_seconds:
        cta_start = max(0.0, source_seconds - CTA_SECONDS)
    cta_clip = parts / "cta.mp4"
    supplied = find_end_card()
    if supplied is not None and not has_alpha(supplied):
        say(f"end card: {supplied.name}, no alpha channel, playing it as the closing clip")
        cta_seconds = render_end_card_clip(supplied, watermark, cta_clip)
    else:
        cta_seconds = render_cta(cta_text, handle, display_font or font_path, font_path,
                                 parts, watermark, cta_clip, source, cta_start,
                                 src_w, src_h, cta_crop, cta_zoom, supplied)
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
    mix_audio(body, vo_lines, starts, whoosh_at, music, final, location_level, master)
    say(f"final: {final.relative_to(REPO_ROOT)}, {media_duration(final):.1f}s")
    return final, starts


# --------------------------------------------------------------------------
# stage 6: contact sheet
# --------------------------------------------------------------------------

def stage_contact_sheet(final: Path, scenes: list[Scene], starts: list[float],
                        work: Path, slug: str, index: int, font_path: str | None) -> Path:
    stage("Stage 6, contact sheet")
    from PIL import Image, ImageDraw, ImageFont

    shots = work / f"short{index}" / "parts" / "sheet"
    shots.mkdir(parents=True, exist_ok=True)
    total = media_duration(final)

    grabs = []
    marks = [starts[i] + (scenes[i].duration / 2) for i in range(len(scenes))]
    body_end = starts[-1] + scenes[-1].duration
    marks.append(min(total - 0.3, body_end + (total - body_end) / 2))
    labels = [f"{scene.number}. {scene.caption or scene.vo[:40]}" for scene in scenes] + ["CTA"]

    for position, mark in enumerate(marks):
        target = shots / f"cell{position:02d}.jpg"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{max(0.0, min(mark, total - 0.1)):.2f}", "-i", str(final),
             "-frames:v", "1", "-q:v", "3", str(target)])
        grabs.append(target)

    columns = min(4, len(grabs))
    rows = (len(grabs) + columns - 1) // columns
    cell_w, cell_h = 320, 569
    pad, caption_h, header = 16, 54, 92

    sheet = Image.new("RGB", (columns * (cell_w + pad) + pad,
                              header + rows * (cell_h + caption_h + pad) + pad),
                      (24, 26, 28))
    draw = ImageDraw.Draw(sheet)
    title_font = ImageFont.truetype(font_path, 30) if font_path else ImageFont.load_default(30)
    label_font = ImageFont.truetype(font_path, 17) if font_path else ImageFont.load_default(17)

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
        for line_no, line in enumerate(textwrap.wrap(text, 32)[:2]):
            draw.text((x, y + cell_h + 8 + line_no * 20), line, font=label_font,
                      fill=(214, 219, 223))

    destination = OUTPUT / f"{slug}-short-{index}-contact-sheet.jpg"
    sheet.save(destination, quality=88)
    say(f"contact sheet: {destination.relative_to(REPO_ROOT)}")
    return destination


# --------------------------------------------------------------------------
# stage 7: publish pack and thumbnail
# --------------------------------------------------------------------------

DEFAULT_HASHTAGS = ["#homeremodel", "#remodeling", "#renovation", "#contractor"]


def stage_publish_pack(final: Path, guide: dict, short: dict, index: int,
                       slug: str, starts: list[float]) -> tuple[Path, Path]:
    """Everything the publishing checklist asks for, next to the video."""
    stage("Stage 7, publish pack and thumbnail")

    thumb = OUTPUT / f"{slug}-short-{index}-thumbnail.jpg"
    grab_at = min(1.2, max(0.4, (starts[1] if len(starts) > 1 else 2.0) / 2))
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{grab_at:.2f}", "-i", str(final),
         "-frames:v", "1", "-q:v", "2", str(thumb)])
    say(f"thumbnail: {thumb.relative_to(REPO_ROOT)}, first frame style, grabbed at {grab_at:.1f}s")

    titles = short.get("seo_titles") or [short.get("working_title", "")]
    cta = short.get("cta", {})
    link = guide.get("video_url", "")
    tags = guide.get("hashtags") or DEFAULT_HASHTAGS
    body = short.get("description") or (
        f"{titles[0]}.\n\n"
        f"{short.get('primary_goal', '')}\n\n"
        f"Watch the full remodel: {link}"
    )

    lines = [
        f"# Publish pack, Short {index}",
        "",
        f"Episode: {guide.get('episode', '')}",
        f"Video: {final.name}",
        f"Thumbnail: {thumb.name}",
        "",
        "## SEO title, use the first unless you prefer another",
        "",
    ]
    lines += [f"{i}. {t}" for i, t in enumerate(titles, start=1)]
    lines += [
        "",
        "## Description",
        "",
        body,
        "",
        " ".join(tags),
        "",
        "## Pinned comment",
        "",
        cta.get("pinned", "").replace("[full video link]", link) or link,
        "",
        "## Hashtags",
        "",
        " ".join(tags),
        "",
        "## Checklist",
        "",
    ]
    lines += [f"- [ ] {item}" for item in (guide.get("checklist") or DEFAULT_CHECKLIST_FALLBACK)]
    pack = OUTPUT / f"{slug}-short-{index}-publish.md"
    pack.write_text("\n".join(lines) + "\n", encoding="utf-8")
    say(f"publish pack: {pack.relative_to(REPO_ROOT)}")
    return pack, thumb


DEFAULT_CHECKLIST_FALLBACK = [
    "Hook lands within 2 seconds",
    "VO recorded and mixed",
    "Captions burned in",
    "Thumbnail reviewed",
    "SEO title finalized",
    "Description written with link to the full video",
    "Pinned comment prepared",
    "Hashtags added",
    "Published to YouTube Shorts",
]


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
    parser.add_argument("--vo", type=Path, default=None,
                        help="a narration file you recorded yourself. It is used exactly "
                             "as supplied, never cut or retimed. The script lines are "
                             "located inside it with whisper and the picture is cut to "
                             "them")
    parser.add_argument("--voice-id", default=None, help="ElevenLabs voice id for Mike")
    parser.add_argument("--model-id", default=ELEVEN_DEFAULT_MODEL)
    parser.add_argument("--captions", choices=["subtitles", "labels", "both"],
                        default="subtitles",
                        help="subtitles follow what Mike actually says, labels are the "
                             "guide's summary captions, both draws each in its own band")
    parser.add_argument("--location-audio", type=float, default=0.0,
                        help="level for the original clip audio, 0 mutes it, "
                             "0.03 is the old low bed under the VO")
    parser.add_argument("--style", type=float, default=VOICE_STYLE,
                        help="ElevenLabs style exaggeration, higher is more animated")
    parser.add_argument("--stability", type=float, default=VOICE_STABILITY,
                        help="ElevenLabs stability, lower lets the delivery move more")
    parser.add_argument("--similarity", type=float, default=VOICE_SIMILARITY)
    parser.add_argument("--line-gap", type=float, default=0.0,
                        help="unused now that the narration is one continuous take, the "
                             "pauses the read already has are what the picture cuts on")
    parser.add_argument("--music", type=Path, default=None, help="music bed override")
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--logo", type=Path, default=None,
                        help="watermark logo override, defaults to assets/logo.png")
    parser.add_argument("--no-logo", action="store_true", help="build without the watermark")
    parser.add_argument("--logo-width", type=float, default=None,
                        help="watermark width as a fraction of frame width. Default is "
                             "automatic, up to 0.16 but never enlarging the mark past its "
                             "native pixels")
    parser.add_argument("--logo-opacity", type=float, default=0.92)
    parser.add_argument("--font", default=None, help="bold TTF for captions")
    parser.add_argument("--source", type=Path, default=None,
                        help="use a local video file instead of downloading, for when "
                             "YouTube blocks the container or you already have the master")
    parser.add_argument("--cookies", type=Path, default=None,
                        help="cookies.txt for yt-dlp, defaults to cookies.txt at the repo root")
    parser.add_argument("--redownload", action="store_true")
    parser.add_argument("--revoice", action="store_true", help="resynthesize the VO")
    args = parser.parse_args()

    load_dotenv()

    for binary in ("ffmpeg", "ffprobe", "yt-dlp"):
        if shutil.which(binary) is None:
            die(f"{binary} is not installed and this pipeline cannot run without it")

    sys.path.insert(0, str(SCRIPTS))
    from fetch_transcript import extract_video_id  # noqa: E402

    # The first argument is normally a YouTube URL, but a local master works too,
    # for episodes that are not on YouTube or that YouTube will not serve.
    local_media = Path(args.url)
    if local_media.exists() and local_media.is_file():
        video_id = slugify(local_media.parent.name if local_media.parent.name != "work"
                           else local_media.stem)
        args.source = args.source or local_media
        say(f"local source: {local_media}")
    else:
        video_id = extract_video_id(args.url)
    work = WORK / video_id
    work.mkdir(parents=True, exist_ok=True)

    cookies = find_cookies(args.cookies)
    guide_path = stage_guide(args.url, video_id, args.guide, True, cookies)
    guide, short = load_short(guide_path, args.number)
    slug = slugify(guide.get("episode") or guide_path.stem)
    scenes = scenes_from_short(short)

    source = stage_download(args.url, work, args.redownload, args.source, cookies)

    rescan = {int(n) for n in args.rescan.split(",") if n.strip()} if args.rescan else None
    edits = stage_analyze(source, scenes, work, video_id, args.number, args.auto,
                          rescan, guide)
    apply_edits(scenes, edits)

    voice_settings = {"stability": args.stability, "style": args.style,
                      "similarity": args.similarity}
    voice_settings.update(guide.get("voice_settings") or {})
    vo_lines, vo_master = stage_vo(short, scenes, work, args.number, args.skip_vo,
                                   args.revoice, args.voice_id, args.model_id,
                                   args.line_gap, voice_settings, args.vo)

    font_path = args.font or find_font()
    if font_path is None:
        say("no bold TTF found, captions fall back to the built in font")

    music = None
    if not args.no_music:
        music = args.music or asset("music.mp3", "music.wav", "music.m4a")
        if music is None:
            say("no music bed in assets/, building without one")

    watermark = None
    if not args.no_logo:
        logo = find_logo(args.logo)
        if logo is None:
            say("no logo in assets/, building without the watermark")
        else:
            # Measured off the channel's own Shorts: hard into the corner.
            watermark = build_watermark(logo, work / "watermark.png",
                                        args.logo_width, 16, 26, args.logo_opacity)
            from PIL import Image
            with Image.open(watermark) as plate:
                mark = plate.getchannel("A").getbbox()
            say(f"watermark: {logo.name}, top right, "
                f"{(mark[2] - mark[0]) if mark else 0}px wide")

    display_font = find_font(DISPLAY_FONT_CANDIDATES)
    final, starts = stage_assemble(scenes, short, guide, source, vo_lines, work, args.number,
                                   slug, font_path, music, watermark, args.captions,
                                   args.location_audio, display_font, vo_master)
    sheet = stage_contact_sheet(final, scenes, starts, work, slug, args.number, font_path)
    pack, thumb = stage_publish_pack(final, guide, short, args.number, slug, starts)

    print("\nDone.")
    print(f"  Short:         {final.relative_to(REPO_ROOT)}")
    print(f"  Contact sheet: {sheet.relative_to(REPO_ROOT)}")
    print(f"  Thumbnail:     {thumb.relative_to(REPO_ROOT)}")
    print(f"  Publish pack:  {pack.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
