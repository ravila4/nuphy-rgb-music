# Event Horizon

A wandering 2×2 black hole with a rotating spiral accretion disk. The disk's
inter-arm bulge is warm amber; each spiral arm takes its color from a pitch
class in the chroma vector via a circle-of-fifths mapping.

## Coordinate system

All geometry is expressed in **key-units** — one unit equals one key spacing.
`LED_X` and `LED_Y` are normalized to `[0, 1]` across the physical key layout,
so multiplying by `(MAX_COLS - 1)` and `(NUM_ROWS - 1)` gives positions where
1 unit = 1 key. This is the only length scale that matches human perception
of the grid, which means the singularity actually reads as a specific number
of keys wide and the disk has enough angular room to show rotating arms.

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

A **rectangular Chebyshev mask** in key-units:

```
void = |dx| < hole_half_w  AND  |dy| < hole_half_h
```

Because one row of the keyboard is ~3× a column in normalized space, a
Euclidean void would be invisible at this resolution. A box mask in key-units
covers a clean 2×2 block of keys, tunable independently per axis so the hole
can be made to look visually square on a specific physical layout.

## Photon ring + disk

Per-LED:

- `ring = exp(-((r - ring_radius)/sigma)^2)` — Gaussian annulus
- `disk_env = exp(...)` — soft outer fall-off to `disk_extent`
- `arm = clip(cos(arms*(θ - rot) - spiral_pitch*r), 0, 1)^arm_sharpness`

A narrow `arm_sharpness` (default 8) makes the arms sharp streaks rather than
gentle sine waves — the high contrast between arm and gap is what lets the
eye track rotation on a 6×16 grid. Arms are drawn **additively** on top of a
dim continuous ring, so the viewer sees the arms *sweep across* a stable disk
shape rather than the arms being the whole disk.

Void is always redrawn last so nothing leaks into the hole.

## Rotation gating (silence = still)

Rotation advances only when there's audio energy:

```
spin_energy = ExpFilter(alpha_rise=0.4, alpha_decay=0.04)
spin = spin_energy.update(min(1.0, raw_rms * 4.0))
disk_rotation += (rotation_speed * spin + bass * 0.35) * dt
```

The slow `alpha_decay` makes the disk coast to a halt over ~1s rather than
stopping abruptly. In silence the disk sits still; bass beats spin it up.

## Coloring — stable structure, chroma-driven arms

Coloring is **spatial-structural**: hue depends on *where* you are on the
disk, never on music features that change per-frame. That means beats and
energy spikes never smear the disk's palette — the hole, the ring, and the
bulge keep their identity at any energy level.

| Zone | Hue source | Value |
|---|---|---|
| Void | — | black |
| Photon ring (inner annulus) | hardcoded | blue 0.58, low saturation (white-hot) |
| Inter-arm bulge | hardcoded | amber 0.10 |
| Spiral arms | chroma | see below |

Each LED outside the photon ring belongs to an arm sector:

```
sector = round((θ - rot) * num_arms / 2π) mod num_arms
```

Each sector gets a hue from the `k`-th largest smoothed chroma bin, mapped
through the **circle of fifths**: `(pc * 7) % 12 / 12`. Harmonically related
keys (C → G → D → A...) end up adjacent on the color wheel, so modulations
produce smooth color drift rather than hue jumps. Per-arm hues are
additionally smoothed through their own `ExpFilter` so top-N swaps between
pitch classes fade over ~1s.

## Beat response (motion and luminance only)

Beats add brightness, never hue.

- `is_beat` → `collapse_intensity` pulse, decays at `* 0.78` per frame.
  The pulse *adds* `ring * ci * 0.8 + disk_env * ci * 0.3` to brightness.
  Hue is untouched, so the photon ring stays blue and the disk stays amber.
- Beats also spawn 2–3 particles at the outer disk edge; particles add
  brightness but do not modify hue either.

## Silence behavior

The global brightness floor `0.55 + rms * 0.6` keeps the disk's shape visible
even on quiet passages. The 2×2 void, photon ring, and amber bulge are all
recognizable in silence — only the rotation stops and the arms dim.

## Audio mapping

| Feature            | Effect                                         |
|--------------------|------------------------------------------------|
| `mids`             | singularity drift speed                        |
| `bass`             | rotation boost (on top of base `rotation_speed`) |
| `raw_rms`          | spin-energy gate (silence → still)             |
| `rms`              | global brightness floor                        |
| `is_beat`          | collapse luminance pulse + particle spawn      |
| `onset_strength`   | collapse pulse intensity                       |
| `spectral_flux`    | particle turbulence                            |
| `chroma`           | per-arm hue (circle of fifths, heavily smoothed)|
| `dominant_freq`    | seed color for newly spawned particles         |
| `highs`            | unused                                         |
| `spectrum`         | unused                                         |
| `high_beat`        | unused                                         |

## Parameters

| Param               | Default | Range      |
|---------------------|---------|------------|
| `hole_half_w`       | 1.0     | 0.5 – 2.0  |
| `hole_half_h`       | 1.0     | 0.5 – 2.0  |
| `ring_radius`       | 2.3     | 1.5 – 4.0  |
| `ring_width`        | 0.9     | 0.3 – 2.0  |
| `disk_extent`       | 5.0     | 3.0 – 7.0  |
| `drift_speed`       | 1.0     | 0.2 – 3.0  |
| `rotation_speed`    | 0.12    | 0.0 – 0.4  |
| `num_arms`          | 3       | 2 – 5      |
| `chroma_saturation` | 1.0     | 0.0 – 1.0  |
| `arm_sharpness`     | 8.0     | 2.0 – 16.0 |
| `spiral_pitch`      | 0.6     | 0.0 – 1.5  |
| `brightness_gain`   | 1.2     | 0.5 – 2.5  |
