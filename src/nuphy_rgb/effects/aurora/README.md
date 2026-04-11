# Aurora Borealis

Music-reactive aurora curtains on the 6×16 LED keyboard grid. Audio energy maps
to solar wind intensity: louder music produces taller and brighter curtains with
stronger color.

## Inspiration

The aurora borealis is caused by charged solar wind particles exciting atmospheric
gases at different altitudes. Each gas emits light at a specific wavelength:
oxygen at 100–200 km glows green (557.7 nm), oxygen at 200–400 km glows red
(630.0 nm, slow to emit; up to 110 seconds per photon), and ionized nitrogen
lower down adds blue and violet. This altitude-color layering produces the
characteristic banding in real auroras.

## The Curtain

Three curtain bands drift horizontally across the grid at different speeds and
directions. Each is a narrow Gaussian (σ ≈ 2 columns) with a fold-brightness
sine wave anchored to its position: peaks face the viewer and are bright;
troughs face away and dim. A per-row drape offset shifts the center column
sinusoidally by row, turning flat vertical stripes into hanging curtain shapes.

Curtains blend additively and wrap at the edges.

## Physics Shortcuts

The vertical color banding is `_ROW_EMISSION_WEIGHTS @ _EMISSION_PALETTE` — a
6×4 matrix multiply from each keyboard row to a blend of real spectroscopic
colors.

The red channel gets its own slow decay (0.97/frame ≈ 2 s tau), mimicking
the actual 110-second forbidden transition lifetime of the O 630 nm line. At
low energy it's invisible; at high energy it bleeds upward and persists after
a loud passage fades.

Sine waves instead of Perlin noise: at 6 rows, Perlin features are smaller than
a single row and read as random flicker. Globally coherent sines produce a
readable curtain shape at this resolution.

## Audio Mapping

| Audio feature   | Solar wind analogue       | Effect                        |
|----------------|--------------------------|-------------------------------|
| `raw_rms`       | Solar wind pressure       | Curtain height (rows lit)     |
| `is_beat`       | CME impact / substorm     | Hem drops, brightness burst   |
| `bass`          | Substorm onset            | Green intensity boost         |
| `mids`          | Electron precipitation    | Blue boost + drift speed      |
| `highs`         | High-energy particle flux | Red/magenta boost             |
| `spectral_flux` | Magnetic turbulence       | Fold shimmer speed (K-H)      |
