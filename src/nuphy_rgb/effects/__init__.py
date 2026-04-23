"""Visualizer effects registry.

Import all effect classes here. main.py uses ALL_EFFECTS to build the visualizer list.
"""

from nuphy_rgb.effects.aurora import Aurora
from nuphy_rgb.effects.blackout import Blackout
from nuphy_rgb.effects.chromatic_keys import ChromaticKeys
from nuphy_rgb.effects.conways_jukebox import ConwaysJukebox
from nuphy_rgb.effects.double_pendulum import DoublePendulum
from nuphy_rgb.effects.event_horizon import EventHorizon
from nuphy_rgb.effects.interference_pond import InterferencePond
from nuphy_rgb.effects.karman_street import KarmanStreet
from nuphy_rgb.effects.lightning import Lightning
from nuphy_rgb.effects.mycelium import Mycelium
from nuphy_rgb.effects.navier_stokes import NavierStokes
from nuphy_rgb.effects.polarity import Polarity
from nuphy_rgb.effects.raycaster import Raycaster
from nuphy_rgb.effects.spectral_waterfall import SpectralWaterfall
from nuphy_rgb.effects.strange_attractor import StrangeAttractor
from nuphy_rgb.effects.three_body import ThreeBody

ALL_EFFECTS = [
    InterferencePond,
    Mycelium,
    EventHorizon,
    StrangeAttractor,
    SpectralWaterfall,
    Aurora,
    ChromaticKeys,
    NavierStokes,
    Polarity,
    KarmanStreet,
    DoublePendulum,
    ThreeBody,
    ConwaysJukebox,
    Lightning,
    Raycaster,
    Blackout,
]
