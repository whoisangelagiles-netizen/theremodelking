---
name: shorts-production-guide
description: Build one finished Short, or the Editor Handoff Production Guide PDF, for The Remodel King from a YouTube URL or a local master. Transcribes the episode with whisper, scans it for the strongest reveal tour, then writes the guide JSON the build runs on, with SEO title options, a scene by scene edit table anchored to source timestamps, the paste-ready ElevenLabs VO block, and CTA options. Use whenever the user says "build the production guide for [URL]", "make a short for this one", asks for an editor handoff document, a Shorts production guide, or a production guide PDF for an episode.
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
- Plain prose. No ALL CAPS emphasis markers, no stacked exclamation points, no
  rhetorical questions. The original spec asked for those, Mike does not want
  them, and the reference Short the channel publishes has none of them.
- First person, Mike's voice. Every fact comes from the transcript.
- The read is warm and unhurried, a contractor showing a friend the finished
  room. The features carry it, the delivery does not push.
- The read ALWAYS ends on the spoken sign off, "Follow for more before and
  afters". Do not write it as a scene, the build appends it to the script by
  itself and plays it over the end card. Override it with `cta_vo` on the Short
  if an episode wants different words.
- The narration is one render with a 0.26s pause spliced in at each line
  boundary, so budget for it: thirteen lines is 3.4 seconds of pause and the
  sign off is another 3, which together is most of a beat. A 150 word script
  lands near 54 seconds, not 50.
- Lines run 8 to 15 words. One line is one shot, so a 20 word line is a seven
  second hold on one frame, which is too long on a phone. Do NOT make every
  shot the same length either, the variation is what stops it feeling like a
  template.
- On screen text is the SPOKEN WORDS, four to six at a time, on the green plate
  in the lower third. That is the default. `--captions labels` switches to the
  guide's summary captions.
- The finished audio is Mike's VO alone. The original location audio is muted,
  not ducked, so nothing of the walkthrough track survives under the read.
- Scale the shot JUST enough to fill the 9:16 frame, Premiere's 178 percent on a
  16:9 clip, and no more. No punch ins. `zoom` above 1.0 exists for a genuine
  detail framing on a 1080p or better source, and even then stays modest.
- The source footage is usually handheld and already moves, so leave `pan` null
  and let the camera do the moving. A synthetic pan on top of a moving shot
  fights it.
- The exception is a LOCKED OFF camera. Mike often sets the camera down and talks
  to it, and a shot cut from that stretch sits dead still. If a take runs more
  than about six seconds with no camera movement in it, give it a `pan` across
  the room, roughly 0.25 of frame width. With no annotations to land on it drifts
  for the whole shot rather than settling early.
- `cta_source` is footage too, and it is the one range in the guide that is not a
  scene. Channel outros are exactly where burned in SUBSCRIBE and BELL graphics
  live, so check the frames before you pick it. The build warns if it overlaps an
  avoid_range, so put any burned in graphic you find into avoid_ranges.
- NEVER reuse footage, inside a Short or across the Shorts from one episode.
  Every second on screen should be a second the viewer has not already seen.
- Non overlapping timestamps are NOT enough. Mike often locks the camera off and
  talks to it for thirty seconds, so two scenes cut from that stretch overlap by
  nothing and still read as the same shot played twice. The build cannot catch
  this, only your eyes can: before you call a cut finished, look at the frame
  check sheet and ask whether any two tiles could be the same shot. If the camera
  did not move between two scenes, move one of them.
- THE HOOK ESTABLISHES A SPACE, not a detail. The first scene has to show a
  finished ROOM so the viewer knows where they are. A tight shot on a fireplace
  or a faucet is a detail, and details belong in the body.
  Remember the frame is vertical and most rooms are horizontal, so a wide of a
  living room does not survive the 9:16 crop, it just becomes a slice of wall. A
  kitchen, a bathroom, or a hallway does survive, because their content stacks
  up the frame: floor, cabinets, counter, uppers. Pick the room that reads
  tallest as the hook, even if it is not the room the Short opens on in the
  script.
