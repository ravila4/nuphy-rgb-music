# Kármán Street

A freestream flows rightward past a fixed square obstacle on an internal
12×32 grid. The wake sheds alternating clockwise and counterclockwise
vortices that drift downstream and wrap at the edges. Two Lagrangian dye
cursors ride the flow upstream of the obstacle, injecting warm and cool
color that buoyancy separates vertically as the vortices carry it away.

## Physics

Stable Fluids (Stam 1999) on the 12×32 internal grid: semi-Lagrangian
velocity advection, vorticity confinement, and a pressure projection step
that enforces incompressibility. Viscous diffusion is omitted — the
numerical diffusion from first-order advection is already high at this
grid resolution, and adding explicit viscosity would push the Reynolds
number into the laminar regime and kill vortex formation.

The obstacle is a 3×3 solid block at column 8, mid-height. The Kármán
instability fires at Re ≈ 30 for a bluff body of diameter D=3, confirmed
in simulation before building.

Horizontal boundaries wrap; top and bottom are no-slip walls. Output is
2×2 max-pooled to the 6×16 keyboard grid, which preserves thin vortex
cores that averaging smears out.

## Dye and Buoyancy

Two Lagrangian cursors (warm and cool) advance with the local velocity
field, staying upstream of the obstacle. On each frame they inject tinted
dye into the fluid. Chroma argmax rotates the warm/cool hue pair around
the wheel so the song's current key tints the palette.

Buoyancy adds a vertical force proportional to the warm and cool tracer
concentrations. Bass amplifies the upward force on warm dye; highs drive
the cool dye down. As vortices shed and carry the dye around the obstacle,
the vertical bias separates the two color phases, so the shed wake reads
as color-coded swirls.

## Audio Mapping

| Feature          | Effect                                                        |
|------------------|---------------------------------------------------------------|
| `bass`           | Freestream speed + warm dye buoyancy (up)                    |
| `highs`          | Cool dye buoyancy (down)                                      |
| `is_beat`        | Vertical jet upstream of obstacle; forces a vortex pair shed  |
| `mid_beat`, `high_beat` | Opposite-sign jet (cool phase)                       |
| `onset_strength` | Random turbulence amplitude; keeps shedding active on drones  |
| `chroma`         | Rotates warm/cool base hues                                   |
| `raw_rms`        | Below `silence_gate`: freestream drops, cursor injection stops |

## Tunable Parameters

| Parameter            | Default | Range       | Effect                                    |
|----------------------|---------|-------------|-------------------------------------------|
| `freestream_idle`    | 8.0     | 0.0–20.0    | Baseline flow speed in silence            |
| `freestream_bass_gain` | 18.0  | 0.0–30.0    | Bass contribution to freestream           |
| `buoyancy_gain`      | 8.0     | 0.0–20.0    | Upward force per unit warm dye            |
| `cooling_gain`       | 10.0    | 0.0–20.0    | Downward force per unit cool dye          |
| `dye_density`        | 4.0     | 0.5–10.0    | Injection rate at cursor position         |
| `dye_decay`          | 0.97    | 0.90–1.00   | Per-frame dye fade                        |
| `vorticity_gain`     | 3.0     | 0.0–8.0     | Vorticity confinement (laminar vs swirly) |
| `beat_kick`          | 6.0     | 0.0–15.0    | Upstream jet amplitude on beat            |
| `turbulence_seed`    | 0.08    | 0.0–0.3     | Random force amplitude scaled by onset    |
| `brightness_gain`    | 5.0     | 0.2–20.0    | Output brightness multiplier              |
| `chroma_tint`        | 0.7     | 0.0–1.0     | Chroma rotation on hue pair               |
| `silence_gate`       | 0.02    | 0.0–0.1     | RMS floor below which injection stops     |
