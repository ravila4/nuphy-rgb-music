"""SpectralWaterfall: scrolling spectrogram on the keyboard grid.

Top row = current frame's spectrum. Each frame, rows scroll downward.
Left = bass, right = treble. Per-bin AGC keeps the full keyboard lit.
Color = frequency-mapped hue, brightness = bin magnitude × amplitude.
"""

import colorsys

import numpy as np

from nuphy_rgb.audio import AudioFrame, ExpFilter, NUM_SPECTRUM_BINS
from nuphy_rgb.effects.grid import MAX_COLS, NUM_ROWS, grid_to_leds


class SpectralWaterfall:
    """Scrolling spectrogram — frequency on x-axis, time on y-axis."""

    name = "Spectral Waterfall"

    def __init__(self) -> None:
        # Grid stores per-bin normalized values per cell [0, 1]
        self._grid = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        # Per-row amplitude: the raw_rms envelope when that row was current
        self._row_amplitude = np.zeros(NUM_ROWS, dtype=np.float64)
        # Simple left-to-right: col 0 = bin 0 (bass), col 15 = bin 15 (treble)
        self._col_to_bin = self._build_col_mapping()
        # Hue per column: bass=red (0.0) to treble=violet (1.0)
        self._col_hues = np.array([
            self._col_to_bin[c] / NUM_SPECTRUM_BINS for c in range(MAX_COLS)
        ])
        self._beat_flash: float = 0.0
        # Per-bin running peak for independent AGC per frequency band
        self._bin_peaks = np.full(NUM_SPECTRUM_BINS, 1e-10, dtype=np.float64)
        # Global amplitude envelope — smoothed raw_rms with squared curve
        self._amplitude_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.2)

    @staticmethod
    def _build_col_mapping() -> list[int]:
        """Map each column to the nearest spectrum bin, left to right.

        col:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
        bin:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
        """
        mapping = []
        for col in range(MAX_COLS):
            bin_idx = int(col * NUM_SPECTRUM_BINS / MAX_COLS)
            bin_idx = min(bin_idx, NUM_SPECTRUM_BINS - 1)
            mapping.append(bin_idx)
        return mapping

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        # Scroll rows down: row N <- row N-1
        self._grid[1:] = self._grid[:-1]
        self._row_amplitude[1:] = self._row_amplitude[:-1]

        # Global amplitude: raw_rms with squared curve
        amplitude = self._amplitude_filter.update(min(frame.raw_rms * 3.0, 1.0))
        self._row_amplitude[0] = amplitude ** 2

        # Per-bin AGC: update running peaks, then normalize each bin
        spectrum = np.array(frame.spectrum, dtype=np.float64)
        self._bin_peaks = np.maximum(spectrum, self._bin_peaks * 0.995)
        normalized = spectrum / (self._bin_peaks + 1e-10)

        # sqrt compression: widen dynamic range visibility
        compressed = np.sqrt(normalized)

        # Fill top row from spectrum bins
        for col in range(MAX_COLS):
            bin_idx = self._col_to_bin[col]
            self._grid[0, col] = compressed[bin_idx]

        # Beat flash: brief brightness boost across all rows
        self._beat_flash *= 0.6
        if frame.is_beat:
            self._beat_flash = 0.25

        # Build RGB grid
        rgb = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        for row in range(NUM_ROWS):
            for col in range(MAX_COLS):
                val = self._grid[row, col]
                if val < 0.001:
                    continue
                hue = self._col_hues[col]
                brightness = min(1.0, val * self._row_amplitude[row] + self._beat_flash)
                saturation = 0.8 + 0.2 * (1.0 - val)
                r, g, b = colorsys.hsv_to_rgb(hue, saturation, brightness)
                rgb[row, col] = (r, g, b)

        return grid_to_leds(rgb)
