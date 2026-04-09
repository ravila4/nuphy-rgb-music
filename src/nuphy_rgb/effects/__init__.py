"""Visualizer effects registry.

Import all effect classes here. main.py uses ALL_EFFECTS to build the visualizer list.
"""

from nuphy_rgb.effects.aurora import Aurora
from nuphy_rgb.effects.blackout import Blackout
from nuphy_rgb.effects.chromatic_keys import ChromaticKeys
from nuphy_rgb.effects.color_wash import ColorWash
from nuphy_rgb.effects.event_horizon import EventHorizon
from nuphy_rgb.effects.interference_pond import InterferencePond
from nuphy_rgb.effects.mycelium import Mycelium
from nuphy_rgb.effects.spectral_waterfall import SpectralWaterfall
from nuphy_rgb.effects.standing_waves import StandingWaves
from nuphy_rgb.effects.strange_attractor import StrangeAttractor

ALL_EFFECTS = [
    InterferencePond,
    ColorWash,
    Mycelium,
    EventHorizon,
    StrangeAttractor,
    SpectralWaterfall,
    Aurora,
    ChromaticKeys,
    StandingWaves,
    Blackout,
]
