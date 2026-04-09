"""Chroma Bars: split chromatic scale across left and right sidebars.

Left strip (bottom→top):  C  C# D  D# E  F
Right strip (bottom→top): F# G  G# A  A# B

Each LED's brightness tracks its pitch class energy. Per-frame contrast
normalization ensures only dominant notes light up. raw_rms gates
overall brightness so quiet passages stay dim.
"""

import colorsys

from nuphy_rgb.audio import AudioFrame, ExpFilter, NUM_CHROMA_BINS
from nuphy_rgb.visualizer_params import VisualizerParam
from nuphy_rgb.sidelights.visualizer import (
    LEFT_BOTTOM_UP,
    LEDS_PER_SIDE,
    RIGHT_BOTTOM_UP,
    SIDE_LED_COUNT,
)

_CHROMA_FLOOR = 0.3  # suppress bins below this fraction of peak


class ChromaBars:
    """Chromatic scale split across sidebars — each LED = one pitch class."""

    name = "Chroma Bars"

    def __init__(self) -> None:
        self._amplitude_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.2)
        self.params: dict[str, VisualizerParam] = {
            "brightness": VisualizerParam(
                value=0.1, default=0.1, min=0.0, max=1.0,
                description="Overall brightness multiplier",
            ),
        }

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        # Amplitude from raw_rms (real dynamic range, not AGC-flattened)
        amplitude = self._amplitude_filter.update(min(frame.raw_rms * 3.0, 1.0))
        amplitude = amplitude ** 2

        # Per-frame contrast: normalize to peak, threshold, stretch
        peak = max(frame.chroma)
        if peak < 1e-6:
            return [(0, 0, 0)] * SIDE_LED_COUNT

        bright = self.params["brightness"].get()
        colors: list[tuple[int, int, int]] = [(0, 0, 0)] * SIDE_LED_COUNT

        for i in range(NUM_CHROMA_BINS):
            relative = frame.chroma[i] / peak
            visible = max(0.0, relative - _CHROMA_FLOOR) / (1.0 - _CHROMA_FLOOR)
            # Cube transform: crushes mid-range, only dominant bins pop
            brightness = min(1.0, visible ** 3 * amplitude) * bright
            if brightness < 0.001:
                continue

            hue = i / NUM_CHROMA_BINS
            r, g, b = colorsys.hsv_to_rgb(hue, 0.85, brightness)
            color = (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))

            if i < LEDS_PER_SIDE:
                colors[LEFT_BOTTOM_UP[i]] = color
            else:
                colors[RIGHT_BOTTOM_UP[i - LEDS_PER_SIDE]] = color

        return colors
