# Event Horizon

A wandering dark rectangle surrounded by a glowing ring with spiral arms.
Bass beats spawn color waves at the outer edge that fall inward and get
swallowed when they reach the ring. Loudness inflates the whole structure;
silence collapses it into a tight halo.

## Inspiration

Loosely modeled on a black hole accretion disk: a void at the center, a
bright ring around it, spiral arms, and material falling inward. The
astrophysics is purely aesthetic -- the math is standard 2-D polar geometry
(Gaussians, cosines, exponential falloffs) dressed in a space theme.

## Coordinate system

All geometry is in **key-units** (1 unit = 1 key spacing). `LED_X` and
`LED_Y` are normalized to `[0, 1]`, so multiplying by `(MAX_COLS - 1)` and
`(NUM_ROWS - 1)` gives key-unit positions.

## The void

A fixed 2x2 rectangular mask (Chebyshev distance):

```text
void = |dx| < hole_half_w  AND  |dy| < hole_half_h
```

The void never reacts to audio. It's a stable visual anchor.

## Center drift

The void's center traces a Lissajous path:

```text
x = cx + amp_x * sin(phase)
y = cy + amp_y * cos(phase * 0.618)
```

The irrational frequency ratio (golden-ratio conjugate) keeps the path
from repeating. `mids` accelerates the phase. ExpFilters smooth the
position so it glides instead of jumping.

## Ring and spiral arms

Per-LED, using polar coordinates `(r, theta)` from the void center:

- **Ring**: Gaussian annulus at `ring_radius` with width `sigma`
- **Disk envelope**: exponential falloff from ring to `disk_extent`
- **Arms**: `cos(N*(theta - rotation) - pitch*r)` raised to a sharpness
  exponent, giving narrow bright streaks

Arms are brightness-only -- they don't affect hue. Sharpness of 8 (the
default) keeps them readable at 6x16 resolution.

Rotation is gated by audio energy and coasts to a halt over ~1s in silence.

## Breathing

`raw_rms` through a slow ExpFilter (rise=0.15, decay=0.03) scales both
`ring_radius` and `disk_extent`. Loud passages expand the disk; silence
contracts it. The ring has a hard minimum radius so it can't collapse into
the void.

## Infall rings

Bass beats spawn a color ring at the outer disk edge. Each frame, live
rings:

1. Move inward at `infall_speed * (1 + bass * 0.8)`
2. Decay in intensity (0.97 per frame)
3. Get removed when they cross below `ring_radius`

Each ring's contribution to a given LED is a radial Gaussian, masked by
the disk envelope. The sum of all ring contributions produces a "warmth"
field that shifts hue from indigo toward red through magenta. Max 6
concurrent rings.

## Coloring

Hue depends on geometry and warmth, not on audio features like chroma or
dominant frequency.

| Zone              | Hue                             |
|-------------------|---------------------------------|
| Void              | black                           |
| Inside the ring   | 0.58 (blue-white, desaturated)  |
| Disk baseline     | 0.68 (indigo)                   |
| Disk + warm ring  | 0.68 + warmth * 0.34 (wraps through magenta to red) |

## Silence behavior

- Disk contracts toward minimum radius
- Brightness floor drops to 0.30
- No rings spawn, rotation coasts to a halt
- Result: a dim indigo halo with the void still visible

## Audio mapping

| Feature          | Effect                                        |
|------------------|-----------------------------------------------|
| `raw_rms`        | Disk size (breathing) + rotation gate         |
| `rms`            | Global brightness floor                       |
| `mids`           | Void drift speed                              |
| `bass`           | Ring spawns + infall speed + rotation boost   |
| `is_beat`        | Ring spawn trigger + brightness pulse         |
| `onset_strength` | Ring intensity + pulse intensity              |

## Parameters

| Param             | Default | Range        |
|-------------------|---------|--------------|
| `hole_half_w`     | 1.0     | 0.5 - 2.0  |
| `hole_half_h`     | 1.0     | 0.5 - 2.0  |
| `ring_radius`     | 2.3     | 1.5 - 4.0  |
| `ring_width`      | 0.9     | 0.3 - 2.0  |
| `disk_extent`     | 5.0     | 3.0 - 7.0  |
| `disk_breath`     | 0.55    | 0.0 - 0.9  |
| `drift_speed`     | 1.0     | 0.2 - 3.0  |
| `rotation_speed`  | 0.12    | 0.0 - 0.4  |
| `num_arms`        | 3       | 2 - 5      |
| `arm_sharpness`   | 8.0     | 2.0 - 16.0 |
| `spiral_pitch`    | 0.6     | 0.0 - 1.5  |
| `infall_speed`    | 0.08    | 0.02 - 0.25|
| `warmth_width`    | 0.9     | 0.3 - 2.0  |
| `warmth_gain`     | 1.2     | 0.0 - 2.5  |
| `brightness_gain` | 1.0     | 0.4 - 2.5  |
