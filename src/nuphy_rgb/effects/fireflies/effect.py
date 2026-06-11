"""Fireflies: Kuramoto coupled oscillators entraining to the music.

One phase oscillator per key on a 6x16 grid (rows wrap, columns do not).
Each cell's brightness is a sharpened pulse of its phase -- mostly dark, with
a brief flash as the phase crosses zero, like a blinking firefly.

The music moves the swarm across the synchronization phase transition:

- Loudness sets the neighbor coupling K via a smoothstep that straddles the
  lattice critical coupling (K_c ~ 2-3 for this stencil): quiet music is
  subcritical (scattered independent blinks), loud music supercritical
  (unison).
- Quiet also injects phase noise (a loudness-gated Wiener term), so the
  swarm visibly dissolves within ~1 s when the music drops. Frequency spread
  alone cannot do both jobs: a spread small enough to lock is ~7x too slow
  to desync (see README).
- The flash rate locks to the measured beat period (AudioFrame.beat_period),
  octave-folded into a comfortable blink range; the natural-frequency center
  tracks it so beats can entrain at any tempo.
- On each beat, a recruitment kick sweeps across the columns over a fraction
  of the beat, pulling cells toward the drive phase -- a visible left-to-
  right wipe. The sweep must stay short: staggering full-strength kicks over
  a whole beat imprints a ~2pi phase winding across the board, which caps
  the order parameter near zero.
- A small natural-frequency gradient across columns adds a slow ambient
  drift wave; coupling flattens it when loud, so it mostly shows when quiet.
- A section change (timbral_change) startles the swarm: most phases
  re-randomize and the fireflies regroup.

Synchrony is shown twice: in the timing of the flashes and in color
coherence. Each firefly owns a fixed hue offset scaled by (1 - R), where R
is the Kuramoto order parameter -- a desynced swarm is a scatter of colors,
a locked swarm converges to the song's hue.

See README.md for the design doc and the physics validation notes.
"""

from __future__ import annotations

import colorsys

import numpy as np

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.grid import MAX_COLS, NUM_ROWS, VALID_MASK, grid_to_leds
from nuphy_rgb.visualizer import freq_to_hue
from nuphy_rgb.visualizer_params import VisualizerParam

_DEFAULT_DT = 1.0 / 30.0
_MAX_DT = 0.1
_SUBSTEPS = 4
_TWO_PI = 2.0 * np.pi

# Flash-rate window for octave folding. Folding down keeps flashes on the
# beat (every 2nd/4th beat); folding up adds an off-beat flash.
_FOLD_LO = 0.8
_FOLD_HI = 2.2

_DRIVE_SNAP = 0.5  # fraction the drive phase snaps to its flash on a beat
_SCRAMBLE_COOLDOWN = 2.0  # seconds between section-change scrambles


def fold_rate(rate_hz: float, lo: float, hi: float) -> float:
    """Fold a rate by octaves into [lo, hi]. Returns 0.0 for rate <= 0."""
    if rate_hz <= 0.0:
        return 0.0
    while rate_hz > hi:
        rate_hz *= 0.5
    while rate_hz < lo:
        rate_hz *= 2.0
    return rate_hz


def smoothstep(x: float, lo: float, hi: float) -> float:
    """Hermite smoothstep of x between lo and hi, clamped to [0, 1]."""
    t = min(1.0, max(0.0, (x - lo) / (hi - lo)))
    return t * t * (3.0 - 2.0 * t)


def columns_due(
    sweep_start: float, col_delay: float, prev_t: float, now: float,
    n_cols: int = MAX_COLS,
) -> list[int]:
    """Columns whose scheduled kick time falls in (prev_t, now].

    Column c is scheduled at ``sweep_start + c * col_delay``; with zero
    delay every column lands on the beat frame at once.
    """
    due = []
    for c in range(n_cols):
        t_c = sweep_start + c * col_delay
        if prev_t < t_c <= now:
            due.append(c)
    return due


