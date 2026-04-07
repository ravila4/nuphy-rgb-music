"""Visualizer effects registry.

Import all effect classes here. main.py uses ALL_EFFECTS to build the visualizer list.
"""

from nuphy_rgb.effects.cathedral_of_spores import CathedralOfSpores
from nuphy_rgb.effects.color_wash import ColorWash
from nuphy_rgb.effects.event_horizon import EventHorizon
from nuphy_rgb.effects.interference_pond import InterferencePond
from nuphy_rgb.effects.mycelium import Mycelium
from nuphy_rgb.effects.strange_attractor import StrangeAttractor
from nuphy_rgb.effects.velvet_moth_swarm import VelvetMothSwarm

ALL_EFFECTS = [
    ColorWash,
    InterferencePond,
    Mycelium,
    VelvetMothSwarm,
    CathedralOfSpores,
    EventHorizon,
    StrangeAttractor,
]
