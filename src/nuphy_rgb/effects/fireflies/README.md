# Fireflies

*Kuramoto coupled oscillators crossing the synchronization phase transition
with the music.*

## Philosophy

**The system.** Southeast Asian fireflies (*Pteroptyx*) gather in mangrove
trees by the thousands and, over a few minutes, spontaneously flash in unison.
No conductor — each firefly nudges its phase toward the ones it can see, and
global synchrony emerges from local rules. This is the canonical **Kuramoto
model**: phase oscillators, each with its own natural frequency, weakly coupled
to neighbors. Fireflies puts one oscillator on every key. The drama is the
**phase transition** between incoherence and unison — and the music decides
which side of it you're on.

Each LED holds a phase θ; brightness is a sharpened pulse that flashes as θ
crosses zero. The grid couples each cell to its 4 nearest neighbors; rows wrap,
columns do not (it's a keyboard, not a torus — and a directional sweep is
geometrically impossible on a closed loop).

**The transition, engineered to actually cross.** Numerical validation against
this exact 6x16 lattice (see "Physics notes") showed the obvious
parameterization cannot work: a frequency spread wide enough to dissolve the
swarm in seconds never locks, and a spread narrow enough to lock takes >12 s
to dissolve. The two roles are therefore decoupled:

- **Lock**: small fixed frequency spread (σ = 2π·0.03 rad/s) + coupling K
  driven by loudness through a smoothstep that straddles the lattice critical
  coupling (K_c ≈ 2–3). Quiet → K ≈ 1, subcritical scatter. Loud → K ≈ 7,
  supercritical unison.
- **Dissolve**: loudness-gated phase noise (Wiener term, D = 2 rad/√s at
  silence). When the music drops, the swarm visibly dissolves in ~0.8 s into a
  live random-walk shimmer rather than a frozen drift.

**Beat entrainment.** The flash rate locks to the measured beat period
(`AudioFrame.beat_period`), octave-folded into 0.8–2.2 Hz so fast songs flash
every second beat rather than strobing. The oscillators' natural-frequency
center tracks the folded rate, so beats entrain at any tempo with only
per-beat kicks — there is **no continuous global forcing term**. (The v1
forcing F=7 pinned every cell to a fixed-rate metronome at all times; it was
half the reason v1 read as a strobe.)

**The recruitment sweep.** On each beat, a kick pulls cells toward the drive
phase, staggered column-by-column over `sweep_fraction` of the beat (~100 ms):
a left-to-right wipe that local coupling then cleans up. The sweep must stay a
fraction of the beat: staggered phase-resets accumulate a winding of
2π·rate·T_sweep across the board, so a full-beat sweep winds ~2π and caps the
order parameter near zero. Diffusive coupling itself propagates at <1 cell/s —
30x too slow to carry a beat-synced front — so the front is painted
kinematically and the physics sustains it.

**Color is coherence.** Hue comes from the music (`dominant_freq` →
`freq_to_hue`, smoothed). Each firefly owns a fixed hue offset scaled by
(1 − R), where R is the Kuramoto order parameter: a desynced swarm is a
scatter of individual colors; as it locks, the colors converge to the song's
hue. Synchrony is visible twice — flash timing and color focus.

**Section changes.** A spike in `timbral_change` re-randomizes most phases
(2 s cooldown): the swarm startles, scatters in color and timing, and
re-gathers. The gather-from-chaos story replays at every section boundary
instead of happening once at startup.

**Silence.** Brightness gates on `rms`; coupling decays and noise rises, so
the swarm dissolves in the dark and is already mid-shimmer when the music
returns.

## ASCII sketch

`#` bright flash, `=` mid, `.` dim, ` ` dark.

**Quiet / desynced** (subcritical K, noise on) — scattered blinks, each its
own color:

```
Row 0: [#][ ][ ][=][ ][ ][.][ ][#][ ][ ][ ][=][ ][ ][.]
Row 1: [ ][=][ ][ ][#][ ][ ][.][ ][ ][=][ ][ ][#][ ]
Row 2: [.][ ][#][ ][ ][=][ ][ ][#][ ][ ][.][ ][ ][=]
Row 3: [ ][ ][=][ ][#][ ][ ][ ][=][ ][#][ ][ ][.]
Row 4: [#][ ][ ][.][ ][ ][=][ ][ ][#][ ][ ][=][ ]
Row 5: [ ][=][ ][ ][#][ ][.][ ][ ][=]
```

**Beat hits** — recruitment kick sweeps the columns over ~1/5 beat:

```
t+0ms   [#][.][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ]
t+40ms  [=][#][#][.][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ]
t+80ms  [.][=][#][#][#][.][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ]
t+120ms [ ][.][=][=][#][#][#][#][.][ ][ ][ ][ ][ ][ ][ ]
```

**Locked chorus** (supercritical K) — unison flash on the beat, one color:

```
Row 0: [#][#][#][#][#][#][#][#][#][#][#][#][#][#][#][#]
Row 1: [#][#][#][#][#][#][#][#][#][#][#][#][#][#][#]
Row 2: [#][#][#][#][#][#][#][#][#][#][#][#][#][#][#]
       ...then the whole board goes dark together.
```

## Audio feature map

| Audio Feature    | System Analogue              | Effect |
|------------------|------------------------------|--------|
| `bass` + `rms`   | Coupling K (smoothstep)      | Quiet = subcritical scatter; loud = supercritical unison |
| `bass` + `rms`   | Phase noise D (inverted)     | Quiet = swarm dissolves in ~0.8 s |
| `beat_period`    | Drive rate (octave-folded)   | Flash rate locks to the song's tempo |
| `is_beat`        | Recruitment kick + sweep     | L→R wipe pulling cells onto the beat |
| `dominant_freq`  | Swarm hue                    | Song color; per-cell scatter shrinks as R rises |
| `rms`            | Dusk/dawn light level        | Gates overall brightness |
| `timbral_change` | Startle                      | Scrambles most phases; swarm re-gathers |

## Physics notes (validated numerically on this lattice, 2026-06-11)

- **Lattice K_c ≈ 2–3** with the 0.25-mean 4-neighbor stencil at σ = 2π·0.03 —
  far above mean-field intuition. K ≥ 5 locks (R > 0.9); at the v1 spread
  (2π·0.22) *no* K in [0,12] ever locks, which is why v1 sat at R 0.3–0.65.
- **Decay law**: from a locked state with K→0, t(R<0.2) ≈ 0.32/σ_Hz. Locking
  and fast desync need σ values ~7x apart — hence the noise term.
- **Winding traps**: uniform[0, 2π) initialization at small σ can freeze into
  a topologically wound state (3/12 seeds); init is low-variance instead.
- **Front speeds**: diffusive phase spreading ~0.4–1 cell/s; a one-beat
  16-column crossing would need ~25–30 cells/s. Beat-synced fronts must be
  kinematic (delayed kicks); the `drift_gradient` ω-lean supplies the slow
  ambient wave (coupling flattens it when loud, so it shows when quiet).
- Explicit Euler, 4 substeps: max phase step ~0.3 rad at extreme params —
  stable with 2–3x margin.

## Tuning

All constants the physics doesn't pin down are live-tunable
`VisualizerParam`s: `k_quiet`/`k_loud`/`loud_lo`/`loud_hi` (transition
placement), `noise_d` (dissolve speed), `sweep_fraction`/`kick_strength`
(beat wipe), `drift_gradient` (ambient wave), `hue_scatter`, `sharpness`,
`scramble_threshold`/`scramble_amount`, `tempo` (fallback rate), `decay`.
