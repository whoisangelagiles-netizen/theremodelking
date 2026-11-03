---
name: youtube-publish-package
description: The end to end SOP that turns one long Remodel King body video into everything needed to post it on YouTube, then files it on Google Drive in the house layout. Runs the long intro, the text touches, one Short, titles and descriptions, then builds the episode folder under Mike Hewitt with a Long Video (Manual Upload) folder, the long video's title and description Doc, and a Short subfolder with the Short, its thumbnail and its title and description Doc. Use whenever the user says "Let's process this long video to be posted into youtube", or hands over a body video link and asks for the whole process, the full package, or the YouTube folder.
---

# YouTube Publish Package, the SOP

**Trigger:** "Let's process this long video to be posted into youtube" plus a Drive
link to the body video (or the project folder holding it).

One body in, one Drive folder out. Every step below already has its own skill;
this SOP runs them in order and files the results. Do not change how any of
them work from here.

## The Drive layout, every episode

Under the parent folder **Mike Hewitt**
(`1ouQYxq3BO-bshx7H5a-VUL9QzPL_ulGj`):

```
[YouTube title of the long video]/
    Long Video (Manual Upload)/          the user uploads the finished long video here
        [slug]-intro.mp4                 the pieces the editor assembles it from
        [slug]-finish-package.zip
    Long Video Title and Description     Google Doc
    Short/
        [slug]-short.mp4
        [slug]-short-thumbnail.jpg
        Short Title and Description      Google Doc
```

The episode folder is named with the long video's YouTube TITLE, exactly as it
will be posted. If the title changes later, rename the folder to match.

The long video itself is never built or uploaded by this SOP. The user decided
on **pieces only**: the intro and the text touches package go in the manual
upload folder, the editor assembles and exports the final, and the user uploads
it there by hand.

## Step 1: get the body

Read the Drive link with `get_file_metadata`. If it is a folder, list it and
find the body and any project photos and the stats deck, the way the
long-video-intro skill describes. Probe the body (1920x1080, 30 fps expected)
and download it once into `work/[slug]/body/body.mp4`. Transcribe it into
`transcripts/[slug]-body.json`, then read ALL of it before writing anything.

Slug is the episode's short working name, `heated-floor`.

## Step 2: look at the whole body

Tile it at one frame every 5 seconds and look at every sheet. Decide, and tell
the user plainly up front:

- Is this a transformation (reveal tour Short) or a how to (process Short)?
- How much finished footage is there, and is the thing the episode is about
  actually shown finished?
- Where is the price said, are there stats slides, burned in subscribe graphics.
- Anything Mike says on camera that contradicts itself (a wrong phase, a wrong
  room) that a viewer will catch.

## Step 3: the four builds

Run each with its own skill, in this order, and check each with your eyes
before moving on:

1. **Intro**, `long-video-intro`. 10 to 15 seconds, tease the cost and time
   that the body actually pays off, never more than it pays off.
2. **Text insides**, `long-video-finish`. Light, one touch every 1.5 to 2
   minutes, never on Mike's face or on the editor's own graphics.
3. **One Short**, `shorts-production-guide` with `build_short.py`, using the
   local body as the source. Under 60 seconds. No footage repeated. Never the
   price.
4. **Titles and descriptions**, written last, from what the builds actually
   show:
   - Long title, longtail homeowner search phrase, plus two alternates.
   - Long description, first person, what the viewer learns, a nudge to stay
     for the cost, chapters offset by the intro length, a comments ask,
     hashtags. Chapter times are against the body plus intro, flag that they
     need a recheck after the editor's final cut.
   - Short title plus two alternates. Short description, two short paragraphs,
     the last one pointing to the long video title, hashtags with #shorts.
   - All the copy rules hold: plain prose, no ALL CAPS, no em dashes anywhere.

## Step 4: the publish spec

Write `publish/[slug].json`, see `publish/heated-floor.json`:

| Field | What |
| --- | --- |
| `long.title`, `long.alternates`, `long.description`, `long.notes` | The Doc for the long video |
| `long.pieces` | `output/[slug]-intro.mp4`, `output/[slug]-finish-package.zip` |
| `short.title`, `short.alternates`, `short.description`, `short.notes` | The Doc for the Short |
| `short.video` | `output/[slug]-short-1-PUBLISH.mp4` |
| `short.thumbnail` | `output/[slug]-short-1-COVER.jpg` |
| `parent_folder_id` | Mike Hewitt, leave as is unless the user names another |

## Step 5: file it on Drive

```bash
python scripts/publish_drive.py publish/[slug].json
```

It builds the whole layout, uploads the files with resumable uploads, and writes
both Docs. Reruns are safe, so after any fix just run it again: folders and Docs
are found by name and reused, and files already there at the same size are
skipped.

**If the credentials are missing** (it stops on `GOOGLE_DRIVE_CLIENT_ID is not
set`), do not stop the job. Make the folders and both Docs with the Google Drive
connector (`create_file`, folder mime type for folders, `textContent` for the
Docs so they convert), using the exact names above. Send the Short and the
thumbnail with SendUserFile, and tell the user those two are waiting on the
setup below. The script picks up the same folders and Docs by name when it
does run.

## Step 6: hand off

- Send the Drive folder link.
- Send the intro, the finish package and reel, the Short and its cover with
  SendUserFile as well. `output/` does not survive the session.
- Commit every spec (`intros/`, `finishes/`, `guides/`, `publish/`, the
  transcript) and open the draft PR.
- Lead the message with what is weak and what needs a decision, then what was
  made. The user wants the weak spots challenged, not a victory lap.

## Setup, once, for the uploads

The Drive connector cannot carry a video, so the upload script signs in as the
user with an OAuth refresh token. Three values, all kept out of the repo:
`GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`,
`GOOGLE_DRIVE_REFRESH_TOKEN`.

1. In Google Cloud Console, project angela-giles: APIs and Services, enable
   the **Google Drive API**.
2. OAuth consent screen: External, add whoisangelagiles@gmail.com as a user,
   then **Publish app** so it reads **In production**. Left in Testing, Google
   kills the refresh token after 7 days and the uploads break every week. An
   unverified app is fine for your own account, you click through one warning.
3. Credentials, Create credentials, OAuth client ID, type **Desktop app**. Copy
   the client ID and secret.
4. On your own computer, in a clone of this repo:

   ```bash
   pip install requests
   GOOGLE_DRIVE_CLIENT_ID=... GOOGLE_DRIVE_CLIENT_SECRET=... python scripts/publish_drive.py auth
   ```

   Sign in as whoisangelagiles@gmail.com, allow Drive, and it prints
   `GOOGLE_DRIVE_REFRESH_TOKEN=...`.
5. Paste all three into the cloud environment's environment variables, the
   same box that holds the ElevenLabs key. New sessions pick them up.

The service account claude-sheets@angela-giles.iam.gserviceaccount.com is not
used for this: service accounts have no Drive storage of their own, so they
cannot upload into a My Drive folder.
