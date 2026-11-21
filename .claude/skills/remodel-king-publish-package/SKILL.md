---
name: "remodel-king-publish-package"
description: "Build the full YouTube publishing package (titles, file names, descriptions, chapters, tags, playlists, end screen) for a finished Remodel King long video and its Short, from the video file itself."
---

# Remodel King Publish Package

Use this when a finished Remodel King long video (and optionally its Short) needs naming and publishing copy. Trigger phrases: "apply the SOP to [House Name]", "name this episode", "titles and descriptions for [House Name]", a Google Drive link to a finished episode, or a local .mp4 of a finished episode.

The Remodel King is Mike Hewett's home renovation YouTube channel (@theremodelking). Angela's team edits, names, and publishes. Mike approves everything before it goes Public.

## Rule zero: never guess the content

Never write a hook, title, or description from the house name alone. Always transcribe the actual video first. If the file cannot be reached, say so plainly and ask for the file or a transcript. Do not ask the user what is in the video when you can transcribe it.

## Step 1. Gather inputs

1. The finished long video. Either a local path or a Google Drive file link.
   - Drive download (works for files shared by link):
     `curl -sS -L --max-time 1200 -o long.mp4 "https://drive.usercontent.google.com/download?id=<FILE_ID>&export=download&confirm=t"`
   - Files are often 3 to 4 GB. Use a long timeout and run it in the foreground.
2. The project stats doc, usually "<House Name> Stats.docx" in the project's Raw folder on Drive (same parent folder as the video). It holds project type, original price, final price, square footage, and construction time. Read it, but NEVER put dollar figures or the timeline in any title, description, chapter, or thumbnail. They are the open loop paid off only in Mike's end slide. Square footage is fine to use.
3. The house name from Mike's email or folder name (for example "Wagner - The Angle House" means the house name is The Angle House). If Mike says it differently on camera, flag the mismatch for the user.

## Step 2. Transcribe with timestamps

```bash
ffmpeg -v error -i long.mp4 -vn -ac 1 -ar 16000 audio.wav
ffprobe -v error -show_entries format=duration -of csv=p=0 long.mp4
pip install --break-system-packages -q faster-whisper
```

Script (loads audio as numpy, which avoids a PyAV version error inside faster-whisper):

```python
import sys, wave, numpy as np
from faster_whisper import WhisperModel
m = WhisperModel("small.en", device="cpu", compute_type="int8")
w = wave.open(sys.argv[1])
a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
segs, _ = m.transcribe(a, vad_filter=True, beam_size=1)
with open(sys.argv[2], "w") as f:
    for s in segs:
        mm, ss = divmod(int(s.start), 60)
        f.write(f"[{mm}:{ss:02d}] {s.text.strip()}\n")
```

A 24 minute episode takes about 3 to 4 minutes on 2 CPUs. Read the whole transcript before writing anything.

## Step 3. Verify anything visual before claiming it

If a hook or feature depends on how something looks (a color, a material, an on-screen label), grab a frame and look at it:

`ffmpeg -v error -ss MM:SS -i long.mp4 -frames:v 1 -vf scale=640:-1 -y frame.jpg`

Example: Mike said the client's favorite color is pink, but the bath table on screen was wood with a red stripe and the on-screen label said "CUSTOM BATH TABLE". The hook used the label, not "pink". Prefer the wording of on-screen labels Angela already added.

## Step 4. Pick two different hooks

The long video and the Short each get their own hook and their own title. The only thing they share is the house name at the end.

- Long video hook: the single most surprising thing in the project, said plainly. It should match the 15-second intro's first voiceover line (usually at 0:00 in the transcript), because the hook leads the title, the intro voiceover, and the thumbnail. If the house name sets up a twist, use it (The Angle House: "We Took Every Angle Out of This Bathroom", from Mike's line "We call this angle house, but there's no more angles").
- Short hook: a different specific feature, ideally something personal or handmade (The Angle House Short: "I Built My Client a Custom Bath Table"). Tell the user the Short's script must open on that feature in the first 2 seconds.
- Model of a good hook: "Car Wash Shower". Generic hooks ("Stunning Makeover", "Dream Bathroom") are rejected.
- Shorts with over 100,000 views keep their current titles. Never retitle them.

## Step 5. Titles and file names

- Long video: `[Hook] | [Room] Remodel Before & After | The [House Name]`
- Short: `[Hook] | [Room] Before & After | The [House Name]`
- House name always last. 100 characters max. Hook inside the first 50 characters. Count characters with code, do not estimate.
- Put the main search phrase (for example "Master Bathroom Remodel") in the long video title so it matches playlist keywords.
- Projects with multiple parts use "Phase", never "Part" ("The Clubhouse Phase 2").
- File name = exact title with every "|" swapped for "-", plus ".mp4". Each video's file name matches its own title.

## Step 6. Long video description, in this exact order

Formatting rules for every description: no em dashes, no "•" bullets (YouTube breaks them), no double asterisks, no dollar figures, no timeline. Write for a viewer with zero context.

