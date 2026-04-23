# Polarity

Twelve charged bodies on a torus, one per pitch class (C through B). Each
body has a fixed charge `cos(2πk/12)`. Bodies with opposite charges attract;
bodies with the same charge repel. The song's chroma vector controls which
bodies are heavy and visible — silent pitch classes coast at zero weight and emit no light
while the playing notes interact through their charges.

## Charge Mapping

The charge formula encodes music theory directly into the force law:

- Tritone (C + F#, k=0 and k=6): charges +1 and -1, force product = -1.
  Maximum attraction. The most dissonant interval slams its bodies together.
- Unison / octave (k=0, k=0): charges +1 and +1, force product = +1.
  Maximum repulsion. Doubles push apart.
- Perfect fifth (C + G, k=0 and k=7): charges +1 and −0.5. Moderate
  attraction, stable orbital pair.

Sustained chords produce characteristic constellations: a major triad forms a
stable triangular arrangement, while a diminished chord contains a tritone and
is physically unstable.

## Architecture

Twelve bodies on a 16×6 torus with minimum-image gravity (shortest periodic
displacement). Velocity Verlet integrator × 6 substeps per render call;
Plummer softening prevents singularities on close encounters. Each body
deposits its pitch-class hue bilinearly into a decaying RGB trail buffer —
the same architecture as Three Body, but with musical charge instead of
audio-band mass.

## Audio Mapping

| Feature      | Effect                                                          |
|--------------|-----------------------------------------------------------------|
| `chroma[k]`  | Mass and brightness of body k; silent pitches coast and vanish |
| `is_beat`    | Velocity impulse to each body scaled by its chroma weight      |
| `raw_rms`    | Trail decay rate (loud = long trails, silence = fast fade)     |

All other audio features are unused.

## Tunable Parameters

| Parameter          | Default | Range       | Effect                                       |
|--------------------|---------|-------------|----------------------------------------------|
| `force_constant`   | 4.0     | 0.0–20.0    | Coulomb force scale                          |
| `softening`        | 0.8     | 0.3–2.0     | Plummer softening radius in grid cells       |
| `base_mass`        | 0.1     | 0.0–1.0     | Minimum mass for silent pitches              |
| `chroma_mass_gain` | 1.6     | 0.0–4.0     | Chroma weight contribution to body mass      |
| `beat_kick`        | 6.0     | 0.0–20.0    | Velocity impulse per beat (per chroma weight)|
| `max_speed`        | 18.0    | 5.0–40.0    | Per-body speed ceiling                       |
| `decay_low`        | 0.80    | 0.60–0.95   | Trail decay at silence                       |
| `decay_high`       | 0.96    | 0.90–0.99   | Trail decay at full volume                   |
| `body_brightness`  | 1.3     | 0.3–3.0     | Deposit intensity per body                   |
| `chroma_threshold` | 0.05    | 0.0–0.5     | Minimum chroma weight to render a body       |
