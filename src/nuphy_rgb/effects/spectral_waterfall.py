"""SpectralWaterfall: scrolling spectrogram on the keyboard grid.

Top row = current frame's spectrum. Each frame, rows scroll downward.
Mirrored layout: bass in center, treble at both edges.
Color = frequency-mapped hue, brightness = bin magnitude.
"""

import colorsys
import math

import numpy as np

from nuphy_rgb.audio import AudioFrame, ExpFilter, NUM_SPECTRUM_BINS
from nuphy_rgb.effects.grid import MAX_COLS, NUM_ROWS, grid_to_leds

# Centroid range for offset mapping (Hz, log scale)
_CENTROID_MIN = 20.0
_CENTROID_MAX = 16000.0


class SpectralWaterfall:
    """Scrolling spectrogram — frequency on x-axis, time on y-axis.

    Spectral centroid drives horizontal drift: bass-heavy content
    shifts the pattern one way, treble-heavy the other.
    """

    name = "Spectral Waterfall"

    def __init__(self) -> None:
        # Grid stores per-bin normalized values per cell [0, 1]
        self._grid = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        # Per-row amplitude: the raw_rms envelope when that row was current
        self._row_amplitude = np.zeros(NUM_ROWS, dtype=np.float64)
        # Mirrored layout: center = bin 0 (bass), edges = bin 15 (treble)
        self._col_to_bin = self._build_col_mapping()
        # Hue per column follows the bin it maps to (bass=red center, treble=violet edges)
        self._col_hues = np.array([
            self._col_to_bin[c] / NUM_SPECTRUM_BINS for c in range(MAX_COLS)
        ])
        self._beat_flash: float = 0.0
        # Horizontal drift driven by spectral centroid
        self._offset_filter = ExpFilter(alpha_rise=0.3, alpha_decay=0.1)
        # Per-bin running peak for independent AGC per frequency band
        self._bin_peaks = np.full(NUM_SPECTRUM_BINS, 1e-10, dtype=np.float64)
        # Global amplitude envelope — smoothed raw_rms with squared curve
        self._amplitude_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.2)

    @staticmethod
    def _build_col_mapping() -> list[int]:
        """Map columns to spectrum bins — mirrored from center.

        Center columns = low bins (bass), edge columns = high bins (treble).
        col:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
        bin: 15 13 11  9  7  5  3  1  0  2  4  6  8 10 12 14
        """
        half = MAX_COLS // 2  # 8
        mapping = []
        for col in range(MAX_COLS):
            # Distance from center (0-7), mapped to bin index
            dist = abs(col - half + 0.5)  # 7.5, 6.5, ..., 0.5, 0.5, ..., 7.5
            bin_idx = int(dist * NUM_SPECTRUM_BINS / half)
            bin_idx = min(bin_idx, NUM_SPECTRUM_BINS - 1)
            mapping.append(bin_idx)
        return mapping

    @staticmethod
    def _centroid_to_offset(centroid: float) -> float:
        """Map spectral centroid to a column offset in [-MAX_COLS/2, MAX_COLS/2].

        Log-scaled: low centroid drifts left, high centroid drifts right.
        """
        if centroid <= _CENTROID_MIN:
            return -MAX_COLS / 2.0
        if centroid >= _CENTROID_MAX:
            return MAX_COLS / 2.0
        t = (math.log(centroid) - math.log(_CENTROID_MIN)) / (
            math.log(_CENTROID_MAX) - math.log(_CENTROID_MIN)
        )
        return (t - 0.5) * MAX_COLS

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        # Scroll rows down: row N <- row N-1
        self._grid[1:] = self._grid[:-1]
        self._row_amplitude[1:] = self._row_amplitude[:-1]

        # Global amplitude: raw_rms with squared curve
        amplitude = self._amplitude_filter.update(min(frame.raw_rms * 3.0, 1.0))
        self._row_amplitude[0] = amplitude ** 2

        # Compute smoothed horizontal offset from spectral centroid
        raw_offset = self._centroid_to_offset(frame.spectral_centroid)
        offset = self._offset_filter.update(raw_offset)
        int_offset = int(round(offset))

        # Per-bin AGC: update running peaks, then normalize each bin
        spectrum = np.array(frame.spectrum, dtype=np.float64)
        self._bin_peaks = np.maximum(spectrum, self._bin_peaks * 0.995)
        normalized = spectrum / (self._bin_peaks + 1e-10)

        # sqrt compression: widen dynamic range visibility
        compressed = np.sqrt(normalized)

        # Fill top row from spectrum bins with horizontal shift
        self._grid[0] = 0.0
        for col in range(MAX_COLS):
            src_col = (col - int_offset) % MAX_COLS
            bin_idx = self._col_to_bin[src_col]
            self._grid[0, col] = compressed[bin_idx]

        # Beat flash: brief brightness boost across all rows
        if frame.is_beat:
            self._beat_flash = 0.25
        self._beat_flash *= 0.6

        # Build RGB grid
        rgb = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        for row in range(NUM_ROWS):
            for col in range(MAX_COLS):
                val = self._grid[row, col]
                if val < 0.001:
                    continue
                hue = self._col_hues[col]
                brightness = min(1.0, val * self._row_amplitude[row] + self._beat_flash)
                saturation = 0.8 + 0.2 * (1.0 - val)  # brighter bins slightly less saturated
                r, g, b = colorsys.hsv_to_rgb(hue, saturation, brightness)
                rgb[row, col] = (r, g, b)

        return grid_to_leds(rgb)
