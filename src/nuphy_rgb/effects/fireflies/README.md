# Fireflies

*Kuramoto coupled oscillators entraining to the music.*

## Philosophy

**The system.** Southeast Asian fireflies (*Pteroptyx*) gather in mangrove
trees by the thousands and, over a few minutes, spontaneously flash in unison.
No conductor, no leader — each firefly only nudges its phase a little toward the
ones it can see, and global synchrony emerges from purely local rules. This is
the canonical example of the **Kuramoto model**: a population of phase
oscillators, each with its own natural frequency, weakly coupled to its
neighbors. The same math governs pacemaker cells in the heart, neurons locking
into brain rhythms, and AC generators on a power grid. Fireflies puts one
oscillator on every key and lets you *watch synchronization happen*.

Each LED holds a phase θ rotating around the circle. Its brightness is a
sharpened pulse of that phase — mostly dark, with a brief flash as θ passes
zero, exactly like a blinking firefly. Left alone, every oscillator runs at a
slightly different natural frequency, so the board is an incoherent shimmer of
scattered blinks. Introduce coupling and the neighbors start pulling each other
into step; phase waves roll across the grid; eventually the whole keyboard
breathes as one. The drama of the effect *is* the transition between those two
regimes, and the music controls which regime you're in.

**Audio as the driving force.** The music plays two physical roles. First, loudness
(`bass` + `rms`) sets the **coupling strength K** — the harder the track hits,
the more strongly neighbors entrain each other, so loud passages drive the board
toward unison and quiet passages let it dissolve back into independent
twinkling. Second, the **beat is the external pacemaker**. A separate "drive"
phase advances continuously and gets a kick on every `is_beat`; a forcing term
yanks all the oscillators toward that drive phase. This is *entrainment to an
external rhythm* — the literal reason your foot taps to a song. On a steady
groove the fireflies lock to the beat and flash on the downbeat; drop the beat
and they spin free.

**Spatial structure.** Phases live on a 6x16 torus (wrap-around in both axes).
Coupling is local — each cell talks to its 4 nearest neighbors — which is what
makes this read at low resolution. Local coupling in a 2D oscillator lattice
produces *traveling phase fronts* and the occasional spiral defect: coherent
rolling waves of brightness, not noise. That matches the grid's strengths
(traveling wavefronts, sine-like coherence) and avoids its weaknesses (no fine
texture, no per-key randomness). Global forcing from the beat competes with the
local waves: when the beat dominates you get flat unison flashes; between beats
the local waves reassert and the pattern ripples.

**Color.** Hue comes from the music — `dominant_freq` mapped through
`freq_to_hue`, smoothed — so the whole swarm glows in the song's color (bass
tracks red/warm, leads blue/cool). On top of that, the **Kuramoto order
parameter R** (how synchronized the swarm is, 0 = chaos, 1 = unison) drives
**saturation**: a desynchronized board washes toward pale white shimmer, and as
the fireflies lock in the color floods back in and saturates. So you don't just
see synchrony in the timing of the flashes — you see it as the color snapping
into focus. A faint per-cell phase offset adds a thread of hue shimmer so the
desynced state still has life.

**Time evolution.** The oscillators never stop rotating, so the board is always
breathing even on a sustained tone — audio *modulates* (coupling, forcing, hue)
rather than *triggers*. The natural-frequency spread guarantees the desynced
state is genuinely moving (a slow rolling shimmer), not frozen.

**Silence.** With no audio, coupling K decays toward zero and the beat
pacemaker goes quiet, so the swarm desynchronizes and drifts. Output brightness
is gated on `rms`, so the flashes fade out as the room goes quiet — the swarm
keeps drifting in the dark and is already mid-shimmer when the music returns,
then re-locks. Embers dying, not a hard blackout.

## ASCII sketch

Brightness = how close each cell's phase is to its flash. `#` bright flash,
`=` mid, `.` dim, ` ` dark.

**Quiet / desynchronized** (low K, no beat) — scattered independent blinks, pale,
slowly rolling:

