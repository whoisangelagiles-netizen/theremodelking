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
EMPHASIS_GREEN = (46, 214, 116)   # brand green lifted so it reads over dark footage
W, H = 1080, 1920
FPS = 30
CTA_SECONDS = 2.4
DEFAULT_LOGO_WIDTH = 0.16
MIN_SCENE_SECONDS = 1.2

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

ELEVEN_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
SUB_MAX_WORDS = 4            # words per subtitle card
SUB_MAX_CHARS = 26           # characters per subtitle card
SUB_TAIL = 0.30              # how long a card may linger before the next one
HANGING_WORDS = {
    "the", "a", "an", "and", "or", "but", "so", "to", "of", "in", "on", "at", "for",
    "with", "is", "was", "were", "we", "it", "that", "this", "your", "our", "my",
    "you", "i", "he", "she", "they", "had", "has", "have", "could", "would", "can",
    "just", "some", "out", "up", "into", "how",
}
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
    annotations: list = field(default_factory=list)
    crop_x: float = 0.5
    source_label: str = ""
    face: dict | None = None

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
                "crop_x": 0.5,
                "punch_in": {"zoom": 1.28, "focus": [0.5, 0.45]} if wants_punch_in(scene.notes) else None,
                "annotations": wanted_annotations(scene.notes),
                "face": {"x": None, "y": None, "w": None, "h": None},
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

def word_is_emphasis(word: str) -> bool:
    letters = "".join(c for c in word if c.isalpha())
    return len(letters) >= 2 and letters.isupper()


def phrases_from_alignment(chars: list[str], starts: list[float],
                           ends: list[float]) -> list[dict]:
    """Character timings into short subtitle cards that follow the read."""
    words, current = [], None
    for char, start, end in zip(chars, starts, ends):
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
        "words": [{"text": w["text"], "emph": word_is_emphasis(w["text"])} for w in g],
        "start": round(g[0]["start"], 3),
        "end": round(g[-1]["end"], 3),
    } for g in groups if g]

    # hold each card until the next one starts, so the screen is never empty
    for index, phrase in enumerate(phrases):
        limit = phrases[index + 1]["start"] if index + 1 < len(phrases) else phrase["end"] + SUB_TAIL
        phrase["end"] = round(min(limit, phrase["end"] + SUB_TAIL), 3)
    return phrases


def eleven_tts(text: str, previous_text: str, next_text: str, api_key: str,
               voice_id: str, model_id: str, destination: Path) -> list[dict]:
    """One ElevenLabs render. previous_text and next_text keep prosody continuous
    across separately rendered lines, so a per line read still sounds like one take."""
    body = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8,
                           "style": 0.35, "use_speaker_boost": True},
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


def stage_vo(short: dict, scenes: list[Scene], work: Path, index: int, skip: bool,
             force: bool, voice_id: str | None, model_id: str,
             gap: float) -> list[dict] | None:
    """Render one audio clip per scene line, so every scene can be cut to its own line.

    Returns a list of {scene, path, speech, hold} in scene order. A single block
    render cannot be synced to picture, because nothing tells you where one line
    ends and the next begins.
    """
    stage("Stage 4, ElevenLabs voice over, one clip per line")

    lines_dir = work / f"short{index}" / "vo_lines"
    texts = [" ".join((scene.vo or "").split()) for scene in scenes]
    if not any(texts):
        die("no per scene VO lines in the guide, nothing to synthesize")

    if skip:
        say("--skip-vo, building picture with no narration track")
        return None

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        die("ELEVENLABS_API_KEY is not set. Export it in your shell, never commit it.\n"
            "  Or rerun with --skip-vo to build the picture without narration.")
    voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID")
    if not voice_id:
        die("no voice id. Pass --voice-id or export ELEVENLABS_VOICE_ID with Mike's voice.")

    rendered = []
    for position, (scene, text) in enumerate(zip(scenes, texts)):
        path = lines_dir / f"line{scene.number:02d}.mp3"
        if not text:
            rendered.append({"scene": scene.number, "path": None, "speech": 0.0,
                             "hold": max(MIN_SCENE_SECONDS, scene.duration),
                             "phrases": []})
            continue
        phrase_file = path.with_suffix(".phrases.json")
        if path.exists() and phrase_file.exists() and not force:
            phrases = json.loads(phrase_file.read_text(encoding="utf-8"))
            say(f"line {scene.number}: cached, {media_duration(path):.2f}s, "
                f"{len(phrases)} subtitle cards")
        else:
            phrases = eleven_tts(text,
                                 texts[position - 1] if position else "",
                                 texts[position + 1] if position + 1 < len(texts) else "",
                                 api_key, voice_id, model_id, path)
            say(f"line {scene.number}: {len(text.split())} words, "
                f"{media_duration(path):.2f}s, {len(phrases)} subtitle cards")
        speech = media_duration(path)
        rendered.append({"scene": scene.number, "path": path, "speech": speech,
                         "hold": speech + gap, "phrases": phrases})
    total = sum(item["hold"] for item in rendered)
    say(f"narration total {total:.1f}s including {gap:.2f}s between lines")
    return rendered


