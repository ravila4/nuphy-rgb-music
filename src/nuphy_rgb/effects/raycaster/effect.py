"""Raycaster: flies through a toroidal pillar maze via column-per-ray casting.

Each of the 16 keyboard columns casts one ray into a small 2D map. Per-column
wall distance drives two independent depth cues:

  * slice height (geometry)  -- NUM_ROWS / distance, clamped
  * brightness (distance fog) -- exp(-d * fog)

Wall material color alternates between EW and NS grid crossings so corners
stay legible despite the tiny vertical resolution (Wolfenstein trick).

Music hooks:
  bass       -> forward velocity
  high_beat  -> rotation jolt
  dominant   -> hue shift on wall material
  rms        -> global brightness floor so the maze is visible in silence
"""

import colorsys
import math

import numpy as np

from nuphy_rgb.plugin_api import (
    AudioFrame,
    ExpFilter,
    MAX_COLS,
    NUM_ROWS,
    freq_to_hue,
    grid_to_leds,
)

# 8x8 toroidal pillar map. 1 = wall, 0 = empty. Wrapping means no dead ends.
_MAP = np.array(
    [
        [0, 0, 0, 0, 0, 1, 0, 0],
        [0, 1, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 1, 0],
        [0, 0, 0, 1, 0, 0, 0, 0],
        [0, 1, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 1, 0, 0],
        [0, 0, 1, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 1, 0],
    ],
    dtype=np.int8,
)
_MAP_H, _MAP_W = _MAP.shape

_FOV = math.radians(66.0)
_MAX_DIST = 10.0
_STEP = 0.04
_FOG = 0.45


def _cast_ray(px: float, py: float, angle: float) -> tuple[float, int]:
    """March a ray until it hits a wall. Returns (distance, side).

    side=0: EW wall (x-axis crossing). side=1: NS wall (y-axis crossing).
    """
    dx = math.cos(angle) * _STEP
    dy = math.sin(angle) * _STEP
    x, y = px, py
    prev_ix = int(x) % _MAP_W
    prev_iy = int(y) % _MAP_H
    d = 0.0
    while d < _MAX_DIST:
        x += dx
        y += dy
        d += _STEP
        ix = int(x) % _MAP_W
        iy = int(y) % _MAP_H
        if _MAP[iy, ix] > 0:
            if ix != prev_ix and iy == prev_iy:
                return d, 0
            if iy != prev_iy and ix == prev_ix:
                return d, 1
            fx = abs((x - dx) - math.floor(x - dx) - 0.5)
            fy = abs((y - dy) - math.floor(y - dy) - 0.5)
            return d, 0 if fx > fy else 1
        prev_ix = ix
        prev_iy = iy
    return _MAX_DIST, 0


class Raycaster:
    """Column-per-ray 3D maze raycaster driven by audio."""

    name = "Raycaster"

    def __init__(self) -> None:
        self._px: float = 4.5
        self._py: float = 4.5
        self._angle: float = 0.0

        self._vel_filter = ExpFilter(alpha_rise=0.4, alpha_decay=0.1)
        self._brightness_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)

        self._turn_jolt: float = 0.0

        self._col_offsets = np.array(
            [(c / (MAX_COLS - 1) - 0.5) * _FOV for c in range(MAX_COLS)],
            dtype=np.float64,
        )

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        velocity = self._vel_filter.update(0.015 + frame.bass * 0.18)
        self._step_forward(velocity)

        self._angle += 0.006
        if frame.high_beat:
            self._turn_jolt = 0.12 * (1.0 if math.sin(self._angle * 7) >= 0 else -1.0)
        self._angle += self._turn_jolt
        self._turn_jolt *= 0.7

        distances = np.empty(MAX_COLS, dtype=np.float64)
        sides = np.empty(MAX_COLS, dtype=np.int8)
        for c in range(MAX_COLS):
            ra = self._angle + self._col_offsets[c]
            d, side = _cast_ray(self._px, self._py, ra)
            distances[c] = d * math.cos(self._col_offsets[c])
            sides[c] = side

        grid = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)

        freq_shift = freq_to_hue(
            max(frame.dominant_freq, 80.0), min_freq=80.0, max_freq=4000.0
        )

        center = (NUM_ROWS - 1) / 2.0

        for c in range(MAX_COLS):
            d = distances[c]
            slice_h = min(NUM_ROWS / max(d, 0.25), float(NUM_ROWS))
            half = slice_h / 2.0
            top = center - half
            bot = center + half

            fog = math.exp(-d * _FOG)

            if sides[c] == 0:
                base_hue = (0.05 + freq_shift * 0.15) % 1.0
                sat = 0.95
            else:
                base_hue = (0.55 + freq_shift * 0.15) % 1.0
                sat = 0.85

            for r in range(NUM_ROWS):
                row_top = r - 0.5
                row_bot = r + 0.5
                cov = max(0.0, min(bot, row_bot) - max(top, row_top))
                if cov <= 0.0:
                    continue
                bright = fog * cov
                rr, gg, bb = colorsys.hsv_to_rgb(base_hue, sat, bright)
                grid[r, c, 0] = rr
                grid[r, c, 1] = gg
                grid[r, c, 2] = bb

        global_b = self._brightness_filter.update(frame.rms)
        global_b = max(global_b, 0.25)
        grid *= global_b

        return grid_to_leds(grid)

    def _step_forward(self, velocity: float) -> None:
        dx = math.cos(self._angle) * velocity
        dy = math.sin(self._angle) * velocity

        bounced = False
        nx = (self._px + dx) % _MAP_W
        if _MAP[int(self._py) % _MAP_H, int(nx) % _MAP_W] == 0:
            self._px = nx
        else:
            bounced = True
            # Push away from the wall so we don't keep sampling it next frame.
            self._px = (self._px - dx * 2.0) % _MAP_W

        ny = (self._py + dy) % _MAP_H
        if _MAP[int(ny) % _MAP_H, int(self._px) % _MAP_W] == 0:
            self._py = ny
        else:
            bounced = True
            self._py = (self._py - dy * 2.0) % _MAP_H

        if bounced:
            # Big rotation so we actually change direction instead of grinding.
            self._angle += 0.9
