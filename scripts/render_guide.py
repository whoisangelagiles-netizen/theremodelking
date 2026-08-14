#!/usr/bin/env python3
"""Render an Editor Handoff Production Guide JSON into a branded PDF.

Usage:
    python scripts/render_guide.py guides/kitchen-gut-reno.json
    python scripts/render_guide.py guides/kitchen-gut-reno.json -o output/custom.pdf

The JSON shape is documented in guides/example.schema.json. Anything omitted
from the top level falls back to the defaults below, so a guide only needs to
carry the episode specific content.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / ".claude" / "skills" / "shorts-production-guide" / "template.html"
OUTPUT_DIR = REPO_ROOT / "output"

DEFAULT_CHANNEL = "The Remodel King"

DEFAULT_PRODUCTION_NOTES = [
    "Export 1080x1920, 9:16 vertical, for every Short.",
    "Captions are bold white with a black outline, always burned in.",
    "Hook text sits in the upper third so it clears the UI and lands fast.",
    "Supporting captions sit in the lower third.",
    "Every cut plays over pre-demo walkthrough, progress state, or final "
    "reveal footage. No footage of demo or installation happening, and no "
    "workers on camera.",
    "Punch-ins, arrows, and highlight boxes are used to point at detail, "
    "never to fake motion.",
    "Whoosh transitions on reveals, impact sound on the payoff beat.",
    "Cost figures are handled by Mike's manually built end slides, not in the "
    "VO or captions.",
]

DEFAULT_CHECKLIST = [
    "Hook lands within 2 seconds",
    "VO recorded",
    "Captions burned in",
    "Thumbnail set",
    "SEO title applied",
    "Description written with full video link",
    "Pinned comment posted",
    "Hashtags added",
]


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "production-guide"


def load_guide(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        guide = json.load(fh)

    guide.setdefault("channel", DEFAULT_CHANNEL)
    guide.setdefault("date", date.today().strftime("%B %-d, %Y"))
    guide.setdefault("episode", path.stem.replace("-", " ").title())
    guide.setdefault("video_url", "")
    guide.setdefault("prepared_for", "")
    guide.setdefault("production_notes", DEFAULT_PRODUCTION_NOTES)
    guide.setdefault("checklist", DEFAULT_CHECKLIST)
    guide.setdefault("shorts", [])

    context = guide.setdefault("project_context", {})
    context.setdefault("summary", "")
    context.setdefault("segment_choice", "")
    context.setdefault("publish_order", "")
    context.setdefault("notes", [])

    for short in guide["shorts"]:
        short.setdefault("format", "9:16 vertical, 1080x1920")
        short.setdefault("seo_titles", [])
        short.setdefault("scenes", [])
        short.setdefault("voice_direction", "")
        cta = short.setdefault("cta", {})
        cta.setdefault("primary", "")
        cta.setdefault("alt", "")
        cta.setdefault("pinned", "")

    check_house_rules(guide)
    return guide


def check_house_rules(guide: dict) -> None:
    """Warn on em dashes, the one formatting rule a renderer can police."""
    offenders = []

    def walk(node, trail):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{trail}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{trail}[{index}]")
        elif isinstance(node, str) and ("—" in node or "–" in node):
            offenders.append(trail)

    walk(guide, "guide")
    for trail in offenders:
        print(f"WARNING: em or en dash found at {trail}, house style forbids it",
              file=sys.stderr)


def render(guide: dict, destination: Path) -> Path:
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover
        sys.exit(
            f"Missing dependency: {exc.name}. Install with:\n"
            "    pip install -r requirements.txt"
        )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE.parent)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(TEMPLATE.name)
    html = template.render(**guide)

    destination.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(TEMPLATE.parent)).write_pdf(str(destination))
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("guide", type=Path, help="path to the guide JSON")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="destination PDF, defaults to output/[slug]-production-guide.pdf")
    parser.add_argument("--html", type=Path, default=None,
                        help="also write the rendered HTML here, useful for debugging")
    args = parser.parse_args()

    if not args.guide.exists():
        sys.exit(f"Guide JSON not found: {args.guide}")

    guide = load_guide(args.guide)

    destination = args.output or OUTPUT_DIR / f"{slugify(guide['episode'])}-production-guide.pdf"

    if args.html:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        env = Environment(
            loader=FileSystemLoader(str(TEMPLATE.parent)),
            autoescape=select_autoescape(["html"]),
        )
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(env.get_template(TEMPLATE.name).render(**guide),
                             encoding="utf-8")
        print(f"HTML: {args.html}")

    render(guide, destination)
    print(f"PDF: {destination}")


if __name__ == "__main__":
    main()
