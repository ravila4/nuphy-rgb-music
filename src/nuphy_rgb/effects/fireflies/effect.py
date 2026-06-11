"""Fireflies: Kuramoto coupled oscillators entraining to the music.

One phase oscillator per key on a 6x16 torus. Each cell's brightness is a
sharpened pulse of its phase -- mostly dark, with a brief flash as the phase
crosses zero, like a blinking firefly. Left alone, every oscillator runs at a
slightly different natural frequency and the board is an incoherent shimmer of
scattered blinks.

The music drives synchronization. Loudness (bass + rms) sets the local coupling
strength K: louder passages make neighbors entrain each other and pull the swarm
toward unison. The beat is an external pacemaker -- a drive phase advances
continuously, gets kicked on every beat, and a forcing term yanks all the
oscillators toward it. That is entrainment to an external rhythm, the literal
reason your foot taps along.

Color is the song's color (dominant_freq -> hue), and the Kuramoto order
parameter R drives saturation: a desynchronized board washes toward pale white
shimmer; as the fireflies lock in, the color floods back. So synchrony shows up
twice -- in the timing of the flashes and in the color snapping into focus.

See research/fireflies.md for the full design doc.
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
_VALID_COUNT = float(np.count_nonzero(VALID_MASK))


class Fireflies:
    name = "Fireflies"

    def __init__(self) -> None:
        # Deterministic spread of natural frequencies so the desynced state is
        # genuinely moving and the sim is reproducible across identical inputs.
        rng = np.random.default_rng(0xF1F1)
        self._phase = rng.uniform(0.0, _TWO_PI, size=(NUM_ROWS, MAX_COLS))
        # Base natural angular frequency ~1.3 Hz pulse, +/- spread per cell.
        base = _TWO_PI * 1.3
        spread = rng.normal(0.0, _TWO_PI * 0.22, size=(NUM_ROWS, MAX_COLS))
        self._omega = base + spread

        self._drive_phase = 0.0
        self._coupling = 0.0   # smoothed K
        self._forcing = 0.0    # smoothed F
        self._order = 0.0      # smoothed Kuramoto order parameter R
        self._hue = 0.0        # smoothed song hue
        self._bright = 0.0     # smoothed output gate
        self._last_timestamp: float | None = None

        self.params: dict[str, VisualizerParam] = {
            "coupling_gain": VisualizerParam(
                value=9.0, default=9.0, min=0.0, max=25.0,
                description="How strongly loudness drives neighbor coupling K. Higher = the swarm locks into unison more eagerly on loud passages.",
            ),
            "forcing_gain": VisualizerParam(
                value=7.0, default=7.0, min=0.0, max=20.0,
                description="How hard the beat pacemaker pulls oscillators toward the downbeat. Higher = tighter entrainment to the rhythm.",
            ),
            "beat_kick": VisualizerParam(
                value=0.55, default=0.55, min=0.0, max=1.0,
                description="Fraction of the way the drive phase snaps to its flash on each beat. Higher = punchier downbeat.",
            ),
            "sharpness": VisualizerParam(
                value=2.6, default=2.6, min=1.0, max=8.0,
                description="Flash sharpness. High = brief firefly blink (mostly dark); low = soft breathing pulse.",
            ),
            "tempo": VisualizerParam(
                value=1.3, default=1.3, min=0.3, max=3.0,
                description="Base pulse rate of the swarm in Hz (natural firefly blink rate).",
            ),
            "decay": VisualizerParam(
                value=0.90, default=0.90, min=0.70, max=0.99,
                description="Per-frame retention of coupling/forcing when audio drops. Higher = the swarm coasts in sync longer after the music quiets.",
            ),
        }

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
        """Mean sin(theta_neighbor - theta) over 4 torus neighbors."""
        coupling = (
            np.sin(np.roll(phase, 1, axis=0) - phase)
            + np.sin(np.roll(phase, -1, axis=0) - phase)
            + np.sin(np.roll(phase, 1, axis=1) - phase)
            + np.sin(np.roll(phase, -1, axis=1) - phase)
        )
        return coupling * 0.25

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._dt(frame.timestamp)
        p = self.params

        # --- audio -> driving terms ----------------------------------------
        loud = min(1.0, 0.6 * frame.bass + 0.6 * frame.rms)
        target_k = p["coupling_gain"].value * loud
        target_f = p["forcing_gain"].value * min(1.0, frame.onset_strength + 0.3 * frame.rms)

        decay = p["decay"].value
        # Rise fast toward stronger driving, decay slowly when the music drops.
        self._coupling = max(target_k, self._coupling * decay) if target_k < self._coupling else 0.5 * (self._coupling + target_k)
        self._forcing = max(target_f, self._forcing * decay) if target_f < self._forcing else 0.5 * (self._forcing + target_f)

        # Output brightness gate from rms: fast attack, slow release.
        gate = min(1.0, 1.4 * frame.rms)
        self._bright = gate if gate > self._bright else 0.85 * self._bright + 0.15 * gate

        # Song hue, smoothed so it glides rather than jumps.
        if frame.dominant_freq > 0.0:
            target_hue = freq_to_hue(frame.dominant_freq)
            # shortest path around the hue circle
            dh = (target_hue - self._hue + 0.5) % 1.0 - 0.5
            self._hue = (self._hue + 0.1 * dh) % 1.0

        # --- pacemaker -----------------------------------------------------
        # Drive phase advances at base tempo, nudged faster on busy passages,
        # and snaps toward its flash (phase 0) on each beat.
        drive_omega = _TWO_PI * p["tempo"].value * (1.0 + 0.5 * frame.spectral_flux)
        self._drive_phase = (self._drive_phase + drive_omega * dt) % _TWO_PI
        if frame.is_beat:
            # pull drive toward 0 (flash) by beat_kick fraction
            err = (0.0 - self._drive_phase + np.pi) % _TWO_PI - np.pi
            self._drive_phase = (self._drive_phase + p["beat_kick"].value * err) % _TWO_PI

        # --- integrate Kuramoto field --------------------------------------
        omega = self._omega * (p["tempo"].value / 1.3)
        k = self._coupling
        f = self._forcing
        sub_dt = dt / _SUBSTEPS
        for _ in range(_SUBSTEPS):
            dtheta = (
                omega
                + k * self._neighbor_coupling(self._phase)
                + f * np.sin(self._drive_phase - self._phase)
            )
            self._phase = (self._phase + dtheta * sub_dt) % _TWO_PI

        # --- order parameter -> saturation ---------------------------------
        z = np.exp(1j * self._phase)[VALID_MASK]
        r = float(np.abs(np.mean(z)))
        self._order = 0.6 * self._order + 0.4 * r

        # --- render --------------------------------------------------------
        # Brightness: sharpened cosine pulse, flashing as phase crosses 0.
        pulse = ((1.0 + np.cos(self._phase)) * 0.5) ** p["sharpness"].value
        value = pulse * self._bright

        # Saturation: pale when desynced, saturated when locked.
        sat = 0.25 + 0.7 * self._order
        # Faint per-cell hue shimmer from phase keeps the desynced state alive.
        hue_shimmer = 0.04 * np.sin(self._phase)

        grid = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        for r_idx in range(NUM_ROWS):
            for c_idx in range(MAX_COLS):
                v = value[r_idx, c_idx]
                if v <= 0.004:
                    continue
                h = (self._hue + hue_shimmer[r_idx, c_idx]) % 1.0
                rr, gg, bb = colorsys.hsv_to_rgb(h, sat, float(v))
                grid[r_idx, c_idx, 0] = rr
                grid[r_idx, c_idx, 1] = gg
                grid[r_idx, c_idx, 2] = bb

        return grid_to_leds(grid)
