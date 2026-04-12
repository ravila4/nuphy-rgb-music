"""Chromatic Keys: bar-graph EQ for pitch classes.

Each pitch class (C through B) owns one or two columns. Bars grow
from the bottom up proportional to chroma energy. Color is fixed
per pitch class — C=red cycling through the hue wheel to B=violet.
"""

import colorsys

import numpy as np

from nuphy_rgb.audio import AudioFrame, ExpFilter, NUM_CHROMA_BINS
from nuphy_rgb.effects.grid import MAX_COLS, NUM_ROWS, grid_to_leds


class ChromaticKeys:
    """Bar-graph EQ for musical pitch classes."""

    name = "Chromatic Keys"
    description = (
        "Twelve pitch classes from C to B mapped to columns. Bar height "
        "tracks energy per note; hue is fixed by pitch class."
    )

    def __init__(self) -> None:
        # Column → pitch class mapping: 12 notes spread across 16 columns
        self._col_to_pitch = [
            int(c * NUM_CHROMA_BINS / MAX_COLS) for c in range(MAX_COLS)
        ]
        # Fixed hue per pitch class (C=0/red → B≈0.917/violet)
        self._pitch_hues = [n / NUM_CHROMA_BINS for n in range(NUM_CHROMA_BINS)]
        # Amplitude envelope
        self._amplitude_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.2)
        self._beat_flash: float = 0.0

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        # Amplitude: AGC-normalized rms with squared curve
        amplitude = self._amplitude_filter.update(frame.rms)
        amplitude = amplitude ** 2

        # Beat flash
        self._beat_flash *= 0.6
        if frame.is_beat:
            self._beat_flash = 0.3

        rgb = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)

        for col in range(MAX_COLS):
            pitch = self._col_to_pitch[col]
            energy = frame.chroma[pitch]
            hue = self._pitch_hues[pitch]

            # Bar height: 0 to NUM_ROWS
            height = energy * NUM_ROWS

            for row in range(NUM_ROWS):
                # Fill fraction: bottom-up (row 5 = base, row 0 = peak)
                fill = max(0.0, min(1.0, height - (NUM_ROWS - 1 - row)))
                if fill < 0.001:
                    continue

                brightness = min(1.0, fill * amplitude + self._beat_flash)
                saturation = 0.85

                r, g, b = colorsys.hsv_to_rgb(hue, saturation, brightness)
                rgb[row, col] = (r, g, b)

        return grid_to_leds(rgb)
