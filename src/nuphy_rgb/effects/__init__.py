"""Visualizer effects registry.

Import all effect classes here. main.py uses ALL_EFFECTS to build the visualizer list.
"""

from nuphy_rgb.effects.color_wash import ColorWash
from nuphy_rgb.effects.event_horizon import EventHorizon
from nuphy_rgb.effects.interference_pond import InterferencePond
from nuphy_rgb.effects.mycelium import Mycelium
from nuphy_rgb.effects.strange_attractor import StrangeAttractor

ALL_EFFECTS = [
    ColorWash,
    InterferencePond,
    Mycelium,
    EventHorizon,
    StrangeAttractor,
]
