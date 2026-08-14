#!/usr/bin/env bash
# Setup script for a Claude Code cloud environment.
#
# Paste the contents of this file into the Setup script box in the cloud
# environment dialog at claude.ai/code, so every new session starts with the
# tools this pipeline needs. Installing by name rather than from
# requirements.txt keeps it working no matter where the script runs from.
#
# faster-whisper is deliberately left out. It is only needed when a video has
# no captions at all, and it is heavy enough to slow every session start.
# Install it on demand with: pip install -r requirements-whisper.txt

set -u

if ! command -v ffmpeg >/dev/null 2>&1; then
  (apt-get update -qq && apt-get install -y -qq ffmpeg) 2>/dev/null \
    || sudo apt-get install -y ffmpeg \
    || echo "could not install ffmpeg, the finishing pipeline will not run"
fi

pip install -q weasyprint Jinja2 Pillow youtube-transcript-api yt-dlp || true

command -v ffmpeg >/dev/null 2>&1 && echo "ffmpeg ready"
command -v yt-dlp  >/dev/null 2>&1 && echo "yt-dlp ready"
