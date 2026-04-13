# Strange Attractor

12 particles orbit a Lorenz attractor in 3-D; their positions are projected
onto the 6x16 LED grid and rendered as glowing trails. Audio energy
modulates the attractor parameters in real time, causing orbits to stretch,
contract, and occasionally explode with the music.

## The Lorenz system

The classic Lorenz equations with three control parameters:

```text
dx/dt = sigma * (y - x)
dy/dt = x * (rho - z) - y
dz/dt = x * y - beta * z
```

At rest the parameters sit near the chaotic regime (sigma=8, rho=20, beta=2).
Audio pushes them into different dynamical regimes: bass widens the
butterfly wings (sigma), mids drive deeper into chaos (rho), highs
accelerate the time step and increase beta damping.

Integration is vectorized Euler with 3 substeps per frame, clamped to
[-100, 100] to prevent runaway.

## Projection

The x-axis maps to grid horizontal, z-axis to grid vertical. Typical
Lorenz range (x in [-25, 25], z in [0, 55]) is normalized to [0, 1]
and matched against `LED_X` / `LED_Y`.

## Trail rendering

Each particle deposits brightness onto nearby LEDs via a Gaussian falloff
(radius 0.15 in normalized coords). Trails accumulate as the max of
current trail brightness and new deposit, then decay each frame.

Trail hue per LED is a circular mean of contributing particle hues,
lerped via shortest-arc delta to avoid wrap discontinuities. Each particle
starts with an evenly-spaced hue on the color wheel; mid-beats rotate
all hues by 0.08.

## Audio mapping

| Feature          | Effect                                            |
|------------------|---------------------------------------------------|
| `bass`           | Lorenz sigma boost (wider butterfly wings)        |
| `mids`           | Lorenz rho boost (pushes toward chaos)            |
| `highs`          | Beta damping + time step acceleration             |
| `rms`            | Trail decay slowdown (louder = longer tails)      |
| `spectral_flux`  | Additional time step acceleration                 |
| `is_beat`        | Particle displacement kick (jolts orbits)         |
| `onset_strength` | Scales the beat kick intensity                    |
| `mid_beat`       | Rotates all particle hues                         |

## Parameters

| Param              | Default | Range       | Description                                      |
|--------------------|---------|-------------|--------------------------------------------------|
| `sigma_bass_boost` | 8.0     | 0.0 -- 20.0 | Bass to Lorenz sigma modulation depth            |
| `rho_mids_boost`   | 16.0    | 0.0 -- 30.0 | Mids to Lorenz rho modulation depth              |
| `trail_decay`      | 0.82    | 0.70 -- 0.95 | Base trail decay per frame (higher = longer tails) |
| `beat_kick_force`  | 3.0     | 0.0 -- 8.0  | Beat impulse displacement on particles           |
