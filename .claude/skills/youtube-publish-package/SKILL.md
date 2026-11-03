---
name: youtube-publish-package
description: The end to end SOP that turns one long Remodel King body video into everything needed to post it on YouTube, filed on Google Drive in the house layout, in two stages. Stage 1, triggered by "Let's process this long video to be posted into youtube" plus the body link, builds the intro, the text touches and one Short, and files the episode folder under Mike Hewitt with the pieces and the Short subfolder (Short, thumbnail, title and description Doc). Claude makes the folders and Docs, the user uploads the video and image files. Stage 2, triggered when the user sends the Drive link of the FINAL long video they uploaded, writes the long video's title, description and real chapters from that final cut and makes the long thumbnail in the channel's green plate look. Use for either trigger, or whenever the user asks for the whole YouTube process, the package, the YouTube folder, or the long video's title, description or thumbnail.
---

# YouTube Publish Package, the SOP

Two stages, because the long video's chapters, title and description must come
from the FINAL cut, and that only exists after the editor assembles it.

| Stage | Trigger | Makes |
| --- | --- | --- |
| 1 | "Let's process this long video to be posted into youtube" + the body link | intro, text touches, one Short, Short title, description and thumbnail, the episode folder |
| 2 | the Drive link of the final long video, once the user has uploaded it | long title, description with real chapters, long thumbnail |

## The Drive layout, every episode

Claude makes the folders and the Docs. The user uploads every video and image
file by hand, there is no upload sign in to maintain. Under the parent folder
**Mike Hewitt** (`1ouQYxq3BO-bshx7H5a-VUL9QzPL_ulGj`):

```
[Episode working name]/                  e.g. "Heated Floor", never the YouTube title
    Long Video (Manual Upload)/          stage 1: the intro and the touches package
        [the final long video]           the user uploads it here by hand
    Long Video Title and Description     stage 2, Google Doc
    [slug]-long-thumbnail.jpg            stage 2
    Short/                               stage 1
        [slug]-short.mp4
        [slug]-short-thumbnail.jpg
        Short Title and Description      Google Doc
```

The folder is named with the episode's working name, because the folder has to
exist before the title is written and a title can change after posting. The
YouTube title lives only in the Doc.

This SOP never builds or uploads the finished long video. The editor assembles
it from the pieces and the user uploads it.

## Stage 1

### 1. Get the body

Read the Drive link with `get_file_metadata`. If it is a folder, list it and
find the body and any project photos and the stats deck, the way the
long-video-intro skill describes. Probe the body (1920x1080, 30 fps expected)
and download it once into `work/[slug]/body/body.mp4`. Transcribe it into
`transcripts/[slug]-body.json` and read ALL of it before writing anything.
The slug is the working name, `heated-floor`.

### 2. Look at the whole body

Tile it at one frame every 5 seconds and look at every sheet. Decide, and tell
the user plainly up front:

- Is this a transformation (reveal tour Short) or a how to (process Short)?
- How much finished footage is there, and is the thing the episode is about
  actually shown finished?
- Where is the price said, are there stats slides, burned in subscribe graphics.
- Anything Mike says that contradicts itself (a wrong phase, a wrong room) that
  a viewer will catch.

### 3. The three builds

Run each with its own skill, in order, and check each with your eyes:

1. **Intro**, `long-video-intro`. 10 to 15 seconds, tease only what the body
   pays off.
2. **Text insides**, `long-video-finish`. Light, never on Mike's face or on the
   editor's own graphics.
3. **One Short**, `shorts-production-guide` with `build_short.py`, local body as
   the source. Under 60 seconds, no repeated footage, never the price.

Then the **Short's copy**: title plus two alternates, a two paragraph
description whose last line points to the long video, hashtags with #shorts.
The Short's cover from the build is its thumbnail.

### 4. File it

With the Google Drive connector, using the exact names in the layout above:
the episode folder under Mike Hewitt, `Long Video (Manual Upload)` and `Short`
inside it (`create_file`, folder mime type), and the `Short Title and
Description` Doc inside `Short` (`create_file` with `textContent` as HTML and
`contentMimeType` `text/html`, so it converts to a Google Doc; read it back once
to check). Reuse a folder or Doc that already exists by that name rather than
making a second one.

The user uploads every video and image file by hand, so send them all with
SendUserFile and say where each one goes:

- `[slug]-intro.mp4` and `[slug]-finish-package.zip` into Long Video (Manual Upload)
- the Short's `PUBLISH.mp4` and its `COVER.jpg` into Short

`output/` does not survive the session, so the files in chat are the only copy.
Lead with the weak spots, then the folder link. Tell the user stage 2 starts
when they send the final long video's link.

## Stage 2

### 1. The final cut

Probe the final long video over HTTP and stream only its audio, never download
the picture unless a thumbnail frame is needed from it:

```bash
python scripts/fetch_drive.py --audio work/[slug]/final/audio.m4a <final id>
python scripts/transcribe_audio.py work/[slug]/final/audio.m4a
```

Compare it with the body transcript: what the editor cut, where the intro ends,
whether anything moved.

### 2. Chapters from the final, not the body

Chapter times come from the final's own transcript, at the first word of each
section. Start at 0:00, at least three chapters, each at least 10 seconds long,
which is what YouTube needs to show them. Name them the way the text touch
chapters are named. Where the price is spoken, a "What it cost" chapter is
fine, it tells the viewer where the payoff is without saying it.

### 3. Title and description

- Title: a longtail homeowner search phrase, under about 70 characters, plus
  two alternates. Never the price in the title.
- Description: first person in Mike's voice, what the viewer will learn, a
  nudge to stay for the cost, the chapters, a comments ask, hashtags.
- Plain prose, no ALL CAPS, no em dashes anywhere.

### 4. Long thumbnail

The channel's look, matched to the Basement Finish, Master Bathroom Remodel and
Jack and Jill thumbnails: frame full bleed, green band top and bottom, a green
plate a little below centre with a two to four word label in white underlined
capitals.

```bash
python scripts/long_thumbnail.py work/[slug]/body/body.mp4 5:44 "Heated floor install" --out output/[slug]-long-thumbnail.jpg
```

Pick the frame by eye, from the body or the project photos: the finished room,
nobody in it, nothing important behind the plate. Render two or three and show
them. If the episode never shows the finished thing cleanly, say so and pick the
most striking frame there is. The label names the project type the way the
channel does: "Basement finish", "Master bathroom remodel".

### 5. File it

Write the `Long Video Title and Description` Doc into the episode folder with the
connector, the same way as the Short's, rewriting any draft of that name. Send
the thumbnail with SendUserFile for the user to upload into the episode folder.
