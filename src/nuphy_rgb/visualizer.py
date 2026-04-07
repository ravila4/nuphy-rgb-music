"""Visualization effects that map AudioFrames to per-key RGB colors."""

import colorsys
import math
from typing import Protocol

from nuphy_rgb.audio import AudioFrame, ExpFilter

NUM_LEDS = 84


class Visualizer(Protocol):
    """Interface for visualization effects."""

    name: str

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]: ...


def freq_to_hue(
    freq: float, min_freq: float = 20.0, max_freq: float = 16000.0
) -> float:
    """Map a frequency to a hue value (0.0-1.0) on a log scale.

    Bass frequencies map to low hue (red/warm), highs to high hue (blue/cool).
    Clamps to [0, 1] for out-of-range frequencies.
    """
    if freq <= min_freq:
        return 0.0
    if freq >= max_freq:
        return 1.0
    return (math.log(freq) - math.log(min_freq)) / (
        math.log(max_freq) - math.log(min_freq)
    )


class ColorWash:
    """All LEDs the same color: hue follows dominant frequency, brightness tracks energy."""

    name = "Color Wash"

    def __init__(self, num_leds: int = NUM_LEDS):
        self._num_leds = num_leds
        self._brightness_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.3)
        self._hue_filter = ExpFilter(alpha_rise=0.6, alpha_decay=0.15)
        self._beat_glow: float = 0.0

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        # Hue from dominant frequency, mapped over typical music range
        # (80-4000Hz covers most dominant frequencies in practice)
        raw_hue = freq_to_hue(frame.dominant_freq, min_freq=80.0, max_freq=4000.0)
        hue = self._hue_filter.update(raw_hue)

        # Brightness: square the RMS to widen the dynamic range
        # (0.9 -> 0.81, 0.5 -> 0.25, 0.3 -> 0.09)
        brightness = self._brightness_filter.update(frame.rms ** 2)

        # Beat boost: spike then decay
        if frame.is_beat:
            self._beat_glow = 0.5
        self._beat_glow *= 0.65  # decay each frame

        brightness = min(1.0, brightness + self._beat_glow)

        # Saturation: reduce when energy is low (fades toward white in quiet parts)
        saturation = min(1.0, frame.rms * 1.5)

        # HSV -> RGB
        r_f, g_f, b_f = colorsys.hsv_to_rgb(hue, saturation, brightness)
        r = int(r_f * 255)
        g = int(g_f * 255)
        b = int(b_f * 255)

        return [(r, g, b)] * self._num_leds