1. Opening line that starts with the main keyword phrase and names 1 to 2 standout features.
2. Cost line, word for word: "Watch until the end to discover the actual remodeling cost, including our original estimate versus the final price!" Only use this line if the video actually reveals both numbers. If it gives one number, rewrite the line so it does not promise an estimate versus final comparison.
3. "Welcome to The [House Name]!" (add ", Phase [#]" only when there is a phase) plus one line on scope (square footage, rooms).
4. Feature list, one "✅" line per upgrade, 6 to 10 lines, using words people search (walk-in shower, freestanding tub, heated tile floor).
5. Shop section:
```
🛒 SHOP THE PRODUCTS WE USE
The Remodel King Home Depot Storefront:
https://creators.homedepot.com/mypage/theremodelking
[One line listing the product types in this video]
```
6. "👍 LIKE this video and SUBSCRIBE to The Remodel King for more bathroom remodels, kitchen remodels, basement finishes, and whole house before-and-after transformations!"
7. "Which feature is your favorite? Tell us in the comments!"
8. Affiliate disclaimer, word for word: "AFFILIATE DISCLAIMER: As a Home Depot Creator, The Remodel King may earn a commission from qualifying purchases made through the links above. This helps support our channel at no additional cost to you."
9. Hashtags (Step 8).
10. Chapters at the very bottom (Step 7).

## Step 7. Chapters (long video only)

- A "CHAPTERS" line, then one chapter per line: `M:SS Chapter Name`.
- First line is 0:00. 5 to 10 chapters. Each at least 10 seconds. Times in order. 2 to 5 words each, using searchable words.
- Take times from the transcript of the final exported file. If the edit changes, recheck every time.
- Never name a chapter after the cost ("Final Cost", "What It Cost"). The cost is the open loop.
- Typical structure: Preview (0:00), [Room] Before, Demo or Rough-In work, any how-to segment, Reveal(s), standout feature chapters, closet or final walkthrough.

## Step 8. Hashtags

- 10 to 13 total, never more than 15.
- First: the strongest room tag (it shows above the title), for example #MasterBathroomRemodel.
- Then 5 to 8 project tags (#BathroomRemodelBeforeAndAfter #FreestandingTub #WalkInShower #HeatedTileFloor #HomeRenovation).
- Always end with all four: #TheRemodelKing #RemodelKing #FirstFlipChallenge #InvestorSecretNetwork
- Short hashtags: room tags first, then #BeforeAndAfter, then the same four at the end.

## Step 9. Tags, category, playlists, end screen

- Tags: "add these to the 12 channel default tags", then 5 to 10 video tags (room, standout features, house name). The Short uses the same tags.
- Category: Howto & Style for every remodel long video and Short. Hard Hats & High Limits podcast episodes and the community workshop video stay People & Blogs.
- Playlists (long video only, usually 2 to 3; a Short NEVER goes in a playlist). Use names exactly:
  - Bathroom Remodel Before and After, Start to Finish
  - Kitchen Remodel Before and After, Open Concept
  - Basement Finishing Before and After
  - Fireplace Remodel Before and After, Gas or Electric
  - Whole House Renovation Before and After
  - Remodel Cost Breakdown, Real Contractor Prices (when the video reveals cost)
  - Remodeling How To: Heated Floors, Windows, and Window Wells (only when the video teaches an install)
  - Finished Projects (only when the project is finished in this video)
  - The house's own playlist if one exists (The Kennel House, The Clubhouse)
- End screen: one playlist element set to the single most relevant playlist (the one matching the main room and the title's search phrase; pick the more specific one if two fit) plus a Subscribe element, over the last 20 seconds, starting only after Mike's cost slide ends.

## Step 10. Short description, in this exact order (the only Shorts template)

```
[1 to 2 short hook paragraphs that start with the main keyword phrase]

Welcome to The [House Name]!

🔥 HERE'S WHAT CHANGED
✅ [feature, lead with the Short's hook feature]
✅ [5 to 7 lines total]

👉 WATCH THE WHOLE TRANSFORMATION
At the end of this Short, tap the full video at the bottom of your screen:
"[Long video's exact title]"
https://www.youtube.com/watch?v=[LONG VIDEO ID]

🛒 SHOP THE PRODUCTS WE USE
The Remodel King Home Depot Storefront:
https://creators.homedepot.com/mypage/theremodelking

👍 LIKE this Short and SUBSCRIBE to The Remodel King for more [room] remodels and before-and-after transformations!

AFFILIATE DISCLAIMER: As a Home Depot Creator, The Remodel King may earn a commission from qualifying purchases made through the links above. This helps support our channel at no additional cost to you.

[hashtags]
```

The Short teases the transformation and never shows or says the cost.

## Step 11. Deliver

Output one copy-paste package, each item in its own code block:

- Long video: Title (with character count), File name, Description (with chapters), Tags, Playlists, End screen playlist.
- Short: Title (with character count), File name, Description, Tags ("same as the long video"), Playlists ("none").
- Then a short "Before upload, check these" list covering only real open items, for example: a material or detail Mike states inconsistently on camera, a house name mismatch between Mike's email and his spoken name, the Short's opening shot must match its hook, replacing [LONG VIDEO ID] after the long video is uploaded, rechecking chapters if Mike requests edits.

Never use em dashes anywhere in the output.

## Publishing reminders to include only if asked for upload steps

- Upload the long video first, then the Short.
- Every video uploads Private and stays Private at least 48 hours until Mike approves. Send the private links to Mike (mike@kingllc.net) and Angie (angieh@saltlakecityhomebuyers.com).
- Audience: "No, it's not made for kids". Age restriction: No.
- Altered content: Yes for every Short (AI voiceover of Mike) and for any long video with an AI intro voiceover.
- Short: set Related video to its long video. A Short is not done until this is set. Publish the Short only after the long video is Public.
- Thumbnails and Short covers carry the hook on green (#0E9346) pills, white uppercase Oswald Bold, no dollar figures.
- Full SOP: https://claude.ai/artifact/MqmbyMaYwxsnRruHydrmT8