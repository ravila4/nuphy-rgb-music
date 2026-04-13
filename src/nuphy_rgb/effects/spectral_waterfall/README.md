# Spectral Waterfall

Scrolling spectrogram on the keyboard grid. The top row shows the current
frame's frequency spectrum; each subsequent frame, all rows scroll downward
by one, so the grid becomes a time-frequency display with the most recent
audio at the top.

## Layout

```
col:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
      ├── bass ──────────┤              ├── treble ──┤
```

Left = bass, right = treble. Each of the 16 columns maps 1:1 to one of
the 16 spectrum bins. Color is frequency-mapped hue (bass=red through
treble=violet); brightness is bin magnitude scaled by an amplitude
envelope.

## Per-bin AGC

Each frequency bin maintains a running peak that decays at 0.995/frame.
Raw bin values are divided by this peak, keeping all bins independently
normalized so quiet treble bins are as visible as loud bass bins. A sqrt
compression widens the dynamic range further.

## Amplitude envelope

`raw_rms` is smoothed through an `ExpFilter` (fast rise, slow decay) and
squared to produce a per-row amplitude multiplier. This is stored with
each row as it scrolls, so older rows retain the loudness context from
when they were current.

## Beat flash

On `is_beat`, a 0.25 brightness boost is added across all rows and decays
at 0.6/frame. This gives transients a brief full-grid punch without
altering the spectral content.

## Audio mapping

| Feature    | Effect                              |
|------------|-------------------------------------|
| `spectrum` | Frequency bin magnitudes per column |
| `raw_rms`  | Per-row amplitude envelope          |
| `is_beat`  | Global brightness flash             |
