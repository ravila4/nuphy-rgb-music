"""Interference Pond visualizer effect.

Spawns wave ripples on beats; their interference patterns produce
constructive/destructive color mixing across the LED grid.
"""

import colorsys
import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from nuphy_rgb.audio import AudioFrame, ExpFilter
from nuphy_rgb.effects.grid import LED_X, LED_Y, NUM_LEDS
from nuphy_rgb.visualizer import freq_to_hue
from nuphy_rgb.visualizer_params import VisualizerParam

_MAX_RIPPLES = 8
_AMPLITUDE_THRESHOLD = 0.01
_DEFAULT_DT = 1.0 / 30.0


@dataclass
class _Ripple:
    cx: float
    cy: float
    hue: float
    amplitude: float
    radius: float
    wavelength: float


class InterferencePond:
    """Ripple-based interference pattern visualizer.

    Beats spawn a new ripple at a random keyboard position. Ripples expand
    outward with wavelength tuned to bass, then decay. Their superimposed
    wave fields produce constructive and destructive interference that is
    mapped to hue, saturation, and brightness per LED.
    """

    name = "Interference Pond"

    def __init__(self) -> None:
        self._ripples: deque[_Ripple] = deque(maxlen=_MAX_RIPPLES)
        self._last_timestamp: float | None = None
        self._peak_wave: float = 0.01
        self._rng = np.random.default_rng(42)
        self._brightness_filter = ExpFilter(alpha_rise=0.9, alpha_decay=0.3)
        self.params: dict[str, VisualizerParam] = {
            "brightness_gain": VisualizerParam(
                value=5.0, default=5.0, min=1.0, max=10.0,
                description="RMS → brightness sensitivity (higher = brighter for quiet audio)",
            ),
            "ripple_decay": VisualizerParam(
                value=0.96, default=0.96, min=0.90, max=0.99,
                description="Ripple amplitude decay per frame (higher = longer-lived ripples)",
            ),
            "wavelength": VisualizerParam(
                value=0.15, default=0.15, min=0.08, max=0.30,
                description="Base wavelength in grid units (lower = fine bands, higher = chunky)",
            ),
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._compute_dt(frame.timestamp)

        if frame.is_beat:
            self._spawn_ripple(frame)

        self._update_ripples(dt, frame.bass)

        return self._build_frame(frame)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_dt(self, timestamp: float) -> float:
        if self._last_timestamp is None:
            dt = _DEFAULT_DT
        else:
            dt = max(timestamp - self._last_timestamp, 1e-4)
        self._last_timestamp = timestamp
        return dt

    def _spawn_ripple(self, frame: AudioFrame) -> None:
        hue = freq_to_hue(frame.dominant_freq)
        wavelength = self.params["wavelength"].get() + 0.1 * frame.bass
        amplitude = 1.0 + min(frame.onset_strength * 0.3, 0.3)
        cx = float(self._rng.uniform(0.0, 1.0))
        cy = float(self._rng.uniform(0.0, 1.0))
        ripple = _Ripple(
            cx=cx,
            cy=cy,
            hue=hue,
            amplitude=amplitude,
            radius=0.0,
            wavelength=wavelength,
        )
        self._ripples.append(ripple)

    def _update_ripples(self, dt: float, bass: float) -> None:
        decay = self.params["ripple_decay"].get() - 0.02 * bass
        expand = dt * (0.4 + 0.3 * bass)
        survivors = deque(maxlen=_MAX_RIPPLES)
        for r in self._ripples:
            r.radius += expand
            r.amplitude *= decay
            if r.amplitude >= _AMPLITUDE_THRESHOLD:
                survivors.append(r)
        self._ripples = survivors

    def _build_frame(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        if not self._ripples:
            return [(0, 0, 0)] * NUM_LEDS

        # Accumulate wave contributions per LED (vectorized over 84 positions)
        wave_sum = np.zeros(NUM_LEDS, dtype=np.float64)
        sin_weighted = np.zeros(NUM_LEDS, dtype=np.float64)
        cos_weighted = np.zeros(NUM_LEDS, dtype=np.float64)

        for r in self._ripples:
            dx = LED_X - r.cx
            dy = LED_Y - r.cy
            dist = np.sqrt(dx * dx + dy * dy)

            wave = np.sin(2.0 * math.pi * (dist - r.radius) / r.wavelength)
            sigma = 0.12 + 0.06 * r.radius
            envelope = np.exp(-0.5 * ((dist - r.radius) / sigma) ** 2)
            contrib = r.amplitude * envelope * wave

            wave_sum += contrib

            # Weighted hue accumulation for blending
            weight = np.abs(contrib)
            angle = 2.0 * math.pi * r.hue
            sin_weighted += weight * math.sin(angle)
            cos_weighted += weight * math.cos(angle)

        # Auto-gain: track peak absolute wave value
        peak = float(np.max(np.abs(wave_sum)))
        self._peak_wave = max(peak, self._peak_wave * 0.98, 1e-6)
        norm_wave = wave_sum / self._peak_wave

        # Brightness from raw RMS, linear curve; sqrt on the normalized
        # wave lifts mid-range LEDs so the pattern reads clearly instead of
        # collapsing into near-black around a single peak.
        scaled = min(frame.raw_rms * self.params["brightness_gain"].get(), 1.0)
        brightness_scale = self._brightness_filter.update(scaled)
        brightness_arr = np.sqrt(np.abs(norm_wave)) * brightness_scale

        # Blended hue via circular mean
        blended_angle = np.arctan2(sin_weighted, cos_weighted)
        blended_hue = (blended_angle / (2.0 * math.pi)) % 1.0

        # Destructive interference -> complementary hue, lower saturation
        constructive = norm_wave >= 0
        hue_arr = np.where(constructive, blended_hue, (blended_hue + 0.5) % 1.0)
        sat_arr = np.where(constructive, 0.85, 0.6)

        # White sparkle gated by highs energy
        sparkle_threshold = 0.7
        if frame.highs > sparkle_threshold:
            sparkle_prob = min(1.0, (frame.highs - sparkle_threshold) / 0.3) * 0.15
            sparkle_mask = self._rng.random(NUM_LEDS) < sparkle_prob
            sat_arr = np.where(sparkle_mask, 0.0, sat_arr)
            brightness_arr = np.where(sparkle_mask, np.minimum(brightness_arr * 1.5, 1.0), brightness_arr)

        # HSV -> RGB
        result: list[tuple[int, int, int]] = []
        for i in range(NUM_LEDS):
            r_f, g_f, b_f = colorsys.hsv_to_rgb(
                float(hue_arr[i]),
                float(sat_arr[i]),
                float(brightness_arr[i]),
            )
            result.append((int(r_f * 255), int(g_f * 255), int(b_f * 255)))
        return result
