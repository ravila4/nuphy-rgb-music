# Chromatic Keys

Bar-graph equalizer for musical pitch classes. Each of the 12 pitch classes
(C through B) owns one or two columns on the 16-column grid. Bars grow
from the bottom up proportional to chroma energy.

## Layout

```
col:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
note: C  C# D  D# E  F  F# G  G# A  A# B  B  ...
```

12 pitch classes spread across 16 columns — some notes get two adjacent
columns. Color is fixed per pitch class: C = red (hue 0.0) cycling through
the hue wheel to B = violet (hue ~0.917).

## Bar rendering

For each column, the corresponding chroma bin energy determines bar
height (0 to `NUM_ROWS`). Rows fill bottom-up: row 5 is the base, row 0
is the peak. Partial fill fractions produce smooth bar tops.

Brightness per cell combines the fill fraction, a squared amplitude
envelope (from `rms`), and any active beat flash.

## Beat flash

On `is_beat`, a 0.3 brightness boost decays at 0.6/frame across the
entire grid.

## Audio mapping

| Feature   | Effect                         |
|-----------|--------------------------------|
| `chroma`  | Per-pitch-class bar heights    |
| `rms`     | Global amplitude envelope      |
| `is_beat` | Brightness flash               |
