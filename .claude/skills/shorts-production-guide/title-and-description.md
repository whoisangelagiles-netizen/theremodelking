# Remodel King Short: title and description

Run this after the Shorts script is done. The deliverable is ONE copy-paste
block: Title, then Description. Nothing else.

The build writes it to `output/[slug]-short-[n]-title-description.md` from the
guide, and `python scripts/title_description.py guides/[slug].json [n]` writes it
on its own. You write four things into the Short in the guide; the script adds
the CTA, the episode link, the boilerplate and the hashtags, and checks the hard
rules. Fix every `FIX:` line it prints before handing the block over.

```json
"yt_title": "See the Basement That Was Never Part of the Flip | Dated House to Dream Home in 4 Weeks",
"yt_description": {
  "hook": "One or two punchy lines restating the on screen hook.",
  "project": "What the house was, where it was, how long the work took.",
  "features": "Specific materials and fixtures, not adjectives.",
  "subject": "basement"
}
```

`subject` fills the CTA: "Want to see the full [subject] before and after and
find out what it cost?"

## Inputs
- The on screen hook text, `cover_hook`.
- The full episode title and its YouTube URL, `video_title` and `video_url`.
- 3 to 5 concrete features shown in the Short.

## Title, exactly one, no alternatives
Format: `[On screen hook, as written] | [Longtail keywords tied to the full episode]`
- The front half mirrors the hook word for word so the thumbnail and the title
  reinforce each other. The script checks it against `cover_hook`.
- The back half carries search keywords: room type, before and after, house
  flip, timeframe.

## Description
Written for someone with zero context on the episode. Short conversational
paragraphs, 1 to 3 sentences each.
1. Open on the hook, one or two punchy lines.
2. Name the project: what the house was, where, how long the work took. Only
   facts from the transcript. If the transcript does not say where, leave it out.
3. The standout features, specific materials and fixtures.
4. CTA, added by the script: watch the whole transformation and find out what
   it cost, then the full episode link on its own line.
5. Home Depot affiliate boilerplate, added verbatim by the script.
6. Hashtags on one line, the guide's `hashtags` plus #FirstFlipChallenge and
   #InvestorSecretNetwork, always.

## Hard rules, checked by the script
- No em dashes anywhere.
- No bullet characters. YouTube strips them, every list line is `- `.
- No cost figures. The CTA promises the cost, the full video delivers it.
- Longtail keywords in the body, not keyword stuffing.
- Never "follow for more before and afters". That CTA is retired.
