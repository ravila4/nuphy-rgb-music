# Event Horizon

A wandering dark rectangle surrounded by a glowing ring with spiral arms.
Bass beats spawn color waves at the outer edge that accelerate inward,
thinning and brightening, until they cross the ring and detonate into a
flare. Loudness inflates the whole structure; silence collapses it into a
tight halo. While the disk spins, the approaching side glows brighter
(Doppler beaming).

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

## Doppler beaming

Ring and arm brightness are multiplied by

```text
1 + beam_strength * spin * cos(theta - rotation)
```

so the side of the disk rotating toward the viewer glows brighter (the M87
look). The asymmetry is gated by the spin-energy filter: silence gives a
symmetric halo. `beam_strength` is capped at 0.7 so the receding side dims
but never disappears. This also makes rotation legible at 6x16 -- a bright
spot orbiting the void reads far better than rigid arms alone.

## Breathing

`raw_rms` through a slow ExpFilter (rise=0.15, decay=0.03) scales both
`ring_radius` and `disk_extent`. Loud passages expand the disk; silence
contracts it. The ring has a hard minimum radius so it can't collapse into
the void.

## Infall rings

Bass beats spawn a color ring at the warm envelope's full-strength edge
(`disk_extent - 0.8`, never inside the photon ring). Each frame, live
rings:

1. Accelerate inward: `infall_speed * (spawn_r / r) ** infall_accel`,
   times `(1 + bass * 0.8)`. The default `infall_accel = 0.5` is the
   Keplerian free-fall exponent; 0 recovers constant speed.
2. Thin tidally: effective width shrinks proportionally to radius
   (floored at `tidal_min`), while peak intensity rises `1/frac` to
   conserve flux. Rings arrive at the horizon thin and hot.
3. Get swallowed when they cross below `ring_radius`, dumping their
   remaining intensity into the accretion flare.

There is no per-frame intensity decay -- the tidal profile provides the
brightness arc instead. Each ring's contribution to a given LED is a
radial Gaussian, masked by a smoothstep that only fades at the disk rim
(full strength inside, so rings are visible from the moment they spawn --
the old exponential-envelope mask hid them for the outer third of the
journey). Max 6 concurrent rings.

## Accretion flare

A swallowed ring flashes the photon ring (luminance only, scaled by
`flare_gain`, decaying at 0.8/frame). Every flare is therefore a bass
beat arriving ~1 second late, after the eye has watched it fall. Rings
culled for low intensity fade silently -- only swallows flare. The old
beat-synced collapse pulse was removed in favor of this delayed payoff.

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
| `raw_rms`        | Disk size (breathing) + rotation gate + beaming gate |
| `rms`            | Global brightness floor                       |
| `mids`           | Void drift speed                              |
| `bass`           | Ring spawns + infall pull + rotation boost    |
| `is_beat`        | Ring spawn trigger (flare follows at swallow) |
| `onset_strength` | Ring intensity (and thus eventual flare size) |

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
| `infall_speed`    | 0.05    | 0.02 - 0.25|
| `infall_accel`    | 0.5     | 0.0 - 1.0  |
| `tidal_min`       | 0.35    | 0.2 - 0.8  |
| `warmth_width`    | 0.9     | 0.3 - 2.0  |
| `warmth_gain`     | 1.2     | 0.0 - 2.5  |
| `flare_gain`      | 1.0     | 0.0 - 2.0  |
| `beam_strength`   | 0.45    | 0.0 - 0.7  |
| `brightness_gain` | 1.0     | 0.4 - 2.5  |
