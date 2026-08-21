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
- The read must sound homeowner friendly, clear and conversational, confident
  and expert, and tighter and more intentional than the original walkthrough
  audio. Mark the words that carry the point so the team can paste the block
  straight into ElevenLabs.
- Leave a small pause between sentences so the cuts and the pans have room.
- On screen text in the finished video is the SUMMARY LABEL per scene, the
  caption column from the guide. `--captions subtitles` switches to word for
  word subtitles timed to the read, `both` draws each in its own band.
- The finished audio is Mike's VO alone. The original location audio is muted,
  not ducked, so nothing of the walkthrough track survives under the read.
- Scale the shot JUST enough to fill the 9:16 frame, Premiere's 178 percent on a
  16:9 clip, and no more. No punch ins. `zoom` above 1.0 exists for a genuine
  detail framing on a 1080p or better source, and even then stays modest.
- FRAME THE FEATURE, NOT THE TALKER. If the line is about the doors, the vanity,
  the built-in or the niche, that is what fills the window, even when Mike is
  the loudest thing in the source frame. He belongs in the hook and the CTA, not
  in every beat. A Short where every scene is Mike talking is the failure mode.
- NEVER put captions, words, or graphics on Mike's face. Captions go above his
  head or below his chin, never across it. The build enforces this from the
  face box you record during frame analysis.
- Never use em dashes in ANY output, ever.
- If highlight footage is limited, use fewer and longer VO lines that hold over
  reveal footage instead of many quick cuts.

## Step 1: fetch the transcript

Run the fetcher before writing anything:

```bash
python scripts/fetch_transcript.py "<YouTube URL>"
```

It saves `transcripts/[video_id].json` with per line timestamps and prints the
path. It tries three tiers by itself, the caption API, then yt-dlp subtitles,
then faster-whisper on the downloaded audio, and every tier produces the same
JSON shape. The `source` field records which one was used. Read that JSON and
work only from it.

The transcript timestamps become the Source Footage timestamp ranges in the
scene tables. Never invent a timestamp. If a beat has no matching transcript
moment, say so in the Editor notes for that scene.

## Step 2: scan the episode for Shorts opportunities

Before writing any guide, work the whole transcript through four lenses:

1. Homeowner problems
2. Solutions Mike provided through the remodel
3. Problems encountered during the project and how they were fixed
4. Product mentions, material recommendations, and product review angles

For every strong opportunity, give all seven of these:

1. Exact timestamps
2. Clip length
3. Why it works as a Short
4. SEO friendly title options
5. Hook text for the first 2 seconds
6. On screen caption ideas
7. Best CTA and end frame strategy

**Be honest about weak episodes.** If the episode is not strong for problem and
solution or product review Shorts, say so plainly and explain whether it works
better as a project showcase. Do not force two Shorts out of an episode that
does not carry them.

Then pick the best two and build the guide from those. Keep the scan in the
guide JSON under `opportunities` so the content team sees what was considered
and what was left on the table.

## Step 3: default output is two Shorts, a mini funnel

Unless the user overrides it:

- **Short 1, homeowner problem hook.** The pain the homeowner recognizes in
  their own house. Ends pointing at the fact that it is fixable.
- **Short 2, contractor solution proof.** The proof that Mike solved it, built
  on the reveal and the specific upgrades.

Publish order is Short 1 first, then Short 2. The user can override the count
or the angle per episode. Honor the override and update the publish order logic
section to match.

## Step 4: each Short section

Every Short in the guide contains, in this order:

1. **Overview.** Working title, source clip range, target runtime, 9:16
   vertical format, primary goal.
2. **SEO title options.** 3 to 4 options built on longtail homeowner search
   phrases, the way a homeowner types a problem into YouTube.
3. **Scene by scene table.** Columns: Scene number, Short timeline, Source
   footage timestamps, Mike AI VO line, On-screen caption, Editor notes.
   Editor notes cover pans, arrows, highlight boxes, whoosh transitions, and
   impact sounds, always over state shots. Never call for a punch in.
4. **Full VO.** The combined read as one paste-ready ElevenLabs block, matching
   the scene lines exactly.
5. **Voice direction.** One or two lines.
6. **CTA options.** Primary, alt comment-bait, and pinned comment text.

## Step 5: the rest of the document

- **Project context.** Which segment of the episode was chosen and why, and the
  publish order logic for the funnel.
- **General production notes.** 1080x1920, bold white captions with a black
  outline, hook text in the upper third, supporting captions in the lower
  third.
- **Publishing checklist, per video.** Hook lands within 2 seconds, VO
  recorded, captions burned in, thumbnail, SEO title, description with the full
  video link, pinned comment, hashtags.

