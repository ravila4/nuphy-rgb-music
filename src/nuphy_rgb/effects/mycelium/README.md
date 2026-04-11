# Mycelium

Beat-driven tendril growth across the keyboard grid. On each beat, glowing
threads spawn at random keys and crawl outward through neighbors, branching
and fading like bioluminescent fungal networks.

## Inspiration

Mycelial networks grow by extending hyphae through available substrate. Each
tip advances one cell at a time, forking when it finds multiple viable paths.
The result is an organic, space-filling structure that emerges from simple local
rules. This effect maps that behavior directly to the keyboard grid: each LED is
a cell, the `NEIGHBORS` table is the substrate graph, and the beat is the
nutrient pulse that triggers growth.

The default color palette is phosphorescent green, shifting toward warm red on
bass-heavy passages and cool blue on high-frequency ones.

## Growth Model

Each tendril is a single cursor with a position, hue, energy level, and
maximum lifespan. On each frame it:

1. Stamps its current key with a max-blended HSV color at full saturation
2. Decays its energy multiplicatively (`energy_decay` param)
3. Advances to a random unoccupied neighbor (probability scales with RMS)
4. Possibly forks, spawning a child tendril at a different neighbor with
   a slight hue shift and 70% of parent energy

An `occupied` set prevents two tendrils from sharing a key, keeping trails
visually distinct. Dead tendrils (age exceeded or energy < 0.05) are culled
each frame and their keys freed.

`mid_beat` events trigger an extra fork burst from all live tendrils
simultaneously, creating a visible density surge between main beats.

## Color

Hue is sampled stochastically at spawn time, weighted by the three audio bands:

| Band   | Hue range  | Color family |
|--------|-----------|--------------|
| Bass   | 0.00–0.08 | Red / warm   |
| Mids   | 0.25–0.42 | Green        |
| Highs  | 0.58–0.78 | Blue / cool  |

Forks inherit parent hue with ±0.03 drift, so a single beat produces a
family of closely related colors rather than random scatter.

A constant green floor (0.02 per frame) keeps dark keys faintly phosphorescent
between beats.

## Tunable Parameters

| Parameter     | Default | Range     | Effect                              |
|--------------|---------|-----------|-------------------------------------|
| `decay_rate`  | 0.93    | 0.80–0.99 | Trail length (higher = longer)      |
| `energy_decay`| 0.82    | 0.60–0.97 | How far tendrils travel before dying|
| `fork_chance` | 0.20    | 0.00–0.60 | Branching density                   |

`spectral_flux` shortens trail decay during busy audio passages, preventing
grid saturation during dense sections.
