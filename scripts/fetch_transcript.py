#!/usr/bin/env python3
"""Fetch a timestamped transcript for a YouTube episode.

Usage:
    python scripts/fetch_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID"

Primary path: youtube-transcript-api pulls the published captions.
Fallback: if the video has no captions, yt-dlp downloads the audio and
faster-whisper transcribes it with timestamps.

Either way the result is written to transcripts/[video_id].json:

    {
      "video_id": "...",
      "url": "...",
      "source": "youtube-captions" | "faster-whisper",
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
import json
import re
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


def whisper_fallback(video_id: str, url: str, model_size: str) -> tuple[list[dict], str]:
    """Download audio with yt-dlp, transcribe with faster-whisper."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit(
            "Captions unavailable and faster-whisper is not installed.\n"
            "Install the fallback with: pip install -r requirements.txt"
        )

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
    args = parser.parse_args()

    video_id = extract_video_id(args.url)
    url = args.url if args.url.startswith("http") else f"https://www.youtube.com/watch?v={video_id}"
    destination = TRANSCRIPT_DIR / f"{video_id}.json"

    if destination.exists() and not args.force:
        print(f"Transcript already cached: {destination}")
        print("Rerun with --force to refetch.")
        return

    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]

    result = fetch_captions(video_id, languages)
    if result is not None:
        raw, language = result
        source = "youtube-captions"
    else:
        raw, language = whisper_fallback(video_id, url, args.whisper_model)
        source = "faster-whisper"

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