class Fireflies:
    name = "Fireflies"

    def __init__(self) -> None:
        # One persistent generator for init, integration noise, and
        # scrambles: identical inputs replay identical swarms.
        self._rng = np.random.default_rng(0xF1F1)
        # Low-variance init: uniform[0, 2pi) can freeze into a topologically
        # wound state that never unwinds (measured 3/12 seeds at small
        # frequency spread).
        self._phase = self._rng.normal(0.0, 0.5, size=(NUM_ROWS, MAX_COLS)) % _TWO_PI
        self._spread_unit = self._rng.normal(0.0, 1.0, size=(NUM_ROWS, MAX_COLS))
        self._hue_offset = self._rng.uniform(-0.5, 0.5, size=(NUM_ROWS, MAX_COLS))
        # Column lean in [-0.5, 0.5] for the ambient drift gradient.
        self._col_lean = np.broadcast_to(
            np.arange(MAX_COLS) / (MAX_COLS - 1) - 0.5, (NUM_ROWS, MAX_COLS)
        )
        # Rows wrap, columns don't: edge columns have 3 neighbors.
        self._neighbor_count = np.full((NUM_ROWS, MAX_COLS), 4.0)
        self._neighbor_count[:, 0] = 3.0
        self._neighbor_count[:, -1] = 3.0

        self._drive_phase = 0.0
        self._coupling = 0.0   # smoothed K
        self._order = 0.0      # smoothed Kuramoto order parameter R
        self._hue = 0.0        # smoothed song hue
        self._bright = 0.0     # smoothed output gate
        self._sweep_start = -1e9
        self._sweep_delay = 0.0
        self._last_scramble = -1e9
        self._last_timestamp: float | None = None

        self.params: dict[str, VisualizerParam] = {
            "tempo": VisualizerParam(
                value=1.3, default=1.3, min=0.3, max=3.0,
                description="Fallback flash rate in Hz while no beat period is measured.",
            ),
            "kick_strength": VisualizerParam(
                value=0.6, default=0.6, min=0.0, max=1.0,
                description="Per-beat recruitment kick: fraction of the way cells snap toward the drive phase.",
            ),
            "sweep_fraction": VisualizerParam(
                value=0.2, default=0.2, min=0.0, max=1.0,
                description="Beat fraction the recruitment kick takes to sweep across the columns. 0 = instant unison; a full-beat sweep winds the phases ~2pi across the board and kills unison.",
            ),
            "sharpness": VisualizerParam(
                value=5.0, default=5.0, min=1.0, max=8.0,
                description="Flash sharpness. High = brief firefly blink (mostly dark); low = soft breathing pulse.",
            ),
            "freq_spread": VisualizerParam(
                value=0.03, default=0.03, min=0.0, max=0.15,
                description="Natural blink-rate spread in Hz. Keep small: above ~0.1 the swarm can never lock; below ~0.02 desynced states risk freezing.",
            ),
            "k_quiet": VisualizerParam(
                value=1.0, default=1.0, min=0.0, max=5.0,
                description="Coupling when quiet. Keep below the lattice critical coupling (~2-3) so quiet passages scatter.",
            ),
            "k_loud": VisualizerParam(
                value=7.0, default=7.0, min=0.0, max=15.0,
                description="Coupling when loud. Keep well above critical (>=5) so choruses lock to unison.",
            ),
            "loud_lo": VisualizerParam(
                value=0.35, default=0.35, min=0.0, max=1.0,
                description="Loudness where coupling starts rising toward k_loud.",
            ),
            "loud_hi": VisualizerParam(
                value=0.70, default=0.70, min=0.0, max=1.0,
                description="Loudness where coupling reaches k_loud.",
            ),
            "noise_d": VisualizerParam(
                value=2.0, default=2.0, min=0.0, max=6.0,
                description="Phase noise at silence in rad/sqrt(s); fades out as loudness rises. 2.0 dissolves a locked swarm in ~0.8 s.",
            ),
            "drift_gradient": VisualizerParam(
                value=0.25, default=0.25, min=0.0, max=1.0,
                description="Blink-rate gradient across columns in Hz: a slow ambient drift wave. Coupling flattens it when loud.",
            ),
            "scramble_threshold": VisualizerParam(
                value=0.5, default=0.5, min=0.0, max=1.0,
                description="timbral_change level that startles the swarm into re-randomizing.",
            ),
            "scramble_amount": VisualizerParam(
                value=0.7, default=0.7, min=0.0, max=1.0,
                description="Fraction of fireflies re-randomized on a section change.",
            ),
            "hue_scatter": VisualizerParam(
                value=0.35, default=0.35, min=0.0, max=1.0,
                description="Hue spread of a fully desynced swarm. Colors converge to the song hue as the swarm locks.",
            ),
            "decay": VisualizerParam(
                value=0.90, default=0.90, min=0.70, max=0.99,
                description="Per-frame retention of coupling when audio drops. Higher = the swarm coasts in sync longer.",
            ),
        }
        self._rate = self.params["tempo"].value  # smoothed flash rate, Hz

    def _dt(self, timestamp: float) -> float:
        if self._last_timestamp is None:
            self._last_timestamp = timestamp
            return _DEFAULT_DT
        dt = timestamp - self._last_timestamp
        self._last_timestamp = timestamp
        if dt <= 0.0:
            return _DEFAULT_DT
        return min(dt, _MAX_DT)

    def _neighbor_coupling(self, phase: np.ndarray) -> np.ndarray:
        """Mean sin(theta_neighbor - theta); rows wrap, columns do not."""
        total = (
            np.sin(np.roll(phase, 1, axis=0) - phase)
            + np.sin(np.roll(phase, -1, axis=0) - phase)
        )
        total[:, 1:] += np.sin(phase[:, :-1] - phase[:, 1:])
        total[:, :-1] += np.sin(phase[:, 1:] - phase[:, :-1])
        return total / self._neighbor_count

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        prev_t = self._last_timestamp
        dt = self._dt(frame.timestamp)
        now = frame.timestamp
        if prev_t is None:
            prev_t = now - dt
        p = self.params

        # --- audio -> driving terms ----------------------------------------
        loud = min(1.0, 0.5 * frame.bass + 0.5 * frame.rms)
        k_target = p["k_quiet"].value + (
            p["k_loud"].value - p["k_quiet"].value
        ) * smoothstep(loud, p["loud_lo"].value, p["loud_hi"].value)
        decay = p["decay"].value
        # Rise fast toward stronger coupling, decay slowly when music drops.
        if k_target < self._coupling:
            self._coupling = max(k_target, self._coupling * decay)
        else:
            self._coupling = 0.5 * (self._coupling + k_target)
        noise_d = p["noise_d"].value * (1.0 - loud)

        # Output brightness gate from rms: fast attack, slow release.
        gate = min(1.0, 1.4 * frame.rms)
        self._bright = gate if gate > self._bright else 0.85 * self._bright + 0.15 * gate

        # Song hue, smoothed so it glides rather than jumps.
        if frame.dominant_freq > 0.0:
            target_hue = freq_to_hue(frame.dominant_freq)
            dh = (target_hue - self._hue + 0.5) % 1.0 - 0.5
            self._hue = (self._hue + 0.1 * dh) % 1.0

        # --- pacemaker ------------------------------------------------------
        measured = 0.0
        if frame.beat_period > 0.0:
            measured = fold_rate(1.0 / frame.beat_period, _FOLD_LO, _FOLD_HI)
        target_rate = measured if measured > 0.0 else p["tempo"].value
        self._rate += 0.1 * (target_rate - self._rate)
        self._drive_phase = (self._drive_phase + _TWO_PI * self._rate * dt) % _TWO_PI
        if frame.is_beat:
            err = (-self._drive_phase + np.pi) % _TWO_PI - np.pi
            self._drive_phase = (self._drive_phase + _DRIVE_SNAP * err) % _TWO_PI
            self._sweep_start = now
            self._sweep_delay = (
                p["sweep_fraction"].value * frame.beat_period / MAX_COLS
            )

        # --- recruitment kicks ----------------------------------------------
        for c in columns_due(self._sweep_start, self._sweep_delay, prev_t, now):
            err = (self._drive_phase - self._phase[:, c] + np.pi) % _TWO_PI - np.pi
            self._phase[:, c] = (
                self._phase[:, c] + p["kick_strength"].value * err
            ) % _TWO_PI

        # --- section change startles the swarm ------------------------------
        if (
            frame.timbral_change > p["scramble_threshold"].value
            and now - self._last_scramble > _SCRAMBLE_COOLDOWN
        ):
            self._last_scramble = now
            mask = self._rng.random((NUM_ROWS, MAX_COLS)) < p["scramble_amount"].value
            self._phase[mask] = self._rng.uniform(0.0, _TWO_PI, size=int(mask.sum()))

        # --- integrate Kuramoto field ----------------------------------------
        # Natural frequencies: center tracks the flash rate; spread and the
        # drift gradient are absolute so tempo changes don't inflate them.
        omega = (
            _TWO_PI * self._rate
            + self._spread_unit * (_TWO_PI * p["freq_spread"].value)
            + self._col_lean * (_TWO_PI * p["drift_gradient"].value)
        )
        k = self._coupling
        sub_dt = dt / _SUBSTEPS
        noise_scale = noise_d * np.sqrt(sub_dt)
        for _ in range(_SUBSTEPS):
            dtheta = omega + k * self._neighbor_coupling(self._phase)
            noise = noise_scale * self._rng.standard_normal((NUM_ROWS, MAX_COLS))
            self._phase = (self._phase + dtheta * sub_dt + noise) % _TWO_PI

        # --- order parameter --------------------------------------------------
        z = np.exp(1j * self._phase)[VALID_MASK]
        r = float(np.abs(np.mean(z)))
        self._order = 0.6 * self._order + 0.4 * r

        # --- render -----------------------------------------------------------
        pulse = ((1.0 + np.cos(self._phase)) * 0.5) ** p["sharpness"].value
        value = pulse * self._bright
        scatter = p["hue_scatter"].value * (1.0 - self._order)

        grid = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        for r_idx in range(NUM_ROWS):
            for c_idx in range(MAX_COLS):
                v = value[r_idx, c_idx]
                if v <= 0.004:
                    continue
                h = (self._hue + scatter * self._hue_offset[r_idx, c_idx]) % 1.0
                rr, gg, bb = colorsys.hsv_to_rgb(h, 0.85, float(v))
                grid[r_idx, c_idx, 0] = rr
                grid[r_idx, c_idx, 1] = gg
                grid[r_idx, c_idx, 2] = bb

        return grid_to_leds(grid)
