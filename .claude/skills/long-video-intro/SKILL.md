---
name: long-video-intro
description: Build the 10 to 15 second cold open that goes in front of a LONG Remodel King video, 1920x1080, from the project's Google Drive folder. Before and after glimpses, a short overview of the transformation in Mike's ElevenLabs voice, and a tease of the project cost and completion time without revealing either. Use whenever the user says "build the long intro for [Drive folder]", "make the intro for the long video", or hands over a project folder with a body video and asks for the opening. This is NOT the Shorts process, never touch build_short.py or the Shorts skills for it.
---

# Long Video Intro

One Drive folder in, one finished intro MP4 out. Mike drops it in front of the
body in his editor and handles the transition himself.

## What goes in the folder

The project folder on Drive follows one layout. List it with the Google Drive
tools (`search_files` with `parentId = '<folder id>'`, then each subfolder):

| Item | Use |
| --- | --- |
| `Pre Demo & Pics` | before photos and the pre demo walkthrough clip |
| `Progress Video` | state shots mid build, rarely used in the intro |
| `Final Video & Pics` | after photos and the final reveal walkthrough |
| `Project Stats Template.pptx` | project name, scope, price, square feet, time. Read it with `read_file_content` |
| `[name] Body Video.mp4` | the long video body. Probe its format, transcribe its audio |
| a slides folder | the stats slides. They are already at the end of the body |

The PROJECT NAME comes from the stats deck, not the file names. The body file
can carry the client's name ("Bateman"), the name on screen is the house name
("East Bench House Phase 3").

## Step 1: fetch

Files must be shared as anyone with the link. Download what the intro can use,
photos and the pre demo and final clips, into `work/[slug]/pre`, `work/[slug]/final`
and `work/[slug]/progress`:

```bash
python scripts/fetch_drive.py work/[slug] pre/01.jpg=<id> final/IMG-0896.mov=<id> ...
```

Never download the body video. Probe it over HTTP and stream only its audio:

```bash
ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate:format=duration \
  "https://drive.usercontent.google.com/download?id=<body id>&export=download&confirm=t"
python scripts/fetch_drive.py --audio work/[slug]/[slug]-body/audio.m4a <body id>
python scripts/transcribe_audio.py work/[slug]/[slug]-body/audio.m4a   # lands in transcripts/[slug]-body.json
```

The intro must match the body. `build_intro.py` renders 1920x1080, 30 fps,
H.264 and AAC 48k stereo, and its read lands within a decibel of the body's
level. If the body is anything else, say so before building.

## Step 2: look

Tile the before and after photos into contact sheets and LOOK at them, then
tile the final reveal clip at one frame every five seconds and again at one per
second around the moments worth using. Pick:

- **Before and after pairs that match.** Same room, ideally the same angle. A
  doorway shot of the toilet room against the same doorway after is worth more
  than two prettier photos that do not line up. If nothing matches, use the
  pair that shows the biggest part of the house.
- **Clean reveal footage.** Moments where the feature carries the frame. Watch
  the tail of every pick, Mike walks into his own shots.
- **One wide reveal for the tease card**, the most striking room.

## Step 3: the script

Three lines, Mike's voice, first person, about 35 to 45 words. The build warns
outside 10 to 15 seconds.

1. **What the project was.** The rooms and how far down it went.
2. **The transformation.** The two features that land hardest on screen.
3. **The tease.** That the cost and the time are coming, never the numbers.
   "Stick around, and I'll tell you what it cost and how long it took."

Every fact comes from the body transcript. Every line must be true OF THE
PICTURE UNDER IT: a heated floor line over laundry footage is wrong if only the
bathroom is heated. All the Shorts writing rules hold: plain prose, no ALL CAPS
emphasis, no rhetorical questions in the read, no em dashes anywhere. Never put
the price, the square footage or the weeks on screen or in the read.

## Step 4: the spec

Write `intros/[slug].json`, see `intros/east-bench-phase-3.json`. Each line owns
its stretch of the read and its shots split it by `weight`:

| Shot | Fields | What it does |
| --- | --- | --- |
| `wipe` | `before`, `after`, `wipe_at` | full frame before, the after wipes in from the right, BEFORE then AFTER label |
| `split` | `before`, `after` | side by side halves, BEFORE and AFTER labels. Best for portrait photos |
| `clip` | `media` | a stretch of footage at full frame |

Media is a photo path, or `{"src": "final/IMG-0896.mov", "at": "4:59.4"}` for
footage. Clips and photos mix freely inside a split. `focus` (or
`before_focus` / `after_focus`) moves the crop centre, `[x, y]` from 0 to 1.
Photos get a slow push, footage never does.

The tease line carries `card`, `{"title": [...], "kicker": "STAY TO THE END",
"delay": 1.2}`. The footage under it blurs and dims as the card lands, so no
word ever sits on Mike's face, and spoken captions stop for that line.

## Step 5: build and check

```bash
python scripts/build_intro.py intros/[slug].json
```

The VO renders once and is cached by its text, so picture fixes rebuild in under
a minute without paying for another take. `--revoice` forces a new take.

Then tile the finished intro at two frames a second and check EVERY tile, not
just the sheet: a label on the wrong side of a wipe, Mike creeping into the end
of a clip, a caption over his face, a black frame at the tail. Fix the spec and
rebuild until it is clean.

`impact`, `whoosh` and `music` in `assets/` are picked up when present, the
whoosh lands on each wipe.

## Step 6: hand off

Send `output/[slug]-intro.mp4` with SendUserFile. `output/` is gitignored and the
container is reclaimed, a path is not a deliverable. Commit the spec.
