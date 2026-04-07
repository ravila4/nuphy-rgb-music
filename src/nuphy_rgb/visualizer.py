"""Visualization protocol and shared utilities for effects."""

import math
from typing import Protocol

from nuphy_rgb.audio import AudioFrame


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
