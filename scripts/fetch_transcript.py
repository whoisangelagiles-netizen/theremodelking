#!/usr/bin/env python3
"""Fetch a timestamped transcript for a YouTube episode.

Usage:
    python scripts/fetch_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID"

Whisper first, by default. YouTube's auto captions arrive with no punctuation
and mangle trade words, and the script is only as good as the transcript under
it, so the extra minute of transcription is worth it.

  1. faster-whisper on the audio. Reads a local master with --source, otherwise
     pulls the audio with yt-dlp. Gives punctuation, sentence boundaries, and
     word level timings
  2. youtube-transcript-api, fast, no download
  3. yt-dlp subtitles, json3 or vtt, published track preferred over auto

--captions-first flips the order back to the caption tiers, for a quick scan
where transcript quality does not matter.

Either way the result is written to transcripts/[video_id].json:

    {
      "video_id": "...",
      "url": "...",
      "source": "faster-whisper" | "youtube-captions" | "yt-dlp-subtitles",
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
    # Episodes that are not on YouTube are keyed by a slug instead, so a local
    # master still gets a transcript filed under a stable name.
    slug = re.sub(r"[^a-z0-9]+", "-", url.strip().lower()).strip("-")
    if slug:
        return slug
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
        line = {
            "index": index,
            "start": round(start, 2),
            "end": round(end, 2),
            "timestamp": stamp(start),
            "range": f"{stamp(start)} - {stamp(end)}",
            "text": text,
        }
        if entry.get("words"):
            line["words"] = entry["words"]
        lines.append(line)
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


def fetch_ytdlp_subs(video_id: str, url: str, languages: list[str],
                     cookies: Path | None = None) -> tuple[list[dict], str] | None:
    """Pull published or auto-generated subtitles with yt-dlp.

    This is the tier that works from a cloud container, where the caption API
    is usually blocked by IP.
    """
    if shutil.which("yt-dlp") is None:
        return None

    with tempfile.TemporaryDirectory() as tmp:
        wanted = ",".join([lang for lang in languages] + [f"{lang}.*" for lang in languages])
        cmd = ["yt-dlp", "--skip-download", "--ignore-no-formats-error",
               "--write-subs", "--write-auto-subs",
               "--sub-langs", wanted, "--sub-format", "json3/vtt/best",
               "--no-warnings", "-o", str(Path(tmp) / "%(id)s.%(ext)s")]
        if cookies:
            cmd += ["--cookies", str(cookies)]
        result = subprocess.run(cmd + [url], capture_output=True, text=True)
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


def whisper_transcribe(video_id: str, url: str, model_size: str,
                       local_source: Path | None = None,
                       auto_install: bool = True) -> tuple[list[dict], str] | None:
    """Transcribe with faster-whisper, from a local master if we have one.

    This is the default tier, not a fallback. Auto captions have no punctuation
    and no sentence boundaries, and every guide written from them inherits that.
    Returns None if the audio cannot be got hold of, so the caption tiers can try.
    """
    if not ensure_faster_whisper(auto_install):
        print("faster-whisper unavailable, falling back to the caption tiers",
              file=sys.stderr)
        return None
    from faster_whisper import WhisperModel

    with tempfile.TemporaryDirectory() as tmp:
        if local_source and Path(local_source).exists():
            audio = Path(tmp) / f"{video_id}.wav"
            print(f"Extracting audio from {local_source}...", file=sys.stderr)
            extract = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(local_source),
                 "-vn", "-ac", "1", "-ar", "16000", str(audio)],
                capture_output=True, text=True,
            )
            if extract.returncode != 0 or not audio.exists():
                print(f"ffmpeg could not pull the audio:\n{extract.stderr.strip()}",
                      file=sys.stderr)
                return None
        else:
            audio = Path(tmp) / f"{video_id}.m4a"
            print("Downloading audio with yt-dlp for transcription...", file=sys.stderr)
            result = subprocess.run(
                ["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "m4a",
                 "-o", str(Path(tmp) / f"{video_id}.%(ext)s"), url],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(f"yt-dlp could not fetch the audio:\n{result.stderr.strip()}",
                      file=sys.stderr)
                return None
            if not audio.exists():
                candidates = sorted(Path(tmp).glob(f"{video_id}.*"))
                if not candidates:
                    return None
                audio = candidates[0]

        print(f"Transcribing with faster-whisper ({model_size})...", file=sys.stderr)
        model = WhisperModel(model_size, device="auto", compute_type="int8")
        segments, info = model.transcribe(str(audio), vad_filter=True,
                                          word_timestamps=True)
        raw = []
        for seg in segments:
            words = [{"word": w.word.strip(), "start": round(w.start, 3),
                      "end": round(w.end, 3)} for w in (seg.words or [])]
            raw.append({"start": seg.start, "end": seg.end, "text": seg.text,
                        "words": words})
        return raw, getattr(info, "language", "en")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="YouTube URL or bare 11 character video id")
    parser.add_argument("--languages", default="en",
                        help="comma separated caption language preference, default en")
    parser.add_argument("--whisper-model", default="small",
                        help="faster-whisper model size, default small. medium is "
                             "slower and noticeably better on trade vocabulary")
    parser.add_argument("--source", type=Path, default=None,
                        help="local master to transcribe instead of downloading audio")
    parser.add_argument("--captions-first", action="store_true",
                        help="try YouTube captions before whisper, faster but the text "
                             "arrives with no punctuation")
    parser.add_argument("--force", action="store_true",
                        help="refetch even if the transcript JSON already exists")
    parser.add_argument("--cookies", type=Path, default=None,
                        help="cookies.txt for yt-dlp, needed when YouTube challenges the IP")
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
    cookies = args.cookies if args.cookies and args.cookies.exists() else None
    if cookies is None and (REPO_ROOT / "cookies.txt").exists():
        cookies = REPO_ROOT / "cookies.txt"

    # Whisper first. It costs a minute and it is the only tier that returns
    # punctuation, sentence boundaries, and word timings, which is what a guide
    # is actually written from. The caption tiers are the fallback.
    result, source = None, "faster-whisper"
    if not args.captions_first:
        result = whisper_transcribe(video_id, url, args.whisper_model, args.source,
                                    auto_install=not args.no_auto_install)
    if result is None:
        result = fetch_captions(video_id, languages)
        source = "youtube-captions"
    if result is None:
        result = fetch_ytdlp_subs(video_id, url, languages, cookies)
        source = "yt-dlp-subtitles"
    if result is None and args.captions_first:
        result = whisper_transcribe(video_id, url, args.whisper_model, args.source,
                                    auto_install=not args.no_auto_install)
        source = "faster-whisper"
    if result is None:
        sys.exit("No transcript from any tier: whisper could not get the audio and "
                 "the video has no captions. Pass --source with a local master.")
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
