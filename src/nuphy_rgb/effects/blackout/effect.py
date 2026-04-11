"""Blackout: all LEDs off. Useful for isolating sidelight effects."""

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.grid import NUM_LEDS

_BLACK: list[tuple[int, int, int]] = [(0, 0, 0)] * NUM_LEDS


class Blackout:
    """Sends all-black frames to suppress firmware lighting."""

    name = "Blackout"

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        return list(_BLACK)
