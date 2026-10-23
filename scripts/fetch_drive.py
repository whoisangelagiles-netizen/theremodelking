#!/usr/bin/env python3
"""Download Google Drive files shared as "anyone with the link" into a work folder.

    python scripts/fetch_drive.py work/east-bench-phase-3 pre/01.jpg=1X-S3H8Y... final/IMG-0896.mov=1kV9...
    python scripts/fetch_drive.py --audio work/east-bench-phase-3/east-bench-phase-3-body/audio.m4a <body file id>

Each argument is local/path=FILE_ID, relative to the folder given first. Files
already on disk are skipped, so a rerun only fetches what is missing.

--audio streams a video and keeps only its audio track, which is how the long
body video gets transcribed without putting gigabytes of picture on disk.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

URL = "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t"


def fetch(destination: Path, file_id: str) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        print(f"  have {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    subprocess.run(["curl", "-sS", "-L", "--fail", "--retry", "4", "-o", str(partial),
                    URL.format(id=file_id)], check=True)
    if partial.read_bytes()[:15].lower().startswith(b"<!doctype html"):
        partial.unlink()
        sys.exit(f"{destination.name}: Drive sent a web page, not the file. Share it as "
                 "anyone with the link and try again.")
    partial.rename(destination)
    print(f"  got  {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio", type=Path, help="stream one video, keep only its audio here")
    parser.add_argument("target", help="work folder, or the file id with --audio")
    parser.add_argument("files", nargs="*", help="local/path=FILE_ID")
    args = parser.parse_args()

    if args.audio:
        args.audio.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-i", URL.format(id=args.target), "-map", "0:a:0", "-c:a", "copy",
                        str(args.audio)], check=True)
        print(f"  got  {args.audio}")
        return

    root = Path(args.target)
    for item in args.files:
        local, _, file_id = item.partition("=")
        if not file_id:
            sys.exit(f"expected local/path=FILE_ID, got {item}")
        fetch(root / local, file_id)


if __name__ == "__main__":
    main()
