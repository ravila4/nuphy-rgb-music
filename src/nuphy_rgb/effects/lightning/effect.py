"""Lightning: branching discharge on beat with white-hot → colored decay.

Each bass beat triggers a branching random-walk bolt from row 0 to row 5.
Strike cells store per-cell intensity and hue; the output color is
reconstructed as HSV(hue, 1 - intensity, intensity), so a fresh strike
reads as pure white and fades through its plasma hue to black.

Designed as the only "hard discrete attack" effect in the catalog — every
other shipped effect is slow and continuous. See research/lightning.md.
"""

from __future__ import annotations

import colorsys
import random

import numpy as np

from nuphy_rgb.plugin_api import (
    AudioFrame,
    MAX_COLS,
    NUM_ROWS,
    VisualizerParam,
    freq_to_hue,
    grid_to_leds,
)

_DEFAULT_DT = 1.0 / 30.0


class Lightning:
    name = "Lightning"

    def __init__(self) -> None:
        self._intensity = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        self._hue = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        self._last_timestamp: float | None = None
        self._time = 0.0
        self._last_strike_t = -1.0
        self._last_path: list[tuple[int, int]] = []
        self._last_strike_col: int = MAX_COLS // 2
        self._rng = random.Random()

        self.params: dict[str, VisualizerParam] = {
            "decay_rate": VisualizerParam(
                value=0.90, default=0.90, min=0.80, max=0.97,
                description="Intensity decay per frame. Lower = faster fade to black.",
            ),
            "peak_intensity": VisualizerParam(
                value=1.0, default=1.0, min=0.5, max=1.0,
                description="Strike core brightness. 1.0 = pure white at peak.",
            ),
            "branch_chance": VisualizerParam(
                value=0.4, default=0.4, min=0.0, max=1.0,
                description="Branch spawn probability per main-channel node (scaled by bass).",
            ),
            "cooldown_ms": VisualizerParam(
                value=80.0, default=80.0, min=30.0, max=300.0,
                description="Minimum time between strikes. Prevents strobing.",
            ),
            "ambient_strength": VisualizerParam(
                value=0.05, default=0.05, min=0.0, max=0.20,
                description="Distant heat-lightning flicker on row 0-1 between strikes.",
            ),
            "blue_bias": VisualizerParam(
                value=0.65, default=0.65, min=0.0, max=1.0,
                description="Compress plasma hue toward blue. 0 = full freq spectrum, 1 = narrow blue-violet band. Default 0.65 keeps teals in range but drops green.",
            ),
        }

    def _plasma_hue(self, frame: AudioFrame) -> float:
        # Center plasma color on blue (hue 0.625) and compress the freq
        # range inward with blue_bias. Low freq → teal, high freq → violet
        # without landing in green or red at the default bias.
        raw = freq_to_hue(frame.dominant_freq)
        bias = self.params["blue_bias"].get()
        # center = 0.65 (pure blue, slightly violet-shifted). With default
        # bias 0.65 a 60 Hz kick lands at hue 0.47 (teal), 200 Hz at 0.57
        # (blue), 1 kHz at 0.70 (violet), 4 kHz at 0.81 (magenta). Pure
        # green (0.33) is cleanly outside even for sub-bass rumble.
        center = 0.65
        width = 1.0 - bias * 0.7
        return (center + (raw - 0.5) * width) % 1.0

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._compute_dt(frame.timestamp)
        self._time += dt

        # dt-corrected decay: param is calibrated at 30fps, rescale to actual dt
        decay = self.params["decay_rate"].get() ** (dt / _DEFAULT_DT)
        self._intensity *= decay

        cooldown_s = self.params["cooldown_ms"].get() / 1000.0
        time_since_strike = self._time - self._last_strike_t

        if frame.is_beat and time_since_strike >= cooldown_s:
            self._strike(frame)
        elif frame.mid_beat and self._last_path and time_since_strike >= cooldown_s * 0.5:
            self._reignite(frame)

        if time_since_strike > 0.2:
            self._ambient_flicker(frame)

        np.clip(self._intensity, 0.0, 1.0, out=self._intensity)
        return self._reconstruct_rgb()

    def _compute_dt(self, timestamp: float) -> float:
        if self._last_timestamp is None:
            dt = _DEFAULT_DT
        else:
            dt = max(timestamp - self._last_timestamp, 1e-4)
        self._last_timestamp = timestamp
        return dt

    def _strike(self, frame: AudioFrame) -> None:
        strike_col = self._pick_strike_column(frame)
        branch_scale = max(0.0, min(frame.bass, 1.0))
        path = self._generate_bolt(strike_col, branch_scale)

        peak = self.params["peak_intensity"].get() * (
            0.6 + 0.4 * max(0.0, min(frame.onset_strength, 1.0))
        )
        hue = self._plasma_hue(frame)

        for r, c in path:
            if self._intensity[r, c] < peak:
                self._intensity[r, c] = peak
            self._hue[r, c] = hue

        self._last_path = path
        self._last_strike_t = self._time
        self._last_strike_col = strike_col

    def _reignite(self, frame: AudioFrame) -> None:
        # Mid-beat: half-intensity flare on the most recent path. Cheap way
        # to make sustained mid content crackle without spawning new bolts.
        reflare = 0.5 * self.params["peak_intensity"].get()
        hue = self._plasma_hue(frame)
        for r, c in self._last_path:
            if self._intensity[r, c] < reflare:
                self._intensity[r, c] = reflare
            self._hue[r, c] = hue

    def _pick_strike_column(self, frame: AudioFrame) -> int:
        # "Storm cell" continuity: successive strikes land within ±3 cols
        # of the previous one. On strong onsets (>0.5) the storm jumps to
        # a fresh column to keep the effect visually varied.
        if frame.onset_strength > 0.5:
            return self._rng.randint(2, MAX_COLS - 3)
        delta = self._rng.randint(-3, 3)
        return max(0, min(MAX_COLS - 1, self._last_strike_col + delta))

    def _generate_bolt(
        self, strike_col: int, branch_scale: float,
    ) -> list[tuple[int, int]]:
        rng = self._rng
        path: list[tuple[int, int]] = []
        main: list[tuple[int, int]] = [(0, strike_col)]
        c = strike_col
        for r in range(1, NUM_ROWS):
            # Horizontal jitter: bias toward 0 so the main channel reads vertical
            c += rng.choice((-1, 0, 0, 0, 1))
            c = max(0, min(MAX_COLS - 1, c))
            main.append((r, c))
        path.extend(main)

        branch_prob = self.params["branch_chance"].get() * (0.3 + 0.7 * branch_scale)
        for i in range(1, len(main) - 1):
            if rng.random() >= branch_prob:
                continue
            br_r, br_c = main[i]
            direction = rng.choice((-1, 1))
            steps = rng.randint(2, 4)
            for _ in range(steps):
                br_r += 1
                if br_r >= NUM_ROWS:
                    break
                br_c += direction + rng.choice((-1, 0, 1))
                br_c = max(0, min(MAX_COLS - 1, br_c))
                path.append((br_r, br_c))

        return path

    def _ambient_flicker(self, frame: AudioFrame) -> None:
        # Distant heat lightning: occasional dim sparks on the top two rows,
        # gated by raw_rms. Colored by current dominant frequency so they
        # blend with the strike palette.
        strength = self.params["ambient_strength"].get()
        if strength <= 0.0 or frame.raw_rms < 0.05:
            return
        if self._rng.random() > 0.12:
            return
        amplitude = strength * max(0.0, min(frame.raw_rms * 2.0, 1.0))
        r = self._rng.randint(0, 1)
        c = self._rng.randint(0, MAX_COLS - 1)
        if self._intensity[r, c] < amplitude:
            self._intensity[r, c] = amplitude
            self._hue[r, c] = self._plasma_hue(frame)

    def _reconstruct_rgb(self) -> list[tuple[int, int, int]]:
        # HSV(hue, 1 - intensity, intensity): at intensity=1 → pure white,
        # at intensity=0.5 → half-saturated color at half brightness,
        # at intensity=0 → black. Encodes the white-hot → colored fade in
        # one expression without any phase tracking.
        rgb = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        intensity = self._intensity
        hue = self._hue
        nonzero = np.argwhere(intensity > 1e-4)
        for r, c in nonzero:
            v = float(intensity[r, c])
            s = 1.0 - v
            r_, g_, b_ = colorsys.hsv_to_rgb(float(hue[r, c]), s, v)
            rgb[r, c, 0] = r_
            rgb[r, c, 1] = g_
            rgb[r, c, 2] = b_
        return grid_to_leds(rgb)
