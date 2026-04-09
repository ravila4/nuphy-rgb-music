"""Sidelight effects registry."""

from nuphy_rgb.sidelights.chroma_bars import ChromaBars
from nuphy_rgb.sidelights.chord_glow import ChordGlow
from nuphy_rgb.sidelights.vu_meter import VUMeter

ALL_SIDELIGHTS = [VUMeter, ChromaBars, ChordGlow]