## Step 6: render the PDF

Write the guide content as JSON to `guides/[slug].json` following the shape in
`guides/example.schema.json`, then render:

```bash
python scripts/render_guide.py guides/[slug].json
```

The finished PDF lands in `output/[slug]-production-guide.pdf`. Give the user
the path. General production notes and the publishing checklist have defaults
built into the renderer, so only include them in the JSON to override.

Three scene fields exist for the finishing pipeline, set them while writing the
guide:

- `caption_zone`, `hook` or `support`. Defaults to hook on scene 1.
- `transition`, set to `whoosh` on the one scene carrying the problem to
  solution shift.
- `overlay`, the filename of a branded alpha `.mov` in `assets/overlays/` when
  a scene calls for one.

Set `cta_frame` on the Short for the end frame text, otherwise `cta.primary`
is used.

## Step 7: build the finished Short

When the user wants a finished video rather than a handoff document:

```bash
python scripts/build_short.py "<YouTube URL>" <short number>
```

It runs transcript, guide check, source download, keyframe extraction, VO,
assembly, and contact sheet. It stops twice and hands the work back to you.

### Pause one, the guide

If no guide JSON matches the video id, the build stops. Write the guide with
this skill, save it to `guides/[slug].json` with the YouTube URL in
`video_url`, then rerun the same command.

### Pause two, frame analysis. This one is yours to do with your eyes.

The build extracts 4 keyframes per scene into
`work/[video_id]/short[n]/frames/` and writes a skeleton
`work/[video_id]/short[n]/edits.json`, then stops.

Read every frame with the Read tool. Do not fill in numbers you have not
looked at. For each scene write:

- `crop_x`, the horizontal center of the 9:16 window as 0 to 1 across the full
  source frame. 0.5 is dead center. Move it so the subject and the feature the
  VO names stay in frame after the crop. A wide kitchen reveal with the island
  camera right needs `crop_x` near 0.65, not 0.5.
- `pan`, `{"from": x, "to": x}`. This is the house move. The 9:16 crop is
  already the only zoom there is, so the frame does not punch in, it SLIDES
  across the shot and settles on whatever Mike is talking about. Keep it gentle,
  0.08 to 0.18 of frame width, and check the feature is in frame at both ends.
  A shot under about 2 seconds holds static instead.
- `punch_in` stays `null`. Mike does not want extra zoom on top of the vertical
  crop, and a punch in on a 720p or 1080p source only softens it further.
- `annotations`, exact coordinates so arrows and boxes land on the real
  feature, not near it. Boxes are `{"type":"box","target":"...","x","y","w","h"}`
  with x and y the top left corner. Arrows are
  `{"type":"arrow","target":"...","from":[x,y],"to":[x,y]}` with the arrowhead
  on the feature. All coordinates are normalized against the full source frame
  you are looking at, the build maps them through the crop for you.
- `face`, Mike's head INCLUDING the cap and jaw, as `{"x","y","w","h"}`
  normalized to the source frame, or `null` when he is not in shot. This is not
  optional. Captions are never allowed to touch his face, so the build needs to
  know where it is. It adds a drift margin on top of your box, because he moves
  inside the shot, and then places each caption in the largest clear band.
- `frames_show_what_the_vo_says`, true or false, honestly.

If the frames do not show what the VO line describes, do not caption over the
wrong footage. Pick a better range from the fetched transcript, put it in that
scene's `source`, and rerun with `--rescan 3` to re-extract just that scene.
Then look again.

Set `"analyzed": true` when every scene is done and rerun the plain command.
The build finishes and writes:

- `output/[slug]-short-[n]-FINAL.mp4`, 1080x1920, publish ready
- `output/[slug]-short-[n]-contact-sheet.jpg`, one frame per scene

Read the contact sheet before you tell the user it is done. If a caption sits
over a face, a crop cuts the feature, or an arrow points at nothing, fix the
numbers and rebuild. Send the user both files with SendUserFile.

`--auto` skips the analysis pause with center crop defaults. It is for a quick
technical check only, never for a Short that gets published.

## What the finished build hands back

Per Short, in `output/`:

- `[slug]-short-[n]-FINAL.mp4`, 1080x1920, publish ready
- `[slug]-short-[n]-contact-sheet.jpg`, one frame per scene
- `[slug]-short-[n]-thumbnail.jpg`, first frame style
- `[slug]-short-[n]-publish.md`, SEO titles, description with the full video
  link, pinned comment, hashtags, and the publishing checklist

That covers every line of the publishing checklist except the act of uploading.
