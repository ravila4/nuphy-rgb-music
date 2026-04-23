# Double Pendulum

The outer tip of a chaotic double pendulum paints a rainbow phosphor trail
across the keyboard. Only the outer tip is rendered; the inner bob drives the
physics but isn't drawn. Audio couples to the physics through time dilation
only: loud music runs the pendulum faster against a fixed wall-clock decay,
so the tip covers more orbit per phosphor lifetime and the trail thickens into
a dense, self-crossing knot.

## Physics

Equal-mass double pendulum (`m1 = m2 = 1`), state `[θ1, θ2, ω1, ω2]` with
angles measured from the downward vertical. Equations of motion:

```
δ   = θ1 - θ2
den = 3 - cos(2δ)

α1 = (-3g sin θ1 - g sin(θ1 - 2θ2) - 2 sin δ (ω2² L2 + ω1² L1 cos δ)) / (L1 den)
α2 =  (2 sin δ (2ω1² L1 + 2g cos θ1 + ω2² L2 cos δ)) / (L2 den)
```

A linear damping term `-λω` bleeds energy so silence eventually brings the
bobs to rest. Integrated with RK4 × 8 substeps per frame; angles are wrapped
to `(-π, π]` after each step.

## Geometry

Pivot sits just above the top row, horizontally centered, at `(8.0, -0.5)`.
`L1 = L2 = 3.0` grid cells; hanging equilibrium places the tip at `(8.0, 5.5)`,
bottom-center. High-energy upswings extend above the pivot and off-grid; those
frames skip the deposit. Corners are unreachable: max reach is `L1 + L2 = 6.0`
cells, which falls short of the pivot-to-corner distance.

## Time Dilation

```
phys_dt = dt × (base_speed + speed_gain × raw_rms)
```

The only audio coupling. Quiet passages run physics at `base_speed` (0.5×
wall clock); loud passages at ~2.9×. Phosphor decay stays on wall-clock, so
faster physics deposits more trail per decay interval; more self-crossings
produce a denser, brighter knot.

On `is_beat`, the outer bob gets a random-sign angular velocity impulse to
prevent the system from settling into quasi-periodic regions.

## Rainbow Tail

The phosphor buffer is a `(6, 16, 3)` RGB field decayed by `tail_decay` each
frame. Hue at each splat comes from wall-clock time:

```
hue = (timestamp × hue_rate) % 1
```

Adjacent splats differ in hue; when the orbit re-crosses older trail, the
fresh (brighter) splat dominates but additive blending leaks the older color
through. Dense overlap regions mix several hues toward white.

## Audio Mapping

| Feature    | Effect                                                         |
|------------|----------------------------------------------------------------|
| `raw_rms`  | Time dilation rate + deposit gate (silence -> trail fades)    |
| `is_beat`  | Random-sign angular impulse on outer bob                       |
| `timestamp`| Hue phase (rainbow cycles at `hue_rate` Hz)                   |

All other audio features are unused.

## Tunable Parameters

| Parameter      | Default | Range       | Effect                                      |
|----------------|---------|-------------|---------------------------------------------|
| `tail_decay`   | 0.92    | 0.70–0.995  | Per-frame RGB multiplier; higher = longer tail |
| `speed_gain`   | 3.0     | 0.5–8.0     | How hard loudness accelerates physics       |
| `base_speed`   | 0.5     | 0.0–2.0     | Physics speed floor at silence              |
| `hue_rate`     | 0.15    | 0.0–1.0     | Rainbow cycles per second                   |
| `gravity`      | 9.8     | 2.0–30.0    | Attractor character (low = floaty, high = snappy) |
| `damping`      | 0.002   | 0.0–0.02    | Linear angular friction                     |
| `beat_kick`    | 2.0     | 0.0–8.0     | Outer-bob angular impulse on beat           |
| `deposit_gain` | 1.5     | 0.3–4.0     | Splat brightness scale                      |
