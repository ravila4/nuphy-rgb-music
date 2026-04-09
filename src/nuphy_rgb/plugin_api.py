"""Public API for plugin authors.

Import from here, not internal modules.  When writing a keyboard or sidelight
effect as a plugin, everything you need is re-exported from this module::

    from nuphy_rgb.plugin_api import AudioFrame, NUM_LEDS, grid_to_leds
"""

from nuphy_rgb.audio import AudioFrame, ExpFilter, NUM_CHROMA_BINS
from nuphy_rgb.effects.grid import (
    LED_ROW_COL,
    LED_X,
    LED_XY,
    LED_Y,
    MAX_COLS,
    NEIGHBORS,
    NUM_LEDS,
    NUM_ROWS,
    RC_TO_LED,
    ROWS,
    VALID_MASK,
    X_GRID,
    Y_GRID,
    blur3,
    gradient_mag,
    grid_to_leds,
)
from nuphy_rgb.hid_utils import SIDE_LED_COUNT
from nuphy_rgb.sidelights.visualizer import (
    LEFT_BOTTOM_UP,
    LEDS_PER_SIDE,
    RIGHT_BOTTOM_UP,
    SideLightVisualizer,
)
from nuphy_rgb.visualizer import Visualizer, freq_to_hue

__all__ = [
    # Audio
    "AudioFrame",
    "ExpFilter",
    "NUM_CHROMA_BINS",
    # Keyboard grid
    "NUM_LEDS",
    "NUM_ROWS",
    "MAX_COLS",
    "ROWS",
    "LED_XY",
    "LED_ROW_COL",
    "LED_X",
    "LED_Y",
    "RC_TO_LED",
    "NEIGHBORS",
    "X_GRID",
    "Y_GRID",
    "VALID_MASK",
    "blur3",
    "gradient_mag",
    "grid_to_leds",
    # Sidelight layout
    "SIDE_LED_COUNT",
    "LEDS_PER_SIDE",
    "LEFT_BOTTOM_UP",
    "RIGHT_BOTTOM_UP",
    # Protocols
    "Visualizer",
    "SideLightVisualizer",
    # Utilities
    "freq_to_hue",
]
