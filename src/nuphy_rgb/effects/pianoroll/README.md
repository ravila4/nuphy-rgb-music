# Pianoroll

Pretend the keyboard is a piano and play the dominant pitched voice. The
detected pitch lights a column in the bottom row; older notes scroll
upward, forming a melodic contour across the grid.

## Layout

```
row 0  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .   <- oldest (faded)
row 1  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
row 2  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
row 3  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
row 4  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
row 5  .  .  .  .  .  *  .  .  .  .  .  .  .  .  .  .   <- current note (bright)
col:   0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
       ├─ 16 semitones, window_base → window_base+15 ─┤
```

16 columns span a chromatic window of 16 semitones. The window auto-shifts
by ±12 semitones (one octave) whenever the detected pitch falls outside
it, keeping the current note on screen.

## Pitch detection

A wide-range YIN detector runs on the raw audio ring buffer each frame
(`f_min=80Hz, f_max=1000Hz`). It emits `(pitch_midi, voiced_prob)` —
a fractional MIDI note and a confidence in `[0, 1]`. On polyphonic music
YIN locks onto the dominant periodic voice, which on most rock/pop
recordings is the bass guitar or low-register line.

## Stamping and scroll

Every frame:

- The smoothed voicing EMA updates (`0.7` rise / `0.2` decay) so brief
  dropouts don't flicker the display.
- If `voiced_ema >= 0.25` and `pitch_midi > 0`, the current note's column
  gets brightness = `voiced_ema` on the bottom row.
- Every `SCROLL_EVERY_N_FRAMES` (= 3) frames, the grid scrolls up one
  row, multiplied by `ROW_DECAY` (= 0.8). At 30 fps that gives 600 ms
  of history across 6 rows.
- Unvoiced frames fade the bottom row by 0.85/frame so silence decays
  between scrolls.

## Color

Hue is driven by the MIDI pitch class (`midi % 12`) of the note that was
stamped, stored per cell. This keeps colors stable when the window
octave-shifts under the current note.

```
pitch class:  C   C#  D   D#  E   F   F#  G   G#  A   A#  B
hue:          0   1/12 2/12 3/12 ...                      11/12
```

## Audio mapping

| Feature       | Effect                          |
|---------------|---------------------------------|
| `pitch_midi`  | Column (within octave-shifted window) and stored hue per cell |
| `voiced_prob` | Brightness; gates whether a note is stamped        |

## Tuning constants

At the top of `effect.py`:

| Constant                 | Role                                              |
|--------------------------|---------------------------------------------------|
| `SCROLL_EVERY_N_FRAMES`  | Higher = slower scroll, longer trails             |
| `ROW_DECAY`              | Per-scroll dim factor for older rows              |
| `NEW_NOTE_THRESHOLD`     | Minimum voicing to stamp; raise to filter noise   |
| `VOICED_SMOOTHING_*`     | Attack / decay of the voicing EMA                 |
