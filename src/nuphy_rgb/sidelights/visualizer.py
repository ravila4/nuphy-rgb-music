"""Sidelight visualization protocol and layout constants."""

from typing import Protocol

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.hid_utils import SIDE_LED_COUNT

LEDS_PER_SIDE = SIDE_LED_COUNT // 2

# Physical LED indices ordered bottom-to-top for symmetric bar effects.
LEFT_BOTTOM_UP = (0, 1, 2, 3, 4, 5)
RIGHT_BOTTOM_UP = (11, 10, 9, 8, 7, 6)


class SideLightVisualizer(Protocol):
    """Interface for sidelight visualization effects."""

    name: str

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]: ...
