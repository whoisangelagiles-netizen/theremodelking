# End card and thumbnail, the approved look

Both are locked to approved references. The build renders them; this file is
what to check them against. Numbers here were MEASURED off the approved files,
and where an earlier written spec disagreed with the files, the files win.

References:
- End card: the Dramatic Flip Short,
  `inside-our-most-dramatic-flip-yet-from-dated-to-dream-home-in-4-weeks-short-1-PUBLISH.mp4`
  (1080x1920, 30fps, 61.95s, card in at 50.2s).
- Thumbnail: "SEE HOW A FREEZING BASEMENT KITCHEN TURNED INTO THIS",
  the Drab to Fab cover (`guides/drab-kitchen-basement.json`, `cover_source` 12:51).

## End card: "Tap the full episode"

Required on every Short. Do not change the wording, layout, colours or arrow.
`draw_cta_tap_card` in `scripts/build_short.py` renders it and matched the
approved frame pixel for pixel when rechecked.

Timing
- Hard cut in, no fade, for the last 11.7 seconds (`END_CARD_SECONDS`). It comes
  in with the spoken tap line; a sign off that runs longer than 11.7s sets the
  length instead.
- Holds to the final frame. Finished reveal footage keeps playing underneath,
  picked with `cta_source` and `cta_crop`.

Layout, top to bottom, centred
1. Four stacked, slightly tilted pills, alternating, exact wording:
   WANT TO FIND OUT (white pill, green text) / THE PROJECT COST & (green, white) /
   WATCH THE FULL (white, green) / TRANSFORMATION? (green, white).
   Anton, all caps, 92px. Roughly y 145 to 660.
2. TAP, small green pill (about y 820 to 895).
3. The link chip: white rounded rectangle, green play circle on the left, the
   full episode's EXACT YouTube title in green Montserrat ExtraBold, two to three
   lines.
4. AT THE BOTTOM OF YOUR SCREEN, green pill.
5. One white hand drawn arrow with a single loop, pointing straight down, ending
   just above where YouTube draws the related video link. It draws itself on over
   0.9s and then bobs. The geometry is fixed in code, so it is identical on every
   Short.

Constants
- Green is `#16A34A` (measured (20,162,73) on the approved card), the same as
  the caption plate. The written spec's `#0E9346` is NOT what was approved.
- The font is Anton, not Oswald. Anton is what rendered the approved card.
- Mike's logo stays top right for the whole Short, end card included.

Required per Short, in the guide
- `video_title`: the full episode's exact YouTube title. It goes on the chip and
  into the spoken tap line. Without it the build falls back to the old sticker
  card, so never leave it out.
- `video_url`: the full episode link, for the description.

Publishing check
- In YouTube Studio, set the Short's related video to the full episode. The
  arrow points at that link, so a Short without it points at nothing.

## Thumbnail

Required on every Short, delivered as `[slug]-short-[n]-THUMBNAIL.jpg`.

Background
- One full frame still of the finished space, the best looking angle. Set
  `cover_source` (an episode timestamp) and `cover_crop`. No before shots, no
  people, no workers, no construction, no motion blur.
- Nothing else on it: no logo, no end card, no gradient.

Hook
- `cover_hook`, the same hook as the title, in the form "See how a [before
  state] [room] turned into this" when it fits.
- All caps, three lines, one pill per line. The build picks the line breaks so
  the pills step down in width, widest on top.
- Montserrat ExtraBold 71px (the written spec said 75, which runs 5 percent wider
  than the approved cover), white with a 3px black outline.
- Pills green `#16A349`, 10px corner radius, 109px tall, 24px padding past the
  outlined text, 12px apart. The block starts at y 400.

Measured on the approved cover, and reproduced by the build within 2px:
- Pill 1: y 400 to 508, x 94 to 985
- Pill 2: y 521 to 629, x 123 to 955
- Pill 3: y 642 to 750, x 155 to 923

Publishing check
- A Short's thumbnail is set from the YouTube mobile app. Confirm it actually
  took before publishing.
