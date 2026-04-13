# Aurora Borealis

Three colored curtain bands drift horizontally across the 6x16 grid.
Audio energy controls curtain height and brightness: louder music produces
taller, brighter curtains.

## Inspiration

The aurora borealis is caused by charged solar wind particles exciting
atmospheric gases at different altitudes. Each gas emits light at a
specific wavelength: oxygen at 100-200 km glows green (557.7 nm), oxygen
at 200-400 km glows red (630.0 nm, slow to emit -- up to 110 seconds per
photon), and ionized nitrogen lower down adds blue and violet. This
altitude-color layering produces the characteristic banding in real auroras.

## Curtains

Three curtain bands drift at different speeds and directions, wrapping at
grid edges. Each curtain is:

- A narrow Gaussian envelope (sigma ~2 columns)
- A fold-brightness sine wave anchored to the curtain's position (peaks
  are bright, troughs are dim)
- A per-row drape offset that shifts the center column sinusoidally,
  turning flat vertical stripes into hanging shapes

Curtains blend additively.

## Vertical color

A 6x4 matrix multiply (`_ROW_EMISSION_WEIGHTS @ _EMISSION_PALETTE`) maps
each keyboard row to a blend of four RGB colors taken from real emission
line wavelengths. Row 0 (top) is red, rows 2-3 are green, rows 4-5 are
blue/violet.

Bright peaks desaturate toward white (quadratic white mix at 35%) as a
depth cue.

## Red channel decay

The red channel has its own slow decay (0.97/frame, ~2s time constant).
At low energy it's invisible; at high energy it bleeds upward and persists
after a loud passage fades. (The 630 nm oxygen line has a long emission lifetime.)

## Audio mapping

| Feature          | Effect                            |
|------------------|-----------------------------------|
| `raw_rms`        | Curtain height (rows lit)         |
| `is_beat`        | Hem drop + brightness burst       |
| `bass`           | Green intensity boost             |
| `mids`           | Blue boost + drift speed          |
| `highs`          | Red/magenta boost                 |
| `spectral_flux`  | Fold shimmer speed                |
