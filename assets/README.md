# assets/

Branded media the finishing pipeline burns into every Short. Drop files in with
these exact names. Nothing here is generated, all of it comes from you.

Commit these files so they survive into a fresh session.

## The one file to upload

| File | What it is | Format |
| --- | --- | --- |
| `logo.png` | Channel logo, composited as a watermark in the TOP RIGHT of every scene and the CTA frame | PNG with a transparent background. Any filename containing "logo" is found, so `KCS Logo.png` works as is |

Specs that work best:

- Transparent PNG, no white box behind the mark.
- At least 400px wide, 600 to 1000px is ideal. It gets scaled down to about
  173px wide in the 1080x1920 frame, so give it room to stay crisp.
- Trim the empty space around the mark before exporting, padding inside the
  file pushes the logo away from the corner.
- Light or white marks read best. The pipeline drops a soft shadow behind it so
  it holds up over bright reveal footage.

It sits 40px in from the right and 52px down from the top, which clears both
the YouTube UI and the hook caption. Width is automatic: up to 16 percent of
the frame, but never enlarged past the mark's native pixels, so a small file
renders crisp rather than soft. Override with `--logo-width`, adjust
`--logo-opacity` (default `0.92`), or drop it with `--no-logo`.

## Things you supply per Short

| What | Where it goes | Format |
| --- | --- | --- |
| **A narration file you recorded** | anywhere, pass it with `--vo path/to/file.mp3` | mp3, wav, or m4a. One continuous read of the script, start to finish |
| **The end card animation** | `assets/end_card.mov` (or `.webm`, `.mp4`) | 1080x1920. **With** an alpha channel it lays over the last shot, the way the drawn stickers do. **Without** one it plays as its own closing clip |

### The narration file

It is used exactly as you recorded it. Nothing is cut, trimmed, retimed, or
resynthesized. The build transcribes it with whisper only to find where each
script line falls, then cuts the picture to those moments, so the words and the
frames land together and the read stays one unbroken take.

```bash
python scripts/build_short.py <url or master> 1 --vo ~/Downloads/sugar-house-vo.mp3
```

Read the script straight through, in order, without stopping between lines. If
you change the wording as you read, change it in the guide too, otherwise the
line matching drifts and the build says so.

### The end card animation

Name it `end_card` and drop it in `assets/` or `assets/overlays/`. The build
finds it by name and uses it instead of drawing the sticker stack.

- **With alpha** (ProRes 4444 `.mov`, or VP9 `.webm` in `yuva420p`): it is
  composited over the tail of the last shot, so the picture keeps running
  behind it. This is what the current drawn end card does and it is the better
  look.
- **Without alpha** (a normal `.mp4`): it plays as its own clip after the last
  shot, at its own length, letterboxed if it is not 1080x1920.

Either way the length of the animation sets the length of the end card, and the
logo watermark still goes on top.

## Optional extras

| File | What it is | Format |
| --- | --- | --- |
| `whoosh.wav` | Transition swoosh, fires at the problem to solution shift | wav or mp3, roughly 0.4 to 1.0 seconds |
| `impact.wav` | Impact hit, lands on frame one of the hook | wav or mp3, short and punchy |
| `music.mp3` | Music bed, sits very low under the VO | mp3, wav, or m4a, it loops to fit |
| `overlays/*.mov` | Animated branded overlays composited over a named scene | ProRes 4444 with alpha, 1080x1920 |

Animated overlays are referenced by filename from the guide JSON, per scene,
and are separate from the always-on logo watermark:

```json
{ "number": 4, "overlay": "logo_bug.mov", "notes": "..." }
```

The pipeline looks in `assets/overlays/` first, then `assets/` directly, and
matches on stem, so `whoosh.mp3` works in place of `whoosh.wav`.

## Fallbacks when a file is missing

Nothing here is required. A missing file never stops a build, it just prints a
line saying what got skipped:

| Missing | What happens |
| --- | --- |
| `logo.png` | No watermark, everything else is unchanged |
| `whoosh.wav` | The transition plays clean, no swoosh |
| `impact.wav` | The hook lands with no impact hit |
| `music.mp3` | No music bed, VO and ducked location audio only |
| An overlay `.mov` | That scene renders without the overlay |

Run `python scripts/check_setup.py` to see exactly what is present and what is
missing.

## Levels the pipeline uses

| Layer | Level |
| --- | --- |
| Mike AI VO | full |
| Original location audio | muted, pass `--location-audio 0.03` to bring it back as a low bed |
| Impact | 70 percent |
| Whoosh | 55 percent |
| Music bed | 6 percent |

The mix is limited at 0.95 so the stack never clips.
