---
name: shorts-production-guide
description: Build a full Editor Handoff Production Guide PDF for The Remodel King from a YouTube episode URL. Fetches the timestamped transcript from the URL, then produces a branded PDF containing two Shorts (a homeowner problem hook and a contractor solution proof), each with SEO title options, a scene by scene edit table with source footage timestamps, a paste-ready ElevenLabs VO block, voice direction, and CTA options. Use whenever the user says "build the production guide for [YouTube URL]", asks for an editor handoff document, a Shorts production guide, or a production guide PDF for an episode.
---

# Shorts Production Guide

Turn one episode URL into one branded Editor Handoff Production Guide PDF.

## Trigger

> build the production guide for [YouTube URL]

The input is ONLY a YouTube URL. Never ask the user to paste a transcript. If
they hand you a transcript anyway, use it, but the normal path is the URL.

## All Shorts rules apply

Everything in the `remodel-king-shorts` skill applies to every VO line written
here. Read that skill first if it is not already loaded. In particular:

- Mike's footage is ONLY pre-demo walkthroughs, progress STATE shots, and final
  reveals. He never films workers or active construction. Narration like "we
  gutted it" is fine but must play over a state shot. Editor notes must never
  call for footage of demo or installation happening.
- NEVER close on project cost or budget. Mike handles cost reveals with end
  slides he builds manually. Do not flag a missing cost as an issue.
- ElevenLabs formatting applied directly to the VO: ALL CAPS on roughly 10 to
  15 percent of words, ellipses before reveals with no space after, 3 to 5
  exclamation points per Short, occasional rhetorical questions, staccato short
  sentences, commas for flow, natural enthusiasm rather than hype.
- First person, Mike's voice. Every fact comes from the transcript.
- Never use em dashes in ANY output, ever.
- If highlight footage is limited, use fewer and longer VO lines that hold over
  reveal footage instead of many quick cuts.

## Step 1: fetch the transcript

Run the fetcher before writing anything:

```bash
python scripts/fetch_transcript.py "<YouTube URL>"
```

It saves `transcripts/[video_id].json` with per line timestamps and prints the
path. If the video has no captions it automatically falls back to downloading
audio with yt-dlp and transcribing with faster-whisper, producing the same JSON
shape. Read that JSON and work only from it.

The transcript timestamps become the Source Footage timestamp ranges in the
scene tables. Never invent a timestamp. If a beat has no matching transcript
moment, say so in the Editor notes for that scene.

## Step 2: default output is two Shorts, a mini funnel

Unless the user overrides it:

- **Short 1, homeowner problem hook.** The pain the homeowner recognizes in
  their own house. Ends pointing at the fact that it is fixable.
- **Short 2, contractor solution proof.** The proof that Mike solved it, built
  on the reveal and the specific upgrades.

Publish order is Short 1 first, then Short 2. The user can override the count
or the angle per episode. Honor the override and update the publish order logic
section to match.

## Step 3: each Short section

Every Short in the guide contains, in this order:

1. **Overview.** Working title, source clip range, target runtime, 9:16
   vertical format, primary goal.
2. **SEO title options.** 3 to 4 options built on longtail homeowner search
   phrases, the way a homeowner types a problem into YouTube.
3. **Scene by scene table.** Columns: Scene number, Short timeline, Source
   footage timestamps, Mike AI VO line, On-screen caption, Editor notes.
   Editor notes cover punch-ins, arrows, highlight boxes, whoosh transitions,
   and impact sounds, always over state shots.
4. **Full VO.** The combined read as one paste-ready ElevenLabs block, matching
   the scene lines exactly.
5. **Voice direction.** One or two lines.
6. **CTA options.** Primary, alt comment-bait, and pinned comment text.

## Step 4: the rest of the document

- **Project context.** Which segment of the episode was chosen and why, and the
  publish order logic for the funnel.
- **General production notes.** 1080x1920, bold white captions with a black
  outline, hook text in the upper third, supporting captions in the lower
  third.
- **Publishing checklist, per video.** Hook lands within 2 seconds, VO
  recorded, captions burned in, thumbnail, SEO title, description with the full
  video link, pinned comment, hashtags.

## Step 5: render the PDF

Write the guide content as JSON to `guides/[slug].json` following the shape in
`guides/example.schema.json`, then render:

```bash
python scripts/render_guide.py guides/[slug].json
```

The finished PDF lands in `output/[slug]-production-guide.pdf`. Give the user
the path. General production notes and the publishing checklist have defaults
built into the renderer, so only include them in the JSON to override.
