# Navier-Stokes

Two opposing dye streams flow toward each other on an internal 12×32 grid:
red from the left driven by bass, cyan from the right driven by highs. Their
shear interaction generates Kelvin-Helmholtz vortices that roll up across the
grid. Bass-heavy music pushes the left side; treble-heavy music pushes the
right; balanced passages produce clean vortex rolls down the center.

## Simulation

Stable Fluids (Stam 1999) on a 12×32 internal grid: semi-Lagrangian velocity
advection, vorticity confinement in place of explicit viscosity, and a Jacobi
pressure projection step that enforces incompressibility. Vorticity
confinement (Fedkiw 2001) re-injects rotational energy that advection
numerically diffuses away. Output is 2×2 average-downsampled to 6×16.

Horizontal boundaries wrap; top and bottom are no-slip walls.

## Color

Left stream is red (hue ≈ 0.0), right stream is cyan (hue ≈ 0.55). Chroma
argmax rotates both hues together around the wheel so the song's current key
tints the palette. When the streams meet, their dyes mix additively in the
advected field; K-H roll cores read as near-white from full additive overlap.

## Audio Mapping

| Feature          | Effect                                                         |
|------------------|----------------------------------------------------------------|
| `bass`           | Left stream injection force                                    |
| `highs`          | Right stream injection force (boosted by `highs_gain`)        |
| `is_beat`        | Left stream surge (`beat_surge` multiplier)                   |
| `high_beat`      | Right stream surge                                             |
| `mids`           | Vorticity confinement gain (more mids = swirlier)             |
| `onset_strength` | Random turbulence amplitude                                    |
| `chroma`         | Rotates the red/cyan hue pair                                  |
| `raw_rms`        | Below `silence_gate`: injection stops, fluid coasts to rest   |

## Tunable Parameters

| Parameter         | Default | Range       | Effect                                       |
|-------------------|---------|-------------|----------------------------------------------|
| `vorticity_gain`  | 2.0     | 0.0–8.0     | Laminar vs swirly (primary tuning knob)      |
| `injection_force` | 5.0     | 0.5–20.0    | Stream force magnitude                       |
| `highs_gain`      | 10.0    | 0.5–10.0    | Right-stream compensation (highs run weaker than bass on real music) |
| `beat_surge`      | 7.0     | 1.0–10.0    | Beat multiplier on injection force           |
| `dye_decay`       | 0.97    | 0.90–1.00   | Per-frame dye fade                           |
| `velocity_decay`  | 0.99    | 0.95–1.00   | Per-frame velocity damping                   |
| `chroma_tint`     | 0.5     | 0.0–1.0     | Chroma rotation amount on hue pair           |
| `turbulence_seed` | 0.15    | 0.0–0.3     | Random force amplitude scaled by onset       |
| `brightness_gain` | 3.2     | 0.2–4.0     | Output brightness multiplier                 |
| `silence_gate`    | 0.02    | 0.0–0.1     | RMS floor below which injection stops        |
