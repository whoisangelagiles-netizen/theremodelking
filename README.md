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

## Setup, once

1. Put your logo in `assets/logo.png`, transparent PNG. It becomes the
   watermark in the top right of every Short. See `assets/README.md`.
2. Provide two credentials. NEVER commit them, this repository is public.
   Any of these three work, the scripts read them in this order:

   ```bash
   # a. your shell, for local runs
   export ELEVENLABS_API_KEY=sk_...
   export ELEVENLABS_VOICE_ID=...     # Mike's voice

   # b. a .env file at the repo root, gitignored, also for local runs
   printf 'ELEVENLABS_API_KEY=sk_...\nELEVENLABS_VOICE_ID=...\n' > .env

   # c. for cloud sessions, the environment variables box in the cloud
   #    environment dialog at claude.ai/code. Open the cloud icon in the row
   #    above the message box, hover your environment, click the gear. There
   #    is no settings page for it. Values apply to sessions started after
   #    you save, and anyone using that environment can read them.
   ```

3. Confirm it all landed:

   ```bash
   python scripts/check_setup.py                 # what is present, what is missing
   python scripts/check_setup.py --list-voices   # every voice on the account with its id
   ```

   It validates the key against the ElevenLabs API, confirms the voice id
   actually exists on your account, and reports your remaining character
   budget. Warnings are optional pieces, they degrade gracefully.

## One command, finished Short

```bash
python scripts/build_short.py "https://www.youtube.com/watch?v=VIDEO_ID" 1
```

That is the whole job: transcript, production guide, source download at highest
quality, keyframe analysis, ElevenLabs VO, cut, 9:16 crop, punch-ins, arrows and
highlight boxes, burned in captions, whoosh and impact, ducked location audio,
optional music bed, branded overlays, CTA end frame, export, contact sheet. No
editing pass afterward.

It stops twice and hands the work to Claude, because both steps need judgement:

1. **Guide.** If no guide exists for the video, Claude writes it from the
   fetched transcript, then you rerun the same command.
2. **Frame analysis.** The build extracts 4 keyframes per scene and stops.
   Claude looks at every frame and writes `work/[video_id]/short[n]/edits.json`,
   the horizontal crop offset that keeps the subject in the 9:16 frame,
   punch-in targets, and exact arrow and highlight box coordinates so they land
   on the actual feature. If the frames do not show what the VO describes,
   Claude picks a different transcript range and re-extracts with
   `--rescan [scene]`. Then you rerun the same command and it finishes.

Finished files:

```
output/[slug]-short-[n]-FINAL.mp4            1080x1920, publish ready
output/[slug]-short-[n]-contact-sheet.jpg    one frame per scene, eyeball it without downloading
```

Useful flags: `--auto` (skip the analysis pause, center crop, technical checks
only), `--skip-vo` (picture with no narration), `--no-music`, `--no-logo`,
`--logo-width 0.16`, `--logo-opacity 0.92`, `--rescan 3`, `--redownload`,
`--revoice`, `--voice-id`, `--font`.

## Running the pieces on their own

```bash
pip install -r requirements.txt   # plus ffmpeg and yt-dlp on the system

# pull the timestamped transcript
python scripts/fetch_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID"
#    writes transcripts/[video_id].json
#    no captions on the video? it falls back to yt-dlp plus faster-whisper

# the skill writes the guide content to guides/[slug].json

# render the handoff PDF
python scripts/render_guide.py guides/[slug].json
#    writes output/[slug]-production-guide.pdf
```

## What the assembly actually does

| Step | Detail |
| --- | --- |
| Cut | One clip per scene from the analyzed source range |
| Crop | 9:16 window at the per scene `crop_x`, scaled to 1080x1920 |
| Punch in | zoompan glued to the analyzed focus point |
| Annotations | Arrows and highlight boxes in brand green `#0E9346`, drawn before the punch in so they stay stuck to the feature |
| Captions | Bold white, black outline, hook upper third, supporting lower third, burned in |
| Watermark | `assets/logo.png` top right of every scene and the CTA frame, soft shadow, fixed while the picture punches in |
| Overlays | Optional branded ProRes 4444 alpha `.mov` from `assets/overlays/`, composited per named scene |
| Audio | VO full, location audio ducked to 3 percent, impact on frame one, whoosh at the problem to solution shift, music bed at 6 percent, limited at 0.95 |
| Fit | Scene out-points stretch or tighten so the picture and the narration land together |
| End | Simple text CTA frame, 2.4 seconds, no long end card |

See `assets/README.md` for the exact files to upload and what happens when one
is missing. Nothing in `assets/` is required, a missing file is skipped with a
note rather than failing the build.

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
| `assets/` | Branded overlays and sound you upload, see `assets/README.md` |
| `work/` | Source video, keyframes, edit decisions, VO, scene clips. Gitignored, safe to delete |
| `output/` | Finished PDFs, Shorts, and contact sheets |
| `scripts/` | `fetch_transcript.py`, `render_guide.py`, `build_short.py`, `check_setup.py` |

## Requirements

`ffmpeg` and `yt-dlp` on the system, plus `pip install -r requirements.txt`.
`ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` come from the environment and are
never written to the repo.
