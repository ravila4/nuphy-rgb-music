# Three Body

Three gravitationally interacting point masses on a 16×6 torus. Each body
owns one audio band — bass (red), mids (green), highs (blue) — and its mass
scales with that band's energy. Louder bands produce heavier bodies that pull
the system harder. Trails are exponentially decaying per-channel brightness
fields deposited bilinearly at each body's sub-pixel position.

## Physics

Softened Newtonian gravity, integrated with velocity Verlet × 6 substeps per
frame. Force between bodies i and j:

```
F_ij = G × m_i × m_j × (r_j - r_i) / (|r_j - r_i|² + ε²)^(3/2)
```

The `ε²` Plummer softening term puts a floor on effective distance so close
encounters produce finite forces.

Torus topology uses the minimum-image convention from molecular dynamics: for
any pair, displacement is taken via the shortest path across periodic images.
A body at column 15 is 1 cell from a body at column 0.

Beats deliver a random-direction velocity impulse to the body whose band
fired, preventing the system from settling into stable two-body pairings.

## Trails

Each body deposits into its own RGB channel (red, green, blue) via bilinear
splat with torus-wrapped coordinates. Trail lifetime scales with `raw_rms` by
interpolating between `decay_low` (short tails at silence) and `decay_high`
(long tails at full volume). Where two trails overlap, colors mix additively;
where all three overlap, the grid reads near-white.

## Audio Mapping

| Feature       | Effect                                                    |
|---------------|-----------------------------------------------------------|
| `bass`        | Mass of red body                                          |
| `mids`        | Mass of green body                                        |
| `highs`       | Mass of blue body                                         |
| `is_beat`     | Random impulse to red body                                |
| `mid_beat`    | Random impulse to green body                              |
| `high_beat`   | Random impulse to blue body                               |
| `raw_rms`     | Trail lifetime + deposit gate (silence -> no new trail)   |

## Tunable Parameters

| Parameter         | Default | Range       | Effect                                       |
|-------------------|---------|-------------|----------------------------------------------|
| `G`               | 4.0     | 0.5–12.0    | Gravitational constant                       |
| `softening`       | 0.8     | 0.3–2.0     | Plummer softening radius in grid cells       |
| `base_mass`       | 0.4     | 0.1–1.0     | Minimum body mass at silence                 |
| `mass_gain`       | 1.6     | 0.0–4.0     | Audio band contribution to mass              |
| `beat_kick`       | 6.0     | 0.0–15.0    | Velocity impulse on beat                     |
| `max_speed`       | 18.0    | 5.0–40.0    | Per-body speed ceiling                       |
| `drag`            | 0.02    | 0.0–0.2     | Silence drag rate                            |
| `decay_low`       | 0.80    | 0.60–0.95   | Trail decay at silence                       |
| `decay_high`      | 0.96    | 0.90–0.99   | Trail decay at full volume                   |
| `body_brightness` | 1.3     | 0.3–3.0     | Deposit intensity per body                   |
