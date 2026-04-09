"""Standing Waves: cymatics-inspired chroma visualization.

Each active pitch class generates a spatial sine wave across the keyboard.
Waves are summed per-pixel, creating interference patterns that shift with
the harmony. Consonant intervals produce stable patterns; dissonant ones
produce complex, shimmering textures.
"""

import colorsys
import math

import numpy as np

from nuphy_rgb.audio import AudioFrame, ExpFilter, NUM_CHROMA_BINS
from nuphy_rgb.effects.grid import MAX_COLS, NUM_ROWS, grid_to_leds

TWO_PI = 2.0 * math.pi


class StandingWaves:
    """Cymatics — the keyboard as a vibrating surface shaped by harmony."""

    name = "Standing Waves"

    def __init__(self) -> None:
        # Spatial frequency per pitch class: C=1 cycle, B≈1.89 cycles
        self._spatial_freq = np.array(
            [2.0 ** (n / 12.0) for n in range(NUM_CHROMA_BINS)]
        )
        # Fixed hue per pitch class
        self._pitch_hues = np.array(
            [n / NUM_CHROMA_BINS for n in range(NUM_CHROMA_BINS)]
        )
        # Precompute normalized grid positions
        self._x = np.arange(MAX_COLS, dtype=np.float64) / (MAX_COLS - 1)  # [0, 1]
        self._y = np.arange(NUM_ROWS, dtype=np.float64) / (NUM_ROWS - 1)  # [0, 1]
        # Amplitude envelope
        self._amplitude_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.2)
        self._phase: float = 0.0
        # Auto-gain with faster decay and a floor to prevent post-loud suppression
        self._peak_wave: float = 0.1
        self._beat_flash: float = 0.0

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        # Phase animation
        self._phase += 0.02 + frame.onset_strength * 0.3
        if frame.is_beat:
            self._phase += 0.5

        # Amplitude
        amplitude = self._amplitude_filter.update(frame.rms)
        amplitude = amplitude ** 2

        # Beat flash
        self._beat_flash *= 0.6
        if frame.is_beat:
            self._beat_flash = 0.3

        # Compute wave contributions — vectorized per pitch class
        total_wave = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        hue_sin = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        hue_cos = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)

        for n in range(NUM_CHROMA_BINS):
            e = frame.chroma[n]
            if e < 0.01:
                continue

            freq = self._spatial_freq[n]
            phase_n = self._phase + n * math.pi / 6.0

            # (NUM_ROWS, MAX_COLS) wave via broadcasting
            wave = np.sin(
                TWO_PI * freq * self._x[np.newaxis, :]
                + phase_n
                + 0.5 * math.pi * self._y[:, np.newaxis]
            )

            weighted = e * wave
            total_wave += weighted

            # Circular mean hue accumulation
            hue_angle = TWO_PI * self._pitch_hues[n]
            weight = e * np.abs(wave)
            hue_sin += weight * math.sin(hue_angle)
            hue_cos += weight * math.cos(hue_angle)

        # Auto-gain normalization (faster decay + floor)
        peak = np.max(np.abs(total_wave))
        self._peak_wave = max(peak, self._peak_wave * 0.98, 0.1)
        normalized = total_wave / (self._peak_wave + 1e-10)

        # Early exit on silence
        if peak < 1e-6:
            return grid_to_leds(np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64))

        # Compute per-pixel hue from circular mean
        hue_grid = np.arctan2(hue_sin, hue_cos) / TWO_PI % 1.0

        # Brightness from |normalized wave| × amplitude
        brightness = np.abs(normalized) * amplitude + self._beat_flash
        np.clip(brightness, 0.0, 1.0, out=brightness)

        # Build RGB grid
        rgb = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        for row in range(NUM_ROWS):
            for col in range(MAX_COLS):
                b = brightness[row, col]
                if b < 0.001:
                    continue
                h = hue_grid[row, col]
                r, g, bl = colorsys.hsv_to_rgb(h, 0.85, b)
                rgb[row, col] = (r, g, bl)

        return grid_to_leds(rgb)
