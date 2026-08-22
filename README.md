# The Remodel King, Shorts Production System

Two Claude Code skills that turn full episodes of The Remodel King into
publish-ready vertical Shorts, plus the rendering pipeline that prints the
editor handoff as a branded PDF.

## Skills

### 1. `remodel-king-shorts`, fast single Short

**Trigger:** paste an episode transcript and say something like

> Here is the transcript for [EPISODE NAME] create a youtube short script ready

**Output:** a Shorts VO script ready to paste into ElevenLabs, then an edit map
of source timestamps and what each frame shows. Nothing else, no titles,
descriptions, or hashtags unless you ask. Ends with a one line offer of an A/B
alternate, same cut, entirely reworded narration.

The format is a **reveal tour**: the transformation in one sentence, who it was
for, the turn, then six to ten named features one per line. Plain prose, 145 to
175 words, 50 to 60 seconds. The end card carries the call to action, not the
narration.

Lives in `.claude/skills/remodel-king-shorts/SKILL.md`.

### 2. `shorts-production-guide`, full editor handoff PDF

**Trigger:**

> build the production guide for [YouTube URL]

The input is a URL or a local master, not a transcript. The skill transcribes
the episode with whisper itself, then builds the guide. **One Short per
episode.** Override the angle per episode just by saying so.

Each Short section carries an overview, 3 to 4 longtail SEO title options, a
scene by scene table with source footage timestamps, the full paste-ready
ElevenLabs VO block, voice direction, and CTA options. The document also
carries project context, general production notes, and a per video publishing
checklist.

Lives in `.claude/skills/shorts-production-guide/SKILL.md`.

## House rules baked into both skills

- **Frame the feature, not the talker.** Cropping 16:9 to 9:16 throws away two
  thirds of the picture, so the crop decides the entire shot. If the line is
  about the niche, the niche fills the window and Mike sits outside it. A Short
  where the window keeps landing on him is the failure mode.
- Mike's footage is only pre-demo walkthroughs, progress state shots, and final
  reveals. He never films workers or active construction, so edit notes never
  ask for demo or installation footage.
- The finished house carries the Short. Before footage is the hook and at most
  one beat after it.
- Cost is never the closer. Mike builds cost reveals as end slides by hand, and
  the price segment goes in `avoid_ranges` so no scene can land on it.
- Nothing is ever laid over Mike's face, captions included.
- No zoom beyond what makes the shot vertical, 178 percent on a 16:9 clip. The
  source is handheld and already moves, so `pan` stays null by default.
- No repeated footage, within a Short or across an episode's Shorts. Two lines
  can share one shot, but only as a single continuous take: they render as one
  clip, so an action like a door closing finishes without a cut through it. The build warns on repeats and on cuts between near identical frames.
- Frame the feature, not the talker. If the line is about the vanity, the vanity
  fills the window. Mike carries the hook and the CTA, not every beat.
- First person for the work, third person for the homeowner, facts only from
  the transcript.
- Plain prose. No ALL CAPS emphasis markers, no stacked exclamation points, no
  rhetorical questions.
