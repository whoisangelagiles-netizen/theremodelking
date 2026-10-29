---
name: long-video-finish
description: Final touches on an edited LONG Remodel King body video, after Mike or the editor has cut it. Chapter labels at each filming day, a few feature callouts in the reveal, before insets, link pills where Mike mentions a link, and a flash only on hard cuts, all in the house look and kept light. Delivered as overlay clips plus a Premiere / Resolve timeline, so nothing is re-cut. Use whenever the user shares an edited body video and asks for final touches, effects, labels, visuals, transitions or polish. This is NOT the Shorts process and NOT the long intro, never touch build_short.py, build_intro.py or their skills for it.
---

# Long Video Finish

One edited body in, a set of overlay clips and a timeline out. Every touch is a
graphic laid OVER the picture at a timestamp. The body is never re-cut,
re-timed or re-mixed, so the edit, the audio and the stats slides stay exactly as
delivered, and each touch can be nudged or deleted in the editor.

## The rule that decides everything: do not put too much

The user asked for light. Aim for one touch every 1.5 to 2 minutes across the
body, with most of them in the reveal. The build prints the rate. If a touch does
not help the viewer follow the build or notice a feature, leave it out.

## Step 1: fetch

The body is several gigabytes. Download it once into `work/[slug]/body/body.mp4`
(shared as anyone with the link):

```bash
python scripts/fetch_drive.py work/[slug] body/body.mp4=<body file id>
```

Probe it. The overlays are 1920x1080 at 30 fps, say so if the body is not.

## Step 2: read the body before adding anything

1. **Transcript.** Reuse `transcripts/[slug]-body.json` if the intro already made
   it, otherwise `python scripts/transcribe_audio.py` on its audio. Flatten it to
   timestamped lines and read all of it. Every label comes from what Mike says.
2. **What is already there.** Tile the whole body at one frame every 5 seconds and
   LOOK at every sheet. The editor already adds titles, dip to black transitions
   and a subscribe animation. Never stack a touch on one of those, and list them
   in the spec's `already_in_the_body` so the next pass knows.
3. **Where the days change.** Find the dips with `signalstats` (mean luma under
   22) and the hard cuts with the `scene` score, then confirm each at 30 fps.
   A flash goes ONLY on a hard cut between days. A dip the editor already made is
   the transition, leave it.
4. **Where Mike stands.** Tile the reveal at one frame every 2 seconds with the
   time burned in. Every touch picks its corner from those frames: never on his
   face, never on the feature being named.

## Step 3: the touches

| Kind | Fields | Use |
| --- | --- | --- |
| `chapter` | `text`, `kicker` | One per filming day, a beat after the picture returns from the dip. The editor's own title look: green bar, white Montserrat, no kicker by default. Never number them: Mike revises the body after this pass, and one cut segment throws every later number off. A kicker, when used, names the room ("Master bath"), never a step |
| `label` | `text`, `corner` | A feature name on the green plate, the AFTER label look. Only features Mike names, only while they are on screen |
| `inset` | `before`, `corner`, `width`, `focus` | A still from the body's own before walkthrough, white frame, BEFORE plate, over the same room finished. Two or three per video at most |
| `pill` | `text`, `corner`, `arrow` | White pill with a down arrow, when Mike says there is a link in the description |
| `flash` | `at` | White at 85 percent peaking on the cut frame, hard cuts between days only |

`at` is a body timestamp, `"32:59.5"`. `corner` is `bottom-left` (default),
`bottom-right`, `top-left` or `top-right`, and `offset` `[x, y]` nudges it.
`hold` overrides how long it stays up. Labels are written in plain case in the
spec and rendered in capitals. No em dashes, no prices, no square footage, no
weeks: the stats slides at the end carry those.

Write `finishes/[slug].json`, see `finishes/east-bench-phase-3.json`.

## Step 4: build and check

```bash
python scripts/finish_body.py finishes/[slug].json
```

About two minutes. It writes, under `output/`:

- `[slug]-finish-package.zip`, the overlays folder, the XML and the markers
- `[slug]-finish-reel.mp4`, every touch over its stretch of the body, back to back
- `[slug]-finish-sheet.jpg`, one frame per touch at full strength

LOOK at the sheet and scrub the reel. Check every touch: on a face, over the
feature it names, a corner that fights something already in the frame, an
animation that starts before the shot does. Fix the spec and rebuild.

`--full` also burns everything into the whole body,
`output/[slug]-body-finished.mp4`. It takes most of an hour and is as big as the
body, too big to send from a cloud session, so build it only when the user has a
way to receive it.

## Step 5: hand off

Send the package zip, the reel and the sheet with SendUserFile. `output/` is
gitignored and the container is reclaimed. Tell the user how to use it:

1. Unzip next to the body video.
2. In Premiere, File > Import the `.xml`. Point it at the body once when it asks,
   the overlays relink from the `overlays/` folder. Resolve: File > Import >
   Timeline.
3. The body sits on V1, the touches above it at their exact frames.

Commit the spec. Mention anything worth flagging in the body itself, but never
change it.
