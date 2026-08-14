# The Remodel King, Shorts Production System

Two Claude Code skills that turn full episodes of The Remodel King into
publish-ready vertical Shorts, plus the rendering pipeline that prints the
editor handoff as a branded PDF.

## Skills

### 1. `remodel-king-shorts`, fast single Short

**Trigger:** paste an episode transcript and say something like

> Here is the transcript for [EPISODE NAME] create a youtube short script ready

**Output:** a Shorts VO script already formatted for ElevenLabs, then an edit
map of source timestamps and what each frame shows. Nothing else, no titles,
descriptions, or hashtags unless you ask. Ends with a one line offer of an A/B
alternate, same cut, entirely reworded narration.

Lives in `.claude/skills/remodel-king-shorts/SKILL.md`.

### 2. `shorts-production-guide`, full editor handoff PDF

**Trigger:**

> build the production guide for [YouTube URL]

The input is a URL, not a transcript. The skill fetches the timestamped
transcript itself, then builds the guide. Default output is two Shorts forming
a mini funnel, Short 1 a homeowner problem hook and Short 2 the contractor
solution proof, published in that order. Override the count or the angle per
episode just by saying so.

Each Short section carries an overview, 3 to 4 longtail SEO title options, a
scene by scene table with source footage timestamps, the full paste-ready
ElevenLabs VO block, voice direction, and CTA options. The document also
carries project context, general production notes, and a per video publishing
checklist.

Lives in `.claude/skills/shorts-production-guide/SKILL.md`.

## House rules baked into both skills

- Mike's footage is only pre-demo walkthroughs, progress state shots, and final
  reveals. He never films workers or active construction, so edit notes never
  ask for demo or installation footage.
- Cost is never the closer. Mike builds cost reveals as end slides by hand.
- First person, Mike's voice, facts only from the transcript.
- ElevenLabs formatting applied directly to the script.
- No em dashes, anywhere, ever.

## Pipeline

```bash
pip install -r requirements.txt

# 1. pull the timestamped transcript
python scripts/fetch_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID"
#    writes transcripts/[video_id].json
#    no captions on the video? it falls back to yt-dlp plus faster-whisper

# 2. the skill writes the guide content to guides/[slug].json

# 3. render the PDF
python scripts/render_guide.py guides/[slug].json
#    writes output/[slug]-production-guide.pdf
```

`guides/example.schema.json` documents the guide JSON shape.
`.claude/skills/shorts-production-guide/template.html` holds the branded
layout, brand green `#0E9346` rules and diamond accents, charcoal body text,
cover page with channel, episode, and date, "Internal Production Document"
footer.

## Folders

| Path | What lives here |
| --- | --- |
| `transcripts/` | Fetched transcript JSON, one per video id |
| `guides/` | Guide content JSON, one per episode |
| `output/` | Finished PDFs |
| `scripts/` | `fetch_transcript.py`, `render_guide.py` |