- Words the voice model reads wrong are respelled on the way to ElevenLabs and
  put back to the real spelling on screen. "niche" is sent as "nitch".
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
output/[slug]-short-[n]-PUBLISH.mp4          THIS IS THE ONE TO UPLOAD
output/[slug]-short-[n]-FINAL.mp4            CRF 18 master, archive quality
output/[slug]-short-[n]-contact-sheet.jpg    one frame per scene, eyeball it without downloading
output/[slug]-short-[n]-thumbnail.jpg        first frame style
output/[slug]-short-[n]-publish.md           SEO titles, description, pinned comment, hashtags
```

**`output/` is gitignored and a cloud container gets reclaimed**, so nothing in
there survives a session. Take the `PUBLISH` copy out before you close the
session. It is CRF 20 capped at 3.5 Mbps, which keeps a 60 second Short around
20 to 26MB, under the 30MB chat upload limit, and is well above what YouTube
keeps after its own re-encode. The `FINAL` master is CRF 18 and runs past 40MB,
which is worth keeping only if you plan to re-edit.

Useful flags: `--captions labels|subtitles|both` (default labels, the guide's
summary captions), `--location-audio 0.03` (bring the original clip audio back
as a low bed, default is muted), `--line-gap 0.28` (pause held after each
narration line), `--style 0.70` and `--stability 0.28` (how animated the read
is, lower stability and higher style let Mike's voice move more), `--auto`
(skip the analysis pause, center crop, technical checks only), `--skip-vo`
(picture with no narration), `--no-music`, `--no-logo`, `--logo-width 0.16`,
`--logo-opacity 0.92`, `--rescan 3`, `--redownload`, `--revoice`,
`--voice-id`, `--font`.

The guide can pin per episode voice settings with a `voice_settings` object,
and mark footage that must never be used with `avoid_ranges`, for instance the
segment where Mike talks price. The build warns when a scene overlaps one.

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
| 1 | `faster-whisper` on the audio, from `--source` or pulled with `yt-dlp` | **First, by default.** The only tier that returns punctuation, sentence boundaries, and word level timings, which is what the guide and the shot anchoring are written from |
| 2 | `youtube-transcript-api` | When whisper cannot get the audio |
| 3 | `yt-dlp` subtitles, json3 or vtt, published track preferred over auto | When tier 2 is blocked by IP, which is normal from a cloud container |

Auto captions arrive with no punctuation and mangle trade words, and a guide
written from them inherits both, so the extra minute of transcription is worth
it. `--captions-first` flips the order for a quick scan. `--no-auto-install`
stops whisper installing itself.

## What the assembly actually does

| Step | Detail |
| --- | --- |
| Cut | One clip per scene from the analyzed source range. Overlapping ranges and cuts that land between near identical frames are flagged at build time |
| Crop | 9:16 window at the per scene `crop_x`, scaled to 1080x1920 |
| Motion | The frame pans across the shot and settles on the feature Mike is naming, the way it would be keyframed by hand. Scaling is only ever what filling the 9:16 frame requires, there is no punch in on top |
| Annotations | Arrows and highlight boxes in brand green `#0E9346`, placed where the pan lands and held once it settles, so they never slide across the shot |
| Captions | The spoken words, four to six at a time, timed from ElevenLabs character timestamps. White Montserrat ExtraBold at 48px with a 2px black stroke, on a solid green plate `#16A34A`, 10px side padding, 57px line pitch, wrapping at 0.72 of frame width so a card never runs past two lines. The plate's bottom edge is pinned at 0.746 of frame height so it never moves between cards. All of it measured off the channel's own Shorts. Lifts clear of Mike's face when he is in the band. `--captions labels` switches to the guide's summary captions |
| Watermark | The logo from `assets/` top right of every scene and the CTA frame, soft shadow, sized to its native pixels, locked to the corner while the picture pans |
| Overlays | Optional branded ProRes 4444 alpha `.mov` from `assets/overlays/`, composited per named scene |
| Audio | Mike's VO only. The original location audio is MUTED, `--location-audio 0.03` brings back the old low bed. Impact on frame one, whoosh at the problem to solution shift, optional music bed at 6 percent, limited at 0.95, padded to the picture |
| Fit | Scene out-points stretch or tighten so the picture and the narration land together |
| End | 3 seconds of live footage carrying a stack of tilted stickers, alternating white and green, plus the handle in a pill. Never a black card. `cta_frame` in the guide takes one line per sticker |

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
| `work/` | Source video, then per Short keyframes, edit decisions, VO lines, and scene clips under `work/[video_id]/short[n]/`. Gitignored, safe to delete |
| `output/` | Finished PDFs, Shorts, and contact sheets |
| `assets/fonts/` | Montserrat ExtraBold for captions, Anton for the end card, both committed so a fresh container renders identically |
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