```
Row 0: [#][ ][ ][=][ ][ ][.][ ][#][ ][ ][ ][=][ ][ ][.]
Row 1: [ ][=][ ][ ][#][ ][ ][.][ ][ ][=][ ][ ][#][ ]
Row 2: [.][ ][#][ ][ ][=][ ][ ][#][ ][ ][.][ ][ ][=]
Row 3: [ ][ ][=][ ][#][ ][ ][ ][=][ ][#][ ][ ][.]
Row 4: [#][ ][ ][.][ ][ ][=][ ][ ][#][ ][ ][=][ ]
Row 5: [ ][=][ ][ ][#][ ][.][ ][ ][=]
```

**Building** (mid K, beat present) — phase waves roll left-to-right, partial
sync, color saturating:

```
Row 0: [=][#][#][=][.][ ][ ][.][=][#][#][=][.][ ][ ][.]
Row 1: [=][#][#][=][.][ ][ ][.][=][#][#][=][.][ ][ ]
Row 2: [.][=][#][#][=][.][ ][ ][.][=][#][#][=][.][ ]
Row 3: [.][=][#][#][=][.][ ][ ][.][=][#][#][=][.]
Row 4: [ ][.][=][#][#][=][.][ ][ ][.][=][#][#][=]
Row 5: [ ][.][=][#][#][=][.][ ][ ][.]
```

**Locked** (high K, on the downbeat) — full unison flash, fully saturated song
color, whole board pulses as one:

```
Row 0: [#][#][#][#][#][#][#][#][#][#][#][#][#][#][#][#]
Row 1: [#][#][#][#][#][#][#][#][#][#][#][#][#][#][#]
Row 2: [#][#][#][#][#][#][#][#][#][#][#][#][#][#][#]
Row 3: [#][#][#][#][#][#][#][#][#][#][#][#][#][#]
Row 4: [#][#][#][#][#][#][#][#][#][#][#][#][#][#]
Row 5: [#][#][#][#][#][#][#][#][#][#]
```

...and a frame later, between beats, the whole board goes dark together before
the next unison flash.

## Audio feature map

| Audio Feature   | System Analogue                    | Effect on Visualization |
|-----------------|------------------------------------|-------------------------|
| `bass` + `rms`  | Coupling strength K                | Louder = stronger neighbor entrainment = swarm pulls toward unison |
| `is_beat`       | Pacemaker kick                     | Snaps the drive phase to its flash; oscillators yanked toward the beat |
| `onset_strength`| External forcing strength F        | How hard the beat pulls the swarm into step (continuous entrainment) |
| `dominant_freq` | Swarm color                        | `freq_to_hue` -> global hue of every firefly (smoothed) |
| `rms`           | Dusk/dawn light level              | Gates overall output brightness; silence fades flashes to black |
| `spectral_flux` | Pacemaker tempo nudge              | Modulates the drive phase's rotation rate so it tracks busier passages |
| `mids`,`highs`  | —                                  | Folded into `rms`/hue indirectly; not used directly |
| `spectrum`      | —                                  | Unused (dominant_freq carries the color) |
| `chroma`        | —                                  | Unused (this effect is about timing sync, not pitch geometry) |

## Implementation notes

- Phase field is a `(6,16)` array on a torus; neighbor coupling via `np.roll`
  in 4 directions, fully vectorized. Invalid cells (row 3-5 gaps) are computed
  but masked out by `grid_to_leds`.
- Integrate with a few substeps per frame for stability when K is high
  (the `sin` coupling can stiffen). Framerate-independent via `dt` from
  `timestamp`.
- Order parameter R = |mean(exp(i*theta))| over valid cells, smoothed; drives
  saturation.
- Brightness pulse: `((1 + cos(theta - flash_phase)) / 2) ** sharpness` — high
  sharpness gives a brief firefly blink; lower gives a softer breathing pulse.
- Deterministic RNG seed for natural-frequency spread so the sim is reproducible.
