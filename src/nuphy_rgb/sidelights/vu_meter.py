"""VU Meter: symmetric bar-graph sidelight driven by bass energy."""

import math

from nuphy_rgb.audio import AudioFrame, ExpFilter
from nuphy_rgb.visualizer_params import VisualizerParam
from nuphy_rgb.sidelights.visualizer import (
    LEFT_BOTTOM_UP,
    LEDS_PER_SIDE,
    RIGHT_BOTTOM_UP,
    SIDE_LED_COUNT,
)

# Classic VU colors by position (bottom to top): green → yellow → red
_VU_COLORS = [
    (0, 255, 0),    # 0 - green
    (0, 255, 0),    # 1 - green
    (255, 255, 0),  # 2 - yellow
    (255, 255, 0),  # 3 - yellow
    (255, 0, 0),    # 4 - red
    (255, 0, 0),    # 5 - red
]


class VUMeter:
    """Symmetric bar fill from bass energy, green→yellow→red."""

    name = "VU Meter"

    def __init__(self) -> None:
        self._filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.2)
        self.params: dict[str, VisualizerParam] = {
            "brightness": VisualizerParam(
                value=1.0, default=1.0, min=0.0, max=1.0,
                description="Overall brightness multiplier",
            ),
        }

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        level = min(self._filter.update(frame.bass), 1.0) * LEDS_PER_SIDE

        bar: list[tuple[int, int, int]] = []
        for i in range(LEDS_PER_SIDE):
            if i < math.floor(level):
                bar.append(_VU_COLORS[i])
            elif i == math.floor(level):
                frac = level - math.floor(level)
                r, g, b = _VU_COLORS[i]
                bar.append((int(r * frac), int(g * frac), int(b * frac)))
            else:
                bar.append((0, 0, 0))

        bright = self.params["brightness"].get()
        colors: list[tuple[int, int, int]] = [(0, 0, 0)] * SIDE_LED_COUNT
        for pos, (r, g, b) in enumerate(bar):
            scaled = (int(r * bright), int(g * bright), int(b * bright))
            colors[LEFT_BOTTOM_UP[pos]] = scaled
            colors[RIGHT_BOTTOM_UP[pos]] = scaled

        return colors
