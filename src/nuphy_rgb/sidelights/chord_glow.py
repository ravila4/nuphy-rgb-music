"""Chord Glow: both sidebars glow the color of the current chord.

Hue is the circular mean of active pitch classes, weighted by chroma
energy. A single note = pure pitch color. A chord = blended hue.
Both strips show the same solid color. raw_rms gates brightness so
quiet passages stay dim.

Hue is smoothed in the phasor domain (sin/cos) to avoid wraparound
artifacts at the red/violet boundary.
"""

import colorsys
import math

from nuphy_rgb.audio import AudioFrame, ExpFilter, NUM_CHROMA_BINS
from nuphy_rgb.hid_utils import SIDE_LED_COUNT
from nuphy_rgb.visualizer_params import VisualizerParam

TWO_PI = 2.0 * math.pi
_HUE_ALPHA_RISE = 0.4
_HUE_ALPHA_DECAY = 0.08


class ChordGlow:
    """Sidebars glow the harmonic color of the current chord."""

    name = "Chord Glow"

    def __init__(self) -> None:
        self._amplitude_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.2)
        # Phasor-domain hue smoothing (avoids circular wraparound artifacts)
        self._smooth_sin: float = 0.0
        self._smooth_cos: float = 0.0
        self._beat_flash: float = 0.0
        self.params: dict[str, VisualizerParam] = {
            "brightness": VisualizerParam(
                value=1.0, default=1.0, min=0.0, max=1.0,
                description="Overall brightness multiplier",
            ),
        }

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        # Circular mean hue from chroma weights
        sin_sum = 0.0
        cos_sum = 0.0
        for i in range(NUM_CHROMA_BINS):
            angle = TWO_PI * i / NUM_CHROMA_BINS
            sin_sum += frame.chroma[i] * math.sin(angle)
            cos_sum += frame.chroma[i] * math.cos(angle)

        weight = math.hypot(sin_sum, cos_sum)
        if weight < 1e-10:
            raw_hue = 0.0
        else:
            raw_hue = math.atan2(sin_sum, cos_sum)

        # Smooth in phasor domain to handle circular wraparound
        prev_weight = math.hypot(self._smooth_sin, self._smooth_cos)
        alpha = _HUE_ALPHA_RISE if weight > prev_weight else _HUE_ALPHA_DECAY
        self._smooth_sin = alpha * math.sin(raw_hue) + (1 - alpha) * self._smooth_sin
        self._smooth_cos = alpha * math.cos(raw_hue) + (1 - alpha) * self._smooth_cos
        hue = math.atan2(self._smooth_sin, self._smooth_cos) / TWO_PI % 1.0

        # Amplitude from raw_rms (real dynamic range)
        amplitude = self._amplitude_filter.update(min(frame.raw_rms * 3.0, 1.0))
        amplitude = amplitude ** 2

        # Beat flash
        self._beat_flash *= 0.6
        if frame.is_beat:
            self._beat_flash = 0.3

        brightness = min(1.0, amplitude + self._beat_flash)
        brightness *= self.params["brightness"].get()

        if brightness < 0.001:
            return [(0, 0, 0)] * SIDE_LED_COUNT

        saturation = 0.85
        r, g, b = colorsys.hsv_to_rgb(hue, saturation, brightness)
        color = (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))

        return [color] * SIDE_LED_COUNT
