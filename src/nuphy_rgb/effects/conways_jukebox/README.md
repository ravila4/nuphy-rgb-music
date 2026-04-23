# Conway's Jukebox

Game of Life on the keyboard, DJ'd by the music. Beats inject seed patterns;
the dominant pitch class at each injection dyes newborn cells; silence
freezes the colony and fades it to black.

## Concept

Each of the 84 LEDs is a live/dead agent under Conway's three rules: survive
on 2–3 neighbors, die on fewer than 2 or more than 3, birth on exactly 3.
From those rules emerge gliders, oscillators, and chaotic blooms. The
keyboard's irregular row lengths (16/15/15/14/14/10) are load-bearing
substrate physics; cells near the modifier row have at most 2–3 valid
neighbors and rarely survive past one generation.

## Tick Scheduling

Conway is turn-based, but the display runs at 30 fps. The simulation advances
at a configurable rate (default 6 generations/second) using a wall-clock
accumulator. Every detected beat additionally forces an immediate generation
advance (with a short cooldown so fast hi-hats don't strobe). Slow songs
evolve calmly; fast or beat-dense passages drive the colony into rapid chaos.

## Seeding

Bass beats inject an R-pentomino near a random column; it generates gliders
and oscillators for dozens of generations. Mid-frequency
beats inject a glider. High-frequency beats scatter 1–3 single-cell sparkles.
`onset_strength` scales injection count so hard transients seed more than
soft ones.

The colony auto-reseeds a small block if population drops to zero between
beats, preventing permanent death during long gaps.

## Color and Memory

Each cell carries the dominant pitch class (chroma argmax) present at its
birth. Newborn cells flash white; they mature into their birth hue over the
first three generations. Cells that die leave a ghost afterglow at the same hue, decaying over a
few frames.

## Silence

Below the `silence_thresh` RMS floor, ticks stop and no seeds are injected.
A brightness envelope decays the visible output to black while the colony
state is frozen. When sound resumes, the exact population reappears.

## Audio Mapping

| Feature       | Role                  | Effect                                              |
|---------------|-----------------------|-----------------------------------------------------|
| `raw_rms`     | Ambient temperature   | Below threshold: colony freezes and fades           |
| `is_beat`     | Seismic event         | R-pentomino injection + forced tick                 |
| `mid_beat`    | Migration pulse       | Glider injection + forced tick                      |
| `high_beat`   | Spore burst           | Sparkle cells + forced tick                         |
| `onset_strength` | Disturbance magnitude | Injection count multiplier                       |
| `chroma`      | Dye                   | argmax bin → hue of all cells born this beat        |

## Tunable Parameters

| Parameter       | Default | Range      | Effect                                      |
|----------------|---------|------------|---------------------------------------------|
| `tick_rate`     | 6.0     | 1.0–20.0   | Generations per second between beats        |
| `silence_thresh`| 0.02    | 0.0–0.2    | RMS floor below which colony freezes        |
| `ghost_decay`   | 0.85    | 0.60–0.97  | Afterglow falloff per frame                 |
| `min_population`| 3       | 0–20       | Auto-seed threshold                         |
| `r_pent_chance` | 0.7     | 0.0–1.0    | R-pentomino vs block on bass beats          |
