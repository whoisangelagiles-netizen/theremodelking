---
name: remodel-king-shorts
description: Write a YouTube Shorts VO script for The Remodel King from a full episode transcript, in the channel's reveal tour format, plus the edit map of source timestamps for the picture. Use whenever the user pastes an episode transcript and asks for a Shorts script, says anything like "Here is the transcript for [EPISODE NAME] create a youtube short script ready", mentions making a Short from an episode, or asks for an alternate reworded version of a previous Shorts script. Trigger even if they only paste a renovation episode transcript with a brief request attached.
---

# The Remodel King, Shorts script

One episode in, ONE Short out. The channel publishes one Short per episode.

## Trigger

> Here is the transcript for [EPISODE NAME] create a youtube short script ready

## Output, and nothing else

1. The VO script, ready to paste into ElevenLabs.
2. The edit map: source timestamp per line, and what the picture shows.

No titles, descriptions, hashtags, or thumbnail ideas unless asked. Close with a
one line offer of an A/B alternate, same cut, entirely reworded narration.

## The format: a reveal tour

This is the format Mike signs off on. It is not a problem and solution funnel
and it is not a hook question. It is a walk through the finished room, naming
one upgrade at a time.

```
1. The transformation, in one sentence.
   "This master bathroom went from dated to a total showpiece."
2. Who it was for and why it looks the way it does, one or two sentences.
   "They love mountain climbing, so the whole bath was built around red rock colors."
3. The turn.
   "And we completely transformed it."
4. Then the features, six to ten of them, one per line, in the order a person
   walking the room would meet them. Every line names a real thing:
   a material, a mechanism, or the benefit it buys.
5. Nothing else. The end card carries the call to action, the VO does not.
```

## How the read sounds

Warm, unhurried, a contractor showing a friend around. The features do the
work, so the delivery does not have to push.

- **Plain prose.** No ALL CAPS emphasis markers, no stacked exclamation points,
  no rhetorical questions. The old spec asked for those. Mike does not want them.
- 145 to 175 words, which lands at 50 to 60 seconds.
- First person for the work, "we tore out", "we turned". Third person for the
  homeowner, "they love", "she found".
- Every fact from the transcript. Never invent a material, a brand, or a number.
- Never an em dash, anywhere, ever.
- Some words the voice model reads wrong. The build respells them on the way to
  ElevenLabs and puts the real spelling back on screen, "niche" is sent as
  "nitch". Write the real word, the pipeline handles it.

## Line length sets the cut

One line, one shot. A 20 word line is a seven second shot, which is a long time
to hold one frame on a phone. Keep lines to 8 to 15 words and the cutting rhythm
comes out right on its own. Do not aim for a fixed shot length, and do not make
every shot the same length, the variation is what stops it feeling like a
template.

## Footage rules, absolute

- **Frame the feature, not the talker.** If the line is about the niche, the
  niche fills the frame. Mike is the narrator, not the subject. A Short where
  the camera keeps landing on him is the failure, and it is the note the channel
  has already given once. A glimpse of him at the edge is fine though, do not
  push the crop to an extreme just to erase him, that costs the room around the
  feature.
- Mike's footage is ONLY pre demo walkthroughs, progress state shots, and final
  reveals. He never films workers or active construction. "We gutted it" is fine
  as narration but it plays over a state shot.
- **The finished house carries the Short.** Before footage is the hook and at
  most one beat after it. Everything else is the reveal.
- **NEVER close on cost.** Mike builds cost reveals as end slides by hand. Do
  not treat a missing cost as a gap, and fence off the price segment in
  `avoid_ranges` so no scene can land on it.
- Never reuse footage, and non overlapping timestamps are not enough. Two scenes
  cut from one locked off camera read as the same shot twice even though they
  share no frames. If the camera did not move between them, move one.
- The hook establishes a ROOM, not a detail. The frame is vertical and most rooms
  are not, so pick the space whose content stacks up the frame, a kitchen or a
  bathroom, rather than a wide of a living room that crops down to a slice of wall.
- If two consecutive lines want the same shot, do not cut
  between them, mark the second `continues_previous` and they render as one take.
- Never put captions, words, or graphics over Mike's face.

## The look, for reference

Captions are the spoken words, four to six at a time, white Montserrat ExtraBold
on a solid green plate sitting on a fixed baseline in the lower third. The end
card is a stack of tilted stickers over live footage, "Follow / for more /
before / and afters", with the handle in a pill underneath. `scripts/build_short.py`
draws all of it. Do not describe caption styling in the edit map.

## Then what

If the user wants the finished video rather than the script, use the
`shorts-production-guide` skill: it writes the guide JSON, fetches the whisper
transcript, and runs the build.