def fit_scenes_to_lines(scenes: list[Scene], vo_lines: list[dict],
                        source_seconds: float) -> None:
    """Cut every scene to the exact length of its own narration line."""
    for scene, item in zip(scenes, vo_lines):
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


def draw_caption(text: str, zone: str, font_path: str | None, path: Path,
                 face=None) -> Path | None:
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

    # a tall block against a big face: shrink once rather than crowd him
    if face and block > (H * 0.34):
        size = int(size * 0.85)
        font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size)
        lines = wrap_caption(text.upper(), font, int(W * 0.88), draw)
        line_height = size * 1.22
        block = line_height * len(lines)

    top = place_caption(block, zone, face)

    for row, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        draw.text((W / 2 - width / 2, top + row * line_height), line, font=font,
                  fill=(255, 255, 255, 255), stroke_width=max(6, size // 12),
                  stroke_fill=(0, 0, 0, 255))
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
                  path: Path) -> tuple[Path, float]:
    """One subtitle card. Emphasis words come through in brand green."""
    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size)

    upper = [{"text": w["text"].upper(), "emph": w.get("emph")} for w in words]
    lines = measure_words(upper, font, draw, int(W * 0.84))
    line_height = size * 1.2
    space = draw.textlength(" ", font=font)
    stroke = max(6, size // 11)

    for row, line in enumerate(lines):
        total = sum(draw.textlength(w["text"], font=font) for w in line) + space * (len(line) - 1)
        x = W / 2 - total / 2
        y = top + row * line_height
        for word in line:
            draw.text((x, y), word["text"], font=font,
                      fill=EMPHASIS_GREEN if word["emph"] else (255, 255, 255, 255),
                      stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += draw.textlength(word["text"], font=font) + space
    canvas.save(path)
    return path, line_height * len(lines)


def subtitle_block_height(phrases, font_path: str | None, size: int) -> float:
    """Tallest card in the scene, so the band never jumps between cards."""
    from PIL import Image, ImageDraw, ImageFont

    probe_img = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(probe_img)
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size)
    tallest = 0.0
    for phrase in phrases:
        upper = [{"text": w["text"].upper(), "emph": w.get("emph")} for w in phrase["words"]]
        lines = measure_words(upper, font, draw, int(W * 0.84))
        tallest = max(tallest, size * 1.2 * len(lines))
    return tallest


def draw_cta_frame(text: str, font_path: str | None, path: Path,
                   watermark: Path | None = None) -> Path:
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

    if watermark:
        with Image.open(watermark) as plate:
            canvas = Image.alpha_composite(canvas.convert("RGBA"),
                                           plate.convert("RGBA")).convert("RGB")
    canvas.save(path)
    return path


# --------------------------------------------------------------------------
# stage 5: assembly
# --------------------------------------------------------------------------

def render_scene(scene: Scene, source: Path, src_w: int, src_h: int, src_has_audio: bool,
                 work: Path, font_path: str | None, watermark: Path | None,
                 destination: Path, phrases: list[dict] | None = None,
                 caption_mode: str = "subtitles") -> None:
    window = crop_window(src_w, src_h, scene.crop_x)
    crop_w, crop_h, x0, y0 = window
    parts = work / "parts"
    parts.mkdir(parents=True, exist_ok=True)

    annotation_png = draw_annotations(scene, src_w, src_h, window,
                                      parts / f"ann{scene.number:02d}.png")
    face = face_rect_in_frame(scene, src_w, src_h, window)

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
    if caption_mode in ("labels", "both"):
        caption_png = draw_caption(scene.caption, scene.caption_zone, font_path,
                                   parts / f"cap{scene.number:02d}.png", face)
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

    chain = [f"[0:v]crop={crop_w}:{crop_h}:{x0}:{y0},"
             f"scale={W}:{H}:flags=lanczos,setsar=1,fps={FPS}[base]"]
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


def render_cta(text: str, font_path: str | None, work: Path, watermark: Path | None,
               destination: Path) -> None:
    png = draw_cta_frame(text, font_path, work / "parts" / "cta.png", watermark)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-loop", "1", "-t", f"{CTA_SECONDS}", "-i", str(png),
         "-f", "lavfi", "-t", f"{CTA_SECONDS}", "-i", "anullsrc=r=48000:cl=stereo",
         "-vf", f"scale={W}:{H},setsar=1,fps={FPS},format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         "-video_track_timescale", "30000", str(destination)])


def mix_audio(body: Path, vo_lines: list[dict] | None, starts: list[float],
              whoosh_at: float | None, music: Path | None, destination: Path,
              location_level: float = 0.0) -> None:
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

    if vo_lines:
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


def stage_assemble(scenes: list[Scene], short: dict, source: Path,
                   vo_lines: list[dict] | None, work: Path, index: int, slug: str,
                   font_path: str | None, music: Path | None,
                   watermark: Path | None, caption_mode: str = "labels",
                   location_level: float = 0.0) -> tuple[Path, list[float]]:
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

    parts = work / "parts"
    if parts.exists():
        shutil.rmtree(parts)
    parts.mkdir(parents=True)

    clips, starts, elapsed = [], [], 0.0
    for position, scene in enumerate(scenes):
        clip = parts / f"scene{scene.number:02d}.mp4"
        say(f"scene {scene.number}: {stamp(scene.start)} to {stamp(scene.end)}, "
            f"crop_x {scene.crop_x:.2f}"
            f"{', punch in' if scene.punch_in else ''}"
            f"{', ' + str(len(scene.annotations)) + ' annotation(s)' if scene.annotations else ''}")
        phrases = (vo_lines[position]["phrases"] if vo_lines else None)
        render_scene(scene, source, src_w, src_h, src_audio, work, font_path,
                     watermark, clip, phrases, caption_mode)
        clips.append(clip)
        starts.append(elapsed)
        elapsed += media_duration(clip)

    cta_text = short.get("cta_frame") or short.get("cta", {}).get("primary") or "Follow for more"
    cta_clip = parts / "cta.mp4"
    render_cta(cta_text, font_path, work, watermark, cta_clip)
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
    mix_audio(body, vo_lines, starts, whoosh_at, music, final, location_level)
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
    parser.add_argument("--voice-id", default=None, help="ElevenLabs voice id for Mike")
    parser.add_argument("--model-id", default=ELEVEN_DEFAULT_MODEL)
    parser.add_argument("--captions", choices=["subtitles", "labels", "both"],
                        default="labels",
                        help="subtitles follow what Mike actually says, labels are the "
                             "guide's summary captions, both draws each in its own band")
    parser.add_argument("--location-audio", type=float, default=0.0,
                        help="level for the original clip audio, 0 mutes it, "
                             "0.03 is the old low bed under the VO")
    parser.add_argument("--line-gap", type=float, default=0.28,
                        help="pause held after each narration line, seconds, default 0.28")
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
    edits = stage_analyze(source, scenes, work, video_id, args.number, args.auto, rescan)
    apply_edits(scenes, edits)

    vo_lines = stage_vo(short, scenes, work, args.number, args.skip_vo, args.revoice,
                        args.voice_id, args.model_id, args.line_gap)

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
            watermark = build_watermark(logo, work / "watermark.png",
                                        args.logo_width, 40, 52, args.logo_opacity)
            from PIL import Image
            with Image.open(watermark) as plate:
                mark = plate.getchannel("A").getbbox()
            say(f"watermark: {logo.name}, top right, "
                f"{(mark[2] - mark[0]) if mark else 0}px wide")

    final, starts = stage_assemble(scenes, short, source, vo_lines, work, args.number,
                                   slug, font_path, music, watermark, args.captions,
                                   args.location_audio)
    sheet = stage_contact_sheet(final, scenes, starts, work, slug, args.number, font_path)
    pack, thumb = stage_publish_pack(final, guide, short, args.number, slug, starts)

    print("\nDone.")
    print(f"  Short:         {final.relative_to(REPO_ROOT)}")
    print(f"  Contact sheet: {sheet.relative_to(REPO_ROOT)}")
    print(f"  Thumbnail:     {thumb.relative_to(REPO_ROOT)}")
    print(f"  Publish pack:  {pack.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
