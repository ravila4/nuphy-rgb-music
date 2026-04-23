# Lightning

Bass beats trigger branching discharge bolts from the top row to the
bottom. Each strike materializes in a single frame as a white-hot column,
then fades through a plasma-colored afterglow to black. The only effect in
the catalog with a hard discrete attack.

## Bolt Generation

Each bolt is a branching random walk: the main channel descends from row 0
to row 5 with small horizontal jitter, and at random nodes spawns side
branches that grow downward and sideways for 2–4 steps. The full path is
generated before the first frame is rendered, so the strike appears
instantaneously. Branch count scales with `bass`.

Successive strikes land near the previous column (±3) to simulate a
storm cell staying in the same area. High-onset, high-bass beats can
break the pattern and land anywhere.

## White-Hot Decay

Intensity and hue are stored separately; color is reconstructed at output:

```
saturation = 1 - intensity
brightness = intensity
```

At peak (intensity = 1): pure white. As intensity decays, saturation rises
and the channel transitions through the plasma hue to black, with no
special-case logic. Hue comes from `dominant_freq` via `freq_to_hue`, biased
toward the blue-violet band by default.

`mid_beat` re-injects the most recent bolt at half intensity, producing a
crackling-discharge effect during sustained mid-frequency content. Between
strikes, a faint ambient flicker on rows 0–1 reads as distant sheet lightning.

## Audio Mapping

| Feature          | Effect                                                         |
|------------------|----------------------------------------------------------------|
| `is_beat`        | Triggers new bolt (80 ms cooldown prevents strobing)          |
| `onset_strength` | Peak brightness of the strike core                            |
| `bass`           | Branch count (louder = more forks)                            |
| `dominant_freq`  | Plasma afterglow hue (low = orange/teal, high = blue/violet)  |
| `raw_rms`        | Ambient flicker amplitude between strikes                     |
| `mid_beat`       | Reignites the last bolt's path at half intensity              |

## Tunable Parameters

| Parameter          | Default | Range      | Effect                                        |
|--------------------|---------|------------|-----------------------------------------------|
| `decay_rate`       | 0.90    | 0.80–0.97  | Per-frame intensity decay; lower = faster fade |
| `peak_intensity`   | 1.0     | 0.5–1.0    | Strike core brightness                        |
| `branch_chance`    | 0.4     | 0.0–1.0    | Branch probability per main-channel node      |
| `cooldown_ms`      | 80.0    | 30.0–300.0 | Minimum time between strikes                  |
| `ambient_strength` | 0.05    | 0.0–0.20   | Flicker amplitude between strikes             |
| `blue_bias`        | 0.65    | 0.0–1.0    | Compresses plasma hue toward blue-violet      |
