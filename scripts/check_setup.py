#!/usr/bin/env python3
"""Check that everything the finishing pipeline needs is actually in place.

    python scripts/check_setup.py
    python scripts/check_setup.py --list-voices     # print your ElevenLabs voices and ids

Prints one line per check. READY means you can build a Short. Warnings are
things that degrade gracefully, the build still runs without them.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "assets"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

OK, WARN, FAIL = "  ok  ", " warn ", " FAIL "
blocking = 0
warnings = 0


def line(status: str, label: str, detail: str = "") -> None:
    global blocking, warnings
    if status == FAIL:
        blocking += 1
    elif status == WARN:
        warnings += 1
    print(f"[{status}] {label}" + (f"  {detail}" if detail else ""))


def heading(text: str) -> None:
    print(f"\n{text}\n" + "-" * len(text))


def ssl_context() -> ssl.SSLContext:
    bundle = (os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
              or os.environ.get("CURL_CA_BUNDLE"))
    return ssl.create_default_context(cafile=bundle) if bundle else ssl.create_default_context()


def eleven_get(path: str, api_key: str) -> dict | None:
    request = urllib.request.Request(f"https://api.elevenlabs.io{path}",
                                     headers={"xi-api-key": api_key})
    try:
        with urllib.request.urlopen(request, context=ssl_context(), timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return {"_error": f"HTTP {exc.code}", "_body": exc.read()[:200].decode("utf-8", "replace")}
    except Exception as exc:  # noqa: BLE001
        return {"_error": f"{type(exc).__name__}: {exc}"}


def check_tools() -> None:
    heading("Tools")
    for binary, why in [("ffmpeg", "cutting and encoding"),
                        ("ffprobe", "reading media"),
                        ("yt-dlp", "downloading the source video")]:
        path = shutil.which(binary)
        line(OK if path else FAIL, binary, path or f"missing, needed for {why}")

    modules = [("PIL", "captions, annotations, watermark", True),
               ("jinja2", "guide PDF", True),
               ("weasyprint", "guide PDF", True),
               ("youtube_transcript_api", "transcript fetch", True),
               ("yt_dlp", "source download", True),
               ("faster_whisper", "last resort transcription, installed on demand", False)]
    for name, why, required in modules:
        try:
            __import__(name)
            line(OK, name)
        except ImportError:
            if name == "faster_whisper":
                line(WARN, name, "not installed, and usually never needed. yt-dlp subtitles "
                                 "cover videos the caption API cannot reach. It installs "
                                 "itself if a video truly has no captions.")
            else:
                line(FAIL if required else WARN, name,
                     f"not installed, needed for {why}. pip install -r requirements.txt")


def image_content_width(path: Path) -> int:
    from PIL import Image
    with Image.open(path) as image:
        if "A" in image.getbands():
            box = image.getchannel("A").getbbox()
            if box:
                return box[2] - box[0]
        return image.width


def check_assets() -> None:
    heading("Assets")

    try:
        from build_short import find_logo
        logo = find_logo(None)
    except ImportError:
        logo = next((p for p in (ASSETS / "logo.png",) if p.exists()), None)
    if logo is None:
        line(WARN, "logo watermark", "no logo in assets/, Shorts build without a watermark")
    else:
        try:
            from PIL import Image
            with Image.open(logo) as image:
                has_alpha = "A" in image.getbands() or image.mode == "P"
                detail = f"{logo.name}, {image.width}x{image.height}"
            if not has_alpha:
                line(WARN, "logo watermark", detail + ", no transparency, it will show a "
                                                     "solid rectangle. Export a PNG with alpha.")
            elif image_content_width(logo) < 260:
                line(OK, "logo watermark",
                     detail + f", the mark is {image_content_width(logo)}px wide inside the "
                              "file so it renders at native size rather than the full 16 "
                              "percent. A 600px export would let it sit larger.")
            else:
                line(OK, "logo watermark", detail)
        except Exception as exc:  # noqa: BLE001
            line(FAIL, "logo watermark", f"{logo.name} cannot be opened, {exc}")

    for name, label, effect in [
        ("whoosh", "whoosh sound", "transitions play clean"),
        ("impact", "impact sound", "the hook lands with no hit"),
        ("music", "music bed", "no music under the VO"),
    ]:
        found = sorted(p for p in ASSETS.glob(f"{name}.*") if p.suffix.lower()
                       in {".wav", ".mp3", ".m4a", ".aac"})
        line(OK if found else WARN, label,
             found[0].name if found else f"missing, {effect}")

    overlays = sorted((ASSETS / "overlays").glob("*.mov")) if (ASSETS / "overlays").exists() else []
    line(OK if overlays else WARN, "branded overlays",
         ", ".join(p.name for p in overlays) if overlays
         else "none, optional, only needed if a guide names one per scene")


def check_elevenlabs(list_voices: bool) -> None:
    heading("ElevenLabs")

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID")

    if not api_key:
        line(FAIL, "ELEVENLABS_API_KEY", "not set in this environment")
        return
    line(OK, "ELEVENLABS_API_KEY", f"set, ends with {api_key[-4:]}")

    user = eleven_get("/v1/user", api_key)
    if user is None or "_error" in user:
        detail = (user or {}).get("_error", "no response")
        if "401" in str(detail):
            detail += ", the key is not valid"
        line(FAIL, "key works", detail)
        return

    subscription = user.get("subscription") or {}
    used = subscription.get("character_count")
    cap = subscription.get("character_limit")
    tier = subscription.get("tier", "unknown")
    budget = f"{cap - used:,} characters left of {cap:,}" if isinstance(used, int) and isinstance(cap, int) else ""
    line(OK, "key works", f"{tier} plan, {budget}")

    voices = eleven_get("/v1/voices", api_key) or {}
    catalogue = voices.get("voices") or []
    if "_error" in voices:
        line(WARN, "voice list", voices["_error"])
        catalogue = []

    if list_voices and catalogue:
        print("\n  Your voices:")
        for voice in catalogue:
            print(f"    {voice.get('voice_id')}  {voice.get('name')}"
                  f"  ({voice.get('category', 'n/a')})")
        print()

    if not voice_id:
        line(FAIL, "ELEVENLABS_VOICE_ID", "not set. Run with --list-voices and pick Mike's voice")
        return

    match = next((v for v in catalogue if v.get("voice_id") == voice_id), None)
    if match:
        line(OK, "ELEVENLABS_VOICE_ID", f"{match.get('name')} ({match.get('category', 'n/a')})")
    elif catalogue:
        line(FAIL, "ELEVENLABS_VOICE_ID",
             f"{voice_id} is not in your voice list. Run with --list-voices")
    else:
        line(WARN, "ELEVENLABS_VOICE_ID", f"{voice_id}, could not verify against your account")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list-voices", action="store_true",
                        help="print every voice on the account with its id")
    args = parser.parse_args()

    try:
        from build_short import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    check_tools()
    check_assets()
    check_elevenlabs(args.list_voices)

    print()
    if blocking:
        print(f"NOT READY, {blocking} blocking issue(s) above"
              + (f", {warnings} warning(s)" if warnings else ""))
        sys.exit(1)
    print("READY to build a Short"
          + (f", {warnings} optional item(s) missing, they degrade gracefully" if warnings else ""))


if __name__ == "__main__":
    main()
