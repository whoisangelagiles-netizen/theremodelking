# assets/

Branded media the finishing pipeline composites into every Short. Drop the
files in with these exact names. Nothing here is generated, all of it comes
from you.

Commit these files so they survive into a fresh session. Keep the overlays
short and trimmed, ProRes 4444 is heavy and a 3 second bug is all the pipeline
needs.

## Files to upload

| File | What it is | Format |
| --- | --- | --- |
| `overlays/*.mov` | Branded overlay animations, logo bug, lower third, badge, whatever you want composited over a scene | ProRes 4444 with alpha, 1080x1920 preferred, any name you like |
| `whoosh.wav` | Transition swoosh, fires at the problem-to-solution shift | wav or mp3, roughly 0.4 to 1.0 seconds |
| `impact.wav` | Impact hit, lands on frame one of the hook | wav or mp3, short and punchy |
| `music.mp3` | Optional music bed, sits very low under the VO | mp3, wav, or m4a, longer than any Short, it loops |

Overlays are referenced by filename from the guide JSON, per scene:

```json
{ "number": 4, "overlay": "logo_bug.mov", "notes": "..." }
```

The pipeline looks in `assets/overlays/` first, then `assets/` directly, and
matches on stem so `whoosh.mp3` works in place of `whoosh.wav`.

## Fallbacks when a file is missing

Nothing here is required. A missing file never stops a build, it just prints a
line saying what got skipped:

| Missing | What happens |
| --- | --- |
| An overlay `.mov` | That scene renders without the overlay, everything else is unchanged |
| `whoosh.wav` | The transition plays clean, no swoosh |
| `impact.wav` | The hook lands with no impact hit |
| `music.mp3` | No music bed, VO and ducked location audio only |

Pass `--no-music` to skip the bed even when the file is present, or
`--music path/to/other.mp3` to use a different one for a single build.

## Levels the pipeline uses

| Layer | Level |
| --- | --- |
| Mike AI VO | full |
| Original location audio | ducked to 3 percent, present but very low |
| Impact | 70 percent |
| Whoosh | 55 percent |
| Music bed | 6 percent |

The mix is limited at 0.95 so the stack never clips.