- If two consecutive lines want the same shot, do NOT cut between them. Set
  `"continues_previous": true` on the second scene and the build renders both as
  ONE clip, with one pan carrying the whole take and the caption changing on
  time. Butting two separately rendered clips together is not enough, the join
  still shows when it lands mid action, for instance while a door is swinging.
  Let the action finish inside the shot. The build warns on REPEAT for
  overlapping footage and JUMP CUT for a cut that lands too close to itself.
- FRAME THE FEATURE, NOT THE TALKER. This is the note the channel has already
  given once, on a set of Shorts that got rejected for it. If the line is about
  the niche, the niche fills the window. Cropping 16:9 to 9:16 throws away two
  thirds of the picture, so the crop decides the whole shot.
- But do NOT contort the crop to erase Mike. A glimpse of him at the edge, a
  shoulder, an arm, a hand pointing, is fine and often helps. Pushing crop_x out
  to 0.16 or 0.84 purely to keep him out costs the room around the feature, and
  a slice of wall with no context is worse than a good frame with him in the
  corner. Pick the framing that shows the feature best, then check he has not
  become the subject of it. Feature centre stage, Mike at the edge.
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
python scripts/fetch_transcript.py <slug> --source work/<slug>/source.mp4   # local master
```

Whisper runs FIRST and it is the tier you want. YouTube's auto captions arrive
with no punctuation and mangle trade words, and every guide written from them
inherits that. Whisper returns sentences, punctuation, and word level timings,
which is what the shot anchoring in step 7 runs on. The caption tiers are only
a fallback when the audio cannot be got hold of.

It saves `transcripts/[video_id].json` and prints the path. The `source` field
records which tier was used, confirm it says `faster-whisper`. Read that JSON
and work only from it.

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

## Step 3: ONE Short per episode, a reveal tour

One URL in, one Short out. The two Short funnel is retired.

The format is in the `remodel-king-shorts` skill and it is not optional:
transformation line, homeowner context, the turn, then six to ten named
features one per line, and the end card carries the call to action. Plain prose,
145 to 175 words, 50 to 60 seconds.

The user can override the count or the angle per episode. Honour the override.

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
- `continues_previous`, true when this line shares the previous scene's take.
  The two render as one uninterrupted clip.

Two guide level fields matter to the build as well:

- `avoid_ranges`, a list of `{"range": "12:55 - 13:10", "reason": "..."}` for
  anything that must never appear in a Short, above all the cost segment. The
  build warns when a scene overlaps one.
- `voice_settings`, an override for this episode's read,
  `{"stability": 0.28, "style": 0.70, "similarity": 0.80}`. Lower stability and
  higher style make the delivery more animated. Leave it out to take the
  defaults, which are already tuned so the read does not sound flat.

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

For every scene the build writes TWO things into
`work/[video_id]/short[n]/frames/`:

- `sceneNN_candidates.jpg`, the one that matters. It holds every moment in the
  episode where Mike is talking about that feature, found by matching the VO
  line's content words against the whisper transcript, one tile per moment,
  each stamped with its timestamp and with the 9:16 window drawn on. Mike
  narrates while he points, so the frames around the words are the frames that
  show the thing.
- `sceneNN_1..4.jpg`, four stills from whatever range the guide named.

**Read the candidate strip first.** Pick the tile that shows the FEATURE, write
its timestamp into `source`, then set `crop_x` so the feature sits inside the
window and Mike sits outside it. If none of the tiles show the feature, widen
the search yourself: grab frames every half second across the window with ffmpeg
and look again. Two seconds either side of a pick is often the difference
between the lit mirror and a blurred wall.

Do not fill in numbers you have not looked at. For each scene write:

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

Read the contact sheet before you tell the user it is done, and check every
single tile. If a crop landed on Mike instead of the feature, if a tile shows a
blurred camera swing, or if a caption sits over a face, fix the numbers and
rebuild. A tile that is "close enough" is the thing that got a set of Shorts
rejected.

The build writes `output/[slug]-short-[n]-PUBLISH.mp4` alongside the master.
That is the file to send and the file to upload: CRF 20 capped at 3.5 Mbps, so
a 60 second Short lands around 20 to 26MB, under the 30MB chat limit and well
above what YouTube keeps. Send it with SendUserFile.

Send it, do not just name the path. `output/` is gitignored and the container is
reclaimed after the session, so a path is not a deliverable.

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
