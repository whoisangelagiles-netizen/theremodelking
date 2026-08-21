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
- Nothing is ever laid over Mike's face, captions included.
- No zoom beyond what makes the shot vertical. The frame pans to the subject
  instead of punching in.
- First person, Mike's voice, facts only from the transcript.
- ElevenLabs formatting applied directly to the script.
- No em dashes, anywhere, ever.

## Setup, once

1. Put your logo in `assets/`, transparent PNG. Any filename with "logo" in it
   works, `logo.png` or `KCS Logo.png` alike. It becomes the watermark in the
   top right of every Short. See `assets/README.md`.
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
quality, keyframe analysis, ElevenLabs VO, cut, 9:16 crop, pans, arrows and
highlight boxes, burned in captions, whoosh and impact, muted location audio,
optional music bed, branded overlays, CTA end frame, export, contact sheet. No
editing pass afterward.

It stops twice and hands the work to Claude, because both steps need judgement:

1. **Guide.** If no guide exists for the video, Claude writes it from the
   fetched transcript, then you rerun the same command.
2. **Frame analysis.** The build extracts 4 keyframes per scene and stops.
   Claude looks at every frame and writes `work/[video_id]/short[n]/edits.json`,
   the horizontal crop offset that keeps the subject in the 9:16 frame,
   the pan that carries the frame to the feature Mike is naming, and exact arrow
   and highlight box coordinates so they land on the actual feature. If the frames do not show what the VO describes,
   Claude picks a different transcript range and re-extracts with
   `--rescan [scene]`. Then you rerun the same command and it finishes.

Finished files:

```
output/[slug]-short-[n]-FINAL.mp4            1080x1920, publish ready
output/[slug]-short-[n]-contact-sheet.jpg    one frame per scene, eyeball it without downloading
```

Useful flags: `--captions labels|subtitles|both` (default labels, the guide's
summary captions), `--location-audio 0.03` (bring the original clip audio back
as a low bed, default is muted), `--line-gap 0.28` (pause held after each
narration line), `--auto` (skip the analysis pause, center crop, technical
checks only), `--skip-vo` (picture with no narration), `--no-music`,
`--no-logo`, `--logo-width 0.16`, `--logo-opacity 0.92`, `--rescan 3`,
`--redownload`, `--revoice`, `--voice-id`, `--font`.

## Running the pieces on their own

```bash
pip install -r requirements.txt   # plus ffmpeg and yt-dlp on the system

# pull the timestamped transcript
python scripts/fetch_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID"
#    writes transcripts/[video_id].json

# the skill writes the guide content to guides/[slug].json

# render the handoff PDF
python scripts/render_guide.py guides/[slug].json
#    writes output/[slug]-production-guide.pdf
```

## How transcripts are fetched

Three tiers, cheapest first, all producing the same timestamped JSON:

| Tier | How | When it runs |
| --- | --- | --- |
| 1 | `youtube-transcript-api` | First. Fast, no download. Commonly blocked by IP from cloud containers, and it fails fast when it is |
| 2 | `yt-dlp` subtitles, json3 or vtt, published track preferred over auto | When tier 1 fails. This is the tier that works from a cloud session |
| 3 | `yt-dlp` audio plus `faster-whisper` | Only when a video genuinely has no captions. Installs itself on demand, so it stays out of `requirements.txt` and out of session startup |

Nothing to configure. `--no-auto-install` stops tier 3 from installing itself.

## What the assembly actually does

| Step | Detail |
| --- | --- |
| Cut | One clip per scene from the analyzed source range |
| Crop | 9:16 window at the per scene `crop_x`, scaled to 1080x1920 |
| Motion | The frame pans across the shot and settles on the feature Mike is naming, the way it would be keyframed by hand. Scaling is only ever what filling the 9:16 frame requires, there is no punch in on top |
| Annotations | Arrows and highlight boxes in brand green `#0E9346`, placed where the pan lands and held once it settles, so they never slide across the shot |
| Captions | Summary label per scene by default, bold white with a black outline, burned in, hook upper third and support lower third, never across Mike's face. `--captions subtitles` switches to word for word subtitles timed from ElevenLabs character timestamps, `both` draws each in its own band |
| Watermark | The logo from `assets/` top right of every scene and the CTA frame, soft shadow, sized to its native pixels, fixed while the picture punches in |
| Overlays | Optional branded ProRes 4444 alpha `.mov` from `assets/overlays/`, composited per named scene |
| Audio | Mike's VO only. The original location audio is MUTED, `--location-audio 0.03` brings back the old low bed. Impact on frame one, whoosh at the problem to solution shift, optional music bed at 6 percent, limited at 0.95, padded to the picture |
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
`faster-whisper` lives in `requirements-whisper.txt` and installs itself on
demand, only when a video has no captions at all, so it stays out of the
default install and out of session startup.

`ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` come from the environment or a
gitignored `.env`, never from a committed file.

### Cloud sessions

A fresh cloud session starts from a clean container, so `ffmpeg` and the python
packages have to be installed before the pipeline can run. Paste
`scripts/setup_session.sh` into the **Setup script** box in the cloud
environment dialog at claude.ai/code, the same dialog that holds the
environment variables. Then every new session comes up ready to build.
