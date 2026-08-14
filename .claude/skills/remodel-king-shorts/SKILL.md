---
name: remodel-king-shorts
description: Turn a full YouTube episode transcript from The Remodel King into a ready-to-use YouTube Shorts package, a voice script already formatted for ElevenLabs synthesis plus an edit map of episode timestamps for finding footage in Premiere Pro. Use this skill whenever the user pastes an episode transcript and asks for a Shorts script, says anything like "Here is the transcript for [EPISODE NAME] create a youtube short script ready", mentions making a Short from an episode, or asks for an alternate/reworded version of a previous Shorts script. Trigger even if they only paste a renovation episode transcript with a brief request attached.
---

# Remodel King Shorts

Convert one episode transcript into one vertical Short: a spoken VO script in
Mike's voice, plus an edit map the editor can cut from.

## Trigger

The user pastes an episode transcript and asks for a Short. Typical phrasing:

> Here is the transcript for [EPISODE NAME] create a youtube short script ready

Any paste of a renovation episode transcript with a request for a Short,
a Shorts script, or a reworded alternate of a previous script counts.

## Output

Exactly two things: the Shorts VO script, then the edit map. Nothing else.
No titles, no descriptions, no hashtags, no thumbnail ideas, no strategy notes,
unless the user asks for them.

## The script

- Under 60 seconds spoken. Roughly 110 to 140 words.
- First person, Mike's voice. "I ripped out...", "we went with...",
  "I could not believe what was behind that wall".
- Every fact comes from the transcript. Never invent a material, brand,
  measurement, timeline, or number that is not in the source.

### Structure

Follow this beat order every time. Never label the sections in the output.

1. **Visual preview hook**, 2 to 3 seconds. The opening line that earns the
   scroll stop. It must be worded differently from the line that follows it,
   never a restatement of the before-state hook.
2. **Before-state hook.** What was wrong with the space.
3. **Transition and reveal.** The turn from old to new.
4. **Feature showcase.** Specific upgrades, pulled only from transcript facts.
5. **Closing payoff.** An emotional beat or a non-cost stat.
6. **Follow CTA.** Short, natural, in Mike's voice.

### Hard rule on cost

NEVER use project cost or budget as the closer. Mike reveals cost with end
slides he builds manually. Do not put a price in the payoff, do not tease a
price, and do not flag a missing cost figure as a problem with the script.

### Footage constraint

Mike's footage is only ever:

- pre-demo walkthroughs
- progress STATE shots (the room mid-project, sitting still)
- final reveals

He never films workers and never films active construction. Narration like
"we gutted it" is fine, but it must play over a state shot. The edit map must
never suggest footage of demo happening, installation happening, or anyone
working. If a beat seems to call for action footage, hold on a state shot or a
reveal instead.

### When highlight footage is limited

Use fewer, longer lines that hold over reveal footage. Do not write many quick
lines that imply cuts the editor cannot make.

### A/B alternates

When the user asks for an alternate, keep the same clip order and the same
visual beats, reword the narration entirely, and keep the existing edit map
valid. The alternate is a new read over the same cut.

## ElevenLabs formatting

Apply the formatting directly in the script text. It is a synthesis script,
not a clean-read script.

- Strategic ALL CAPS on roughly 10 to 15 percent of words: numbers, materials,
  outcomes, punch words.
- Ellipses before reveals, with no space after the ellipsis. Like this...THAT
  is what changed everything.
- 3 to 5 exclamation points across the whole script.
- Occasional rhetorical questions.
- Staccato short sentences for impact, commas for flow.
- Natural enthusiasm, not hype. Mike sounds like a contractor who is proud of
  the work, not an ad read.

## Script formatting rules

- Plain prose only. No labels, no clip cues, no markdown, no bullets,
  no quotation marks around the script.
- Paragraph breaks between beats are fine and encouraged.
- Never use em dashes in ANY output, ever. Not in the script, not in the edit
  map, not in the surrounding text. Use commas, periods, or ellipses.

## Edit map

After the script, give a beat by beat map. For each beat:

- the abbreviated VO line (first few words, enough to locate it)
- the source timestamp range from the transcript
- what the frame shows, in state-shot or reveal terms

Flag any line where the footage may not exist, so the editor knows to check
before cutting.

## Output shape

1. The script, standing alone, first.
2. A separator.
3. The edit map.
4. At most one line offering an A/B alternate.

Nothing after that.
