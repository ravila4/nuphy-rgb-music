"""ColorWash: all LEDs the same color, hue follows frequency, brightness tracks energy."""

import colorsys

from nuphy_rgb.audio import AudioFrame, ExpFilter
from nuphy_rgb.effects.grid import NUM_LEDS
from nuphy_rgb.visualizer import freq_to_hue


class ColorWash:
    """All LEDs the same color: hue follows dominant frequency, brightness tracks energy."""

    name = "Color Wash"

    def __init__(self, num_leds: int = NUM_LEDS):
        self._num_leds = num_leds
        self._brightness_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.3)
        self._hue_filter = ExpFilter(alpha_rise=0.6, alpha_decay=0.15)
        self._beat_glow: float = 0.0

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        raw_hue = freq_to_hue(frame.dominant_freq, min_freq=80.0, max_freq=4000.0)
        hue = self._hue_filter.update(raw_hue)

        brightness = self._brightness_filter.update(frame.rms ** 2)

        if frame.is_beat:
            self._beat_glow = 0.5
        self._beat_glow *= 0.65

        brightness = min(1.0, brightness + self._beat_glow)
        saturation = min(1.0, frame.rms * 1.5)

        r_f, g_f, b_f = colorsys.hsv_to_rgb(hue, saturation, brightness)
        r = int(r_f * 255)
        g = int(g_f * 255)
        b = int(b_f * 255)

        return [(r, g, b)] * self._num_leds
