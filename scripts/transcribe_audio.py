#!/usr/bin/env python3
"""Transcribe a local media file with the ElevenLabs speech to text API.

    python scripts/transcribe_audio.py work/mountaineer-house/source.mp4

Writes transcripts/[stem].json in the same shape as fetch_transcript.py, plus a
words array with per word timings. Used when an episode is not on YouTube, or
has no captions, and nothing can be installed locally.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS = REPO_ROOT / "transcripts"
ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-text"


def stamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def extract_audio(source: Path, destination: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
                    "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(destination)],
                   check=True)
    return destination


def post_multipart(url: str, fields: dict, file_path: Path, api_key: str) -> dict:
    boundary = uuid.uuid4().hex
    body = bytearray()
    for key, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body += f"--{boundary}\r\n".encode()
    body += (f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
             f"Content-Type: {mime}\r\n\r\n").encode()
    body += file_path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()

    request = urllib.request.Request(url, data=bytes(body), headers={
        "xi-api-key": api_key,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    bundle = (os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
              or os.environ.get("CURL_CA_BUNDLE"))
    context = ssl.create_default_context(cafile=bundle) if bundle else ssl.create_default_context()
    with urllib.request.urlopen(request, context=context, timeout=900) as response:
        return json.loads(response.read())


def lines_from_words(words: list[dict], gap: float = 0.7, max_chars: int = 90) -> list[dict]:
    """Group words into readable transcript lines with timings."""
    lines, group = [], []

    def flush():
        if not group:
            return
        text = " ".join(w["text"] for w in group).strip()
        if not text:
            return
        lines.append({
            "index": len(lines),
            "start": round(group[0]["start"], 2),
            "end": round(group[-1]["end"], 2),
            "timestamp": stamp(group[0]["start"]),
            "range": f"{stamp(group[0]['start'])} - {stamp(group[-1]['end'])}",
            "text": text,
        })

    for word in words:
        if word.get("type") not in (None, "word"):
            continue
        if group:
            joined = " ".join(w["text"] for w in group)
            if (word["start"] - group[-1]["end"] > gap
                    or len(joined) >= max_chars
                    or group[-1]["text"].rstrip()[-1:] in ".!?"):
                flush()
                group = []
        group.append(word)
    flush()
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", type=Path, help="local video or audio file")
    parser.add_argument("--model-id", default="scribe_v1")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.media.exists():
        sys.exit(f"file not found: {args.media}")

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("ELEVENLABS_API_KEY is not set")

    destination = TRANSCRIPTS / f"{args.media.parent.name}.json"
    if destination.exists() and not args.force:
        print(f"Transcript already cached: {destination}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        audio = extract_audio(args.media, Path(tmp) / "audio.mp3")
        size = audio.stat().st_size / 1e6
        print(f"Sending {size:.1f} MB to ElevenLabs speech to text ({args.model_id})...",
              file=sys.stderr)
        payload = post_multipart(ENDPOINT, {"model_id": args.model_id,
                                            "timestamps_granularity": "word",
                                            "diarize": "false"}, audio, api_key)

    words = [w for w in payload.get("words", []) if w.get("type") in (None, "word")]
    lines = lines_from_words(payload.get("words", []))
    out = {
        "video_id": args.media.parent.name,
        "source": "elevenlabs-speech-to-text",
        "language": payload.get("language_code", "en"),
        "media": str(args.media),
        "duration": round(words[-1]["end"], 2) if words else 0,
        "line_count": len(lines),
        "lines": lines,
        "words": [{"text": w["text"], "start": round(w["start"], 3),
                   "end": round(w["end"], 3)} for w in words],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Transcript: {destination}")
    print(f"{len(lines)} lines, {len(words)} words, runtime {stamp(out['duration'])}")


if __name__ == "__main__":
    main()
