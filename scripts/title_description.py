#!/usr/bin/env python3
"""The YouTube title and description for a Short, as one copy-paste block.

    python scripts/title_description.py guides/<slug>.json [short number]

Reads the Short's `yt_title` and `yt_description` from the guide, adds the CTA,
the full episode link, the Home Depot boilerplate and the hashtags, checks the
hard rules, and writes output/[slug]-short-[n]-title-description.md. The build
runs the same thing at the end, so a finished Short always ships with one.

The spec lives in .claude/skills/shorts-production-guide/title-and-description.md.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "output"

REQUIRED_TAGS = ["#FirstFlipChallenge", "#InvestorSecretNetwork"]

BOILERPLATE = """👉👉👉 SHOP THE PRODUCTS USED IN THIS PROJECT:

The Remodel King Home Depot Storefront
https://creators.homedepot.com/mypage/theremodelking

You'll find products featured in our remodeling projects, including:

- Bathroom fixtures
- Lighting products
- Flooring materials
- Tile products
- Door hardware
- Storage solutions
- And more

Be sure to like and subscribe to our YouTube channel for more shorts just like this.

Affiliate Disclaimer: As a Home Depot Creator, The Remodel King may earn a commission from qualifying purchases made through the links above. This helps support the channel at no additional cost to you."""

CTA = ("Want to see the full {subject} before and after and find out what it cost? "
       "Watch the full transformation here:\n{url}")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def problems(title: str, description: str, hook: str) -> list[str]:
    found = []
    for name, text in (("title", title), ("description", description)):
        if "—" in text or "–" in text:
            found.append(f"{name} has a dash Mike does not use, write it out")
        if "•" in text:
            found.append(f"{name} has a bullet character, YouTube strips it, use '- '")
        if re.search(r"\$\s?\d|\d[\d,.]*\s?(k\b|grand\b|dollars\b)", text, re.I):
            found.append(f"{name} names a cost, the full video delivers that")
        if "follow for more" in text.lower():
            found.append(f"{name} uses the retired follow for more CTA")
    front = title.split("|")[0].strip()
    if "|" not in title:
        found.append("title needs the form 'hook | longtail keywords'")
    elif hook and front.lower().rstrip(".") != hook.lower().strip().rstrip("."):
        found.append(f"title front half '{front}' does not match the cover hook '{hook}'")
    return found


def build_block(guide: dict, short: dict) -> tuple[str, list[str]]:
    """The finished block plus any rule it breaks."""
    title = " ".join(str(short.get("yt_title") or "").split())
    parts = short.get("yt_description") or {}
    url = guide.get("video_url", "")
    missing = [k for k in ("hook", "project", "features", "subject") if not parts.get(k)]
    missing += [] if title else ["yt_title"]
    missing += [] if url else ["video_url"]
    tags = list(dict.fromkeys(list(guide.get("hashtags") or []) + REQUIRED_TAGS))
    description = "\n\n".join([
        parts.get("hook", "").strip(),
        parts.get("project", "").strip(),
        parts.get("features", "").strip(),
        CTA.format(subject=parts.get("subject", "").strip(), url=url),
        BOILERPLATE,
        " ".join(tags),
    ])
    block = f"**Title**\n{title}\n\n**Description**\n\n{description}\n"
    issues = [f"missing {m}" for m in missing]
    issues += problems(title, "\n".join(str(parts.get(k, "")) for k in ("hook", "project", "features")),
                       str(short.get("cover_hook") or ""))
    return block, issues


def write_block(guide: dict, short: dict, slug: str, index: int) -> tuple[Path, list[str]]:
    block, issues = build_block(guide, short)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / f"{slug}-short-{index}-title-description.md"
    path.write_text(block, encoding="utf-8")
    return path, issues


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    guide_path = Path(sys.argv[1])
    index = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    guide = json.loads(guide_path.read_text(encoding="utf-8"))
    short = guide["shorts"][index - 1]
    slug = slugify(guide.get("episode") or guide_path.stem)
    path, issues = write_block(guide, short, slug, index)
    print(path.read_text(encoding="utf-8"))
    print(f"written to {path.relative_to(REPO_ROOT)}", file=sys.stderr)
    for issue in issues:
        print(f"FIX: {issue}", file=sys.stderr)
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
