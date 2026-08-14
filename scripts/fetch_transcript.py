#!/usr/bin/env python3
"""Fetch a timestamped transcript for a YouTube episode.

Usage:
    python scripts/fetch_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID"

Three tiers, cheapest first:

  1. youtube-transcript-api, fast, no download
  2. yt-dlp subtitles, json3 or vtt, published track preferred over auto.
     This is the tier that works from a cloud container, where the caption
     API is usually blocked by IP
  3. faster-whisper on the downloaded audio, only when a video truly has no
     captions. Installed on demand, it is not in requirements.txt

Either way the result is written to transcripts/[video_id].json:

    {
      "video_id": "...",
      "url": "...",
      "source": "youtube-captions" | "yt-dlp-subtitles" | "faster-whisper",
      "language": "en",
      "duration": 1042.5,
      "lines": [
        {"index": 0, "start": 0.0, "end": 4.2, "timestamp": "0:00",
         "range": "0:00 - 0:04", "text": "..."}
      ]
    }
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT_DIR = REPO_ROOT / "transcripts"

VIDEO_ID_PATTERNS = [
    r"(?:v=|/v/|/embed/|/shorts/|youtu\.be/|/live/)([0-9A-Za-z_-]{11})",
    r"^([0-9A-Za-z_-]{11})$",
]


def extract_video_id(url: str) -> str:
    for pattern in VIDEO_ID_PATTERNS:
        match = re.search(pattern, url.strip())
        if match:
            return match.group(1)
    sys.exit(f"Could not find a video id in: {url}")


def stamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def build_lines(raw: list[dict]) -> list[dict]:
    """raw entries carry start, duration (or end), and text."""
    lines = []
    for index, entry in enumerate(raw):
        text = " ".join(str(entry.get("text", "")).split())
        if not text:
            continue
        start = float(entry.get("start", 0.0))
        if entry.get("end") is not None:
            end = float(entry["end"])
        else:
            end = start + float(entry.get("duration", 0.0))
        lines.append({
            "index": index,
            "start": round(start, 2),
            "end": round(end, 2),
            "timestamp": stamp(start),
            "range": f"{stamp(start)} - {stamp(end)}",
            "text": text,
        })
    return lines


def fetch_captions(video_id: str, languages: list[str]) -> tuple[list[dict], str] | None:
    """Try youtube-transcript-api across its 1.x and 0.6.x interfaces."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("youtube-transcript-api is not installed, skipping caption fetch",
              file=sys.stderr)
        return None

    try:
        # youtube-transcript-api >= 1.0
        if hasattr(YouTubeTranscriptApi, "fetch") or not hasattr(
            YouTubeTranscriptApi, "get_transcript"
        ):
            api = YouTubeTranscriptApi()
            fetched = api.fetch(video_id, languages=languages)
            language = getattr(fetched, "language_code", languages[0])
            raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
            return raw, language
        # youtube-transcript-api 0.6.x
        raw = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        return raw, languages[0]
    except Exception as exc:  # noqa: BLE001, the library raises many shapes
        print(f"No usable captions ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None


def parse_json3(path: Path) -> list[dict]:
    """YouTube json3 subtitles into raw start/end/text entries."""
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = []
    for event in data.get("events", []):
        segments = event.get("segs")
        if not segments:
            continue
        text = " ".join("".join(s.get("utf8", "") for s in segments).split())
        if not text:
            continue
        start = float(event.get("tStartMs", 0)) / 1000.0
        duration = float(event.get("dDurationMs", 0)) / 1000.0
        if raw and raw[-1]["text"] == text:
            continue
        raw.append({"start": start, "end": start + duration, "text": text})
    return raw


def parse_vtt(path: Path) -> list[dict]:
    """WebVTT into raw start/end/text entries, used when json3 is unavailable."""
    raw = []
    start = end = None
    buffer: list[str] = []

    def flush():
        if start is None:
            return
        text = " ".join(" ".join(buffer).split())
        text = re.sub(r"<[^>]+>", "", text)
        if text and not (raw and raw[-1]["text"] == text):
            raw.append({"start": start, "end": end, "text": text})

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "-->" in line:
            flush()
            buffer = []
            head, _, tail = line.partition("-->")
            start = to_seconds_clock(head.strip())
            end = to_seconds_clock(tail.strip().split()[0] if tail.strip() else "")
        elif line.strip() and not line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            buffer.append(line.strip())
        elif not line.strip():
            flush()
            buffer = []
            start = end = None
    flush()
    return raw


def to_seconds_clock(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    seconds = 0.0
    try:
        for part in parts:
            seconds = seconds * 60 + float(part)
    except ValueError:
        return 0.0
    return seconds


def fetch_ytdlp_subs(video_id: str, url: str, languages: list[str]) -> tuple[list[dict], str] | None:
    """Pull published or auto-generated subtitles with yt-dlp.

    This is the tier that works from a cloud container, where the caption API
    is usually blocked by IP.
    """
    if shutil.which("yt-dlp") is None:
        return None

    with tempfile.TemporaryDirectory() as tmp:
        wanted = ",".join([lang for lang in languages] + [f"{lang}.*" for lang in languages])
        result = subprocess.run(
            ["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
             "--sub-langs", wanted, "--sub-format", "json3/vtt/best",
             "--no-warnings", "-o", str(Path(tmp) / "%(id)s.%(ext)s"), url],
            capture_output=True, text=True,
        )
        files = sorted(Path(tmp).glob(f"{video_id}.*"))
        if not files:
            detail = (result.stderr or "").strip().splitlines()[-1:] or ["no subtitle tracks"]
            print(f"yt-dlp found no subtitles ({detail[0]})", file=sys.stderr)
            return None

        def rank(path: Path) -> tuple:
            stem = path.stem.lower()
            # Prefer a published track over an auto one, and json3 over vtt.
            return ("orig" in stem or "auto" in stem, path.suffix != ".json3", len(stem))

        for path in sorted(files, key=rank):
            raw = parse_json3(path) if path.suffix == ".json3" else parse_vtt(path)
            if raw:
                language = path.stem.split(".")[-1] if "." in path.stem else languages[0]
                print(f"Using subtitles from {path.name}", file=sys.stderr)
                return raw, language
    return None


def ensure_faster_whisper(auto_install: bool) -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        pass
    if not auto_install:
        return False
    print("Installing faster-whisper on demand, this takes a minute...", file=sys.stderr)
    result = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "faster-whisper"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print((result.stderr or "").strip()[-400:], file=sys.stderr)
        return False
    importlib.invalidate_caches()
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def whisper_fallback(video_id: str, url: str, model_size: str,
                     auto_install: bool = True) -> tuple[list[dict], str]:
    """Download audio with yt-dlp, transcribe with faster-whisper."""
    if not ensure_faster_whisper(auto_install):
        sys.exit(
            "No captions anywhere and faster-whisper could not be installed.\n"
            "Install it yourself with: pip install -r requirements-whisper.txt"
        )
    from faster_whisper import WhisperModel

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{video_id}.m4a"
        print("No captions found, downloading audio with yt-dlp...", file=sys.stderr)
        result = subprocess.run(
            ["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "m4a",
             "-o", str(Path(tmp) / f"{video_id}.%(ext)s"), url],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            sys.exit(f"yt-dlp failed:\n{result.stderr.strip()}")
        if not audio.exists():
            candidates = sorted(Path(tmp).glob(f"{video_id}.*"))
            if not candidates:
                sys.exit("yt-dlp produced no audio file")
            audio = candidates[0]

        print(f"Transcribing with faster-whisper ({model_size})...", file=sys.stderr)
        model = WhisperModel(model_size, device="auto", compute_type="int8")
        segments, info = model.transcribe(str(audio), vad_filter=True)
        raw = [
            {"start": seg.start, "end": seg.end, "text": seg.text}
            for seg in segments
        ]
        return raw, getattr(info, "language", "en")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="YouTube URL or bare 11 character video id")
    parser.add_argument("--languages", default="en",
                        help="comma separated caption language preference, default en")
    parser.add_argument("--whisper-model", default="base",
                        help="faster-whisper model size for the fallback, default base")
    parser.add_argument("--force", action="store_true",
                        help="refetch even if the transcript JSON already exists")
    parser.add_argument("--no-auto-install", action="store_true",
                        help="do not pip install faster-whisper when the last tier is reached")
    args = parser.parse_args()

    video_id = extract_video_id(args.url)
    url = args.url if args.url.startswith("http") else f"https://www.youtube.com/watch?v={video_id}"
    destination = TRANSCRIPT_DIR / f"{video_id}.json"

    if destination.exists() and not args.force:
        print(f"Transcript already cached: {destination}")
        print("Rerun with --force to refetch.")
        return

    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]

    # Three tiers, cheapest first. The caption API is fast but is commonly
    # blocked by IP from cloud containers, where yt-dlp still works.
    source = "youtube-captions"
    result = fetch_captions(video_id, languages)
    if result is None:
        result = fetch_ytdlp_subs(video_id, url, languages)
        source = "yt-dlp-subtitles"
    if result is None:
        result = whisper_fallback(video_id, url, args.whisper_model,
                                  auto_install=not args.no_auto_install)
        source = "faster-whisper"
    raw, language = result

    lines = build_lines(raw)
    if not lines:
        sys.exit("Transcript came back empty, nothing to write")

    payload = {
        "video_id": video_id,
        "url": url,
        "source": source,
        "language": language,
        "duration": lines[-1]["end"],
        "line_count": len(lines),
        "lines": lines,
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    print(f"Transcript: {destination}")
    print(f"Source: {source}, lines: {len(lines)}, "
          f"runtime: {stamp(payload['duration'])}")


if __name__ == "__main__":
    main()
