# Event Horizon

*The event horizon swallows events.*

A wandering 2×2 black hole with a rotating spiral accretion disk. The disk
sits on a cool indigo baseline; bass beats inject warm rings at the outer
edge that fall inward, shift the local hue toward red via magenta, and are
extinguished the instant they cross the photon ring. Loudness inflates the
whole disk; silence collapses it into a tight halo.

## Coordinate system

All geometry is expressed in **key-units** — one unit equals one key spacing.
`LED_X` and `LED_Y` are normalized to `[0, 1]` across the physical key layout,
so multiplying by `(MAX_COLS - 1)` and `(NUM_ROWS - 1)` gives positions where
1 unit = 1 key. This is the only length scale that matches human perception
of the grid at this resolution.

## Singularity

The singularity traces a Lissajous-like path in key-units:

```
x = cx + amp_x * sin(φ)
y = cy + amp_y * cos(φ * 0.618)
```

`0.618` (golden-ratio conjugate) keeps the two axes incommensurable so the
path never repeats. `mids` accelerates the phase accumulator. `ExpFilter`s
smooth the target position to prevent teleportation jumps.

## Event horizon (the "hole")

A **fixed** rectangular Chebyshev mask in key-units:

```
void = |dx| < hole_half_w  AND  |dy| < hole_half_h
```

The void does not breathe — it's a stable 2×2 visual anchor. Everything
else in the effect reacts to music; the hole stays put.

## Accretion disk breathing

Loudness (`raw_rms`) drives a slow envelope that inflates / collapses the
disk by scaling both `ring_radius` and `disk_extent` together:

```
breath = ExpFilter(rise=0.15, decay=0.03).update(min(1, raw_rms * 3))
disk_scale = 1 + disk_breath * (2*breath - 1)     # silence → 1 - disk_breath
                                                  # loud    → 1 + disk_breath
ring_radius_eff = max(min_ring, ring_radius * disk_scale)
disk_extent_eff = max(ring_radius_eff + 0.5, disk_extent * disk_scale)
```

The ring has a hard floor at `max(hole_half_w, hole_half_h) + 0.4` so it
can never be pulled into the void, and the disk extent is always held
above the ring. Slow rise + slower decay means the disk inhales with a
track's dynamics rather than pumping on every beat.

## Photon ring + spiral arms

Per-LED, using `r` and `θ` from the singularity:

- `ring = exp(-((r - ring_radius_eff)/sigma)^2)` — Gaussian annulus
- `disk_env` — soft outer fall-off to `disk_extent_eff`
- `arm = clip(cos(arms*(θ - rot) - spiral_pitch*r), 0, 1)^arm_sharpness`

A narrow `arm_sharpness` (default 8) makes arms sharp streaks rather than
gentle sine waves — high contrast is what lets the eye track rotation on
a 6×16 grid. Arms are additive on top of a dim continuous ring. **Arms
are a brightness feature only; they carry no hue.**

Rotation advances only when there's audio energy:

```
spin = ExpFilter(0.4, 0.04).update(min(1, raw_rms * 4))
disk_rotation += (rotation_speed * spin + bass * 0.35) * dt
```

The slow decay lets the disk coast to a halt over ~1s instead of stopping
abruptly. In silence the disk sits still; bass spins it up.

## Infall rings — the event horizon swallows events

Each bass beat (or sustained low-end) spawns an `_InfallRing` at the outer
disk edge with an intensity proportional to `bass + onset_strength`. Every
frame, each live ring:

1. **Advects inward** at `infall_speed * (1 + bass*0.8) * dt`
2. **Decays** its intensity geometrically (`0.97^dt_scale`)
3. **Is extinguished** the instant its radius drops below `ring_radius_eff`

Per-LED warmth is the sum of each ring's radial Gaussian contribution,
masked by the disk envelope so warmth never leaks into empty space:

```
warmth[i] = clip( Σ rg.intensity * exp(-((r[i] - rg.radius)/ww)^2) * disk_env[i] )
```

The warmth field drives **hue** (indigo → magenta → red) and a small
additive **brightness** boost so the wave is legibly visible, not just a
tint shift. Ring count is capped at `_MAX_RINGS = 6`.

## Coloring

Coloring is **structural plus a temperature field**: hue is a function of
geometry (where on the disk) and warmth (how many rings are currently
passing through), never of per-frame audio features like chroma or
dominant frequency.

| Zone                           | Hue                               |
|---|---|
| Void                           | black                             |
| Photon ring interior           | 0.58 (hot blue)                   |
| Disk baseline                  | 0.68 (indigo) + `warmth * 0.34`   |
| Warm ring at peak              | ~0.02 (red) via magenta short-path |

The hue span 0.68 → 1.02 wraps through 0.88 (magenta) on the short path,
so as a warm ring traverses the disk you see indigo → violet → magenta →
red-orange → back to indigo once the ring is swallowed.

Inner-ring saturation is softened so the photon-ring core reads as
white-hot blue rather than pure saturated blue.

## Silence behavior

- Disk contracts toward its `min_ring` floor
- Global brightness floor drops to `0.30` (down from `0.55 + rms * 0.6` at loud)
- No rings spawn
- Rotation coasts to a halt
- Result: a dim, tight, mostly-indigo halo with the void still recognizable

## Audio mapping

| Feature            | Effect                                           |
|---|---|
| `raw_rms`          | disk breathing (size) + rotation gate            |
| `rms`              | global brightness floor                          |
| `mids`             | singularity drift speed                          |
| `bass`             | ring spawns + infall speed + rotation boost      |
| `is_beat`          | ring spawn trigger + collapse luminance pulse    |
| `onset_strength`   | ring intensity + collapse pulse intensity        |
| `highs`            | unused                                           |
| `spectrum`         | unused                                           |
| `chroma`           | unused                                           |
| `dominant_freq`    | unused                                           |

## Parameters

| Param              | Default | Range      |
|---|---|---|
| `hole_half_w`      | 1.0     | 0.5 – 2.0  |
| `hole_half_h`      | 1.0     | 0.5 – 2.0  |
| `ring_radius`      | 2.3     | 1.5 – 4.0  |
| `ring_width`       | 0.9     | 0.3 – 2.0  |
| `disk_extent`      | 5.0     | 3.0 – 7.0  |
| `disk_breath`      | 0.55    | 0.0 – 0.9  |
| `drift_speed`      | 1.0     | 0.2 – 3.0  |
| `rotation_speed`   | 0.12    | 0.0 – 0.4  |
| `num_arms`         | 3       | 2 – 5      |
| `arm_sharpness`    | 8.0     | 2.0 – 16.0 |
| `spiral_pitch`     | 0.6     | 0.0 – 1.5  |
| `infall_speed`     | 0.08    | 0.02 – 0.25|
| `warmth_width`     | 0.9     | 0.3 – 2.0  |
| `warmth_gain`      | 1.2     | 0.0 – 2.5  |
| `brightness_gain`  | 1.0     | 0.4 – 2.5  |
