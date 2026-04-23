# Raycaster

First-person view through a toroidal 8×8 pillar maze. Each of the 16
keyboard columns casts one ray; wall distance drives slice height (geometry)
and brightness (exponential fog). The maze wraps in both axes — there are no
dead ends, and the player can never escape.

## Rendering

Classic column-per-ray technique (Wolfenstein-style). For each column, a ray
steps outward at the corresponding angle within a 66° field of view until it
hits a wall or reaches max distance. The corrected distance (fisheye-corrected)
determines two depth cues:

```
slice_height  = NUM_ROWS / distance      (clamped to grid height)
brightness    = exp(-distance × fog)
```

East/west wall crossings and north/south crossings get different base hues
(warm vs cool), following the Wolfenstein shading trick: the hue discontinuity
at corners gives depth at 6-row vertical resolution where geometry alone
would not.

`dominant_freq` shifts both base hues together so wall color tracks the
current pitch. EW walls drift in the warm range; NS walls drift in the cool
range.

## Navigation

The player moves forward at a rate that scales with `bass` (a continuous
push, not a beat trigger). The view slowly rotates at a constant yaw rate.
`high_beat` delivers a rotation jolt; direction alternates to avoid
one-sided spiraling.

`rms` sets a global brightness floor so the maze stays visible in silence.

## Audio Mapping

| Feature         | Effect                                              |
|-----------------|-----------------------------------------------------|
| `bass`          | Forward velocity (continuous)                       |
| `high_beat`     | Rotation jolt                                       |
| `dominant_freq` | Wall hue shift                                      |
| `rms`           | Global brightness floor                             |
