"""VelvetMothSwarm: moths orbiting a drifting center, leaving luminous trails."""

import colorsys
import math
import random
from dataclasses import dataclass, field

import numpy as np

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.grid import (
    MAX_COLS,
    NUM_ROWS,
    VALID_FLOAT,
    X_GRID,
    Y_GRID,
    blur3,
    gradient_mag,
    grid_to_leds,
)
from nuphy_rgb.visualizer import freq_to_hue

# Grid coordinate ranges: X in [0, MAX_COLS-1], Y in [0, NUM_ROWS-1]
_X_MAX = float(MAX_COLS - 1)  # 15.0
_Y_MAX = float(NUM_ROWS - 1)  # 5.0


@dataclass
class _Moth:
    x: float
    y: float
    angle: float       # orbit angle in radians
    speed: float       # orbit angular speed (rad/frame)
    phase: float       # wing-beat phase
    hue_offset: float  # individual hue offset [0, 1)


def _make_moth(rng: random.Random) -> _Moth:
    return _Moth(
        x=rng.uniform(2.0, _X_MAX - 2.0),
        y=rng.uniform(0.5, _Y_MAX - 0.5),
        angle=rng.uniform(0.0, 2.0 * math.pi),
        speed=rng.uniform(0.015, 0.055),
        phase=rng.uniform(0.0, 2.0 * math.pi),
        hue_offset=rng.uniform(0.0, 1.0),
    )


class VelvetMothSwarm:
    """Moths orbiting a drifting center, painting glowing trails on the key grid."""

    name = "Velvet Moth Swarm"

    def __init__(self, count: int = 6, seed: int | None = None):
        rng = random.Random(seed)
        self._moths: list[_Moth] = [_make_moth(rng) for _ in range(count)]
        # float32 RGB accumulator: (NUM_ROWS, MAX_COLS, 3)
        self._field = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float32)
        self._last_t: float | None = None
        self._t: float = 0.0  # internal time accumulator

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        # --- 1. Time delta ---
        if self._last_t is None:
            dt = 1.0 / 30.0
        else:
            dt = frame.timestamp - self._last_t
            dt = max(0.001, min(0.08, dt))
        self._last_t = frame.timestamp
        self._t += dt

        bass = frame.bass
        mids = frame.mids
        highs = frame.highs
        rms = frame.rms
        is_beat = frame.is_beat

        # --- 2. Derived scalars ---
        hue_root = freq_to_hue(frame.dominant_freq)
        decay = 0.84 + mids * 0.08
        beat_boost = 1.8 if is_beat else 1.0
        wing_span = 0.7 + bass * 1.6
        glow_sigma = 0.35 + 0.35 * rms

        # --- 3. Decay field ---
        self._field *= decay

        # --- 4. Drifting swarm center (in grid units) ---
        cx = 7.4 + math.sin(self._t * 0.19) * 1.1
        cy = 2.5 + math.cos(self._t * 0.23) * 0.5

        # Pre-build coordinate grids for vectorized distance (shape NUM_ROWS x MAX_COLS)
        # X_GRID and Y_GRID are already float32 with those shapes

        for moth in self._moths:
            # --- 5a. Update moth state ---
            moth.angle += moth.speed * dt * 30.0   # dt normalised to ~30 fps
            moth.phase += 3.6 * dt                 # dt-normalised wing phase

            # Orbit radius (spring toward center with wandering)
            orbit_r = 2.2 + math.sin(moth.phase * 0.31) * 0.9
            target_x = cx + math.cos(moth.angle) * orbit_r
            target_y = cy + math.sin(moth.angle) * orbit_r * 0.55  # flatter orbit

            # Spring toward orbit target
            spring = 0.12
            moth.x += (target_x - moth.x) * spring
            moth.y += (target_y - moth.y) * spring

            # Clamp to grid
            moth.x = max(0.0, min(_X_MAX, moth.x))
            moth.y = max(0.0, min(_Y_MAX, moth.y))

            # --- 5b. Wing positions ---
            wing_dx = math.cos(moth.angle + math.pi / 2.0) * wing_span
            wing_dy = math.sin(moth.angle + math.pi / 2.0) * wing_span * 0.4

            positions = [
                (moth.x, moth.y, 1.0),                                   # body
                (moth.x + wing_dx, moth.y + wing_dy, 0.55),              # wing A
                (moth.x - wing_dx, moth.y - wing_dy, 0.55),              # wing B
            ]

            # --- 5c. Hue / RGB for this moth ---
            hue = (hue_root + moth.hue_offset) % 1.0
            r_f, g_f, b_f = colorsys.hsv_to_rgb(hue, 0.85, 1.0)
            moth_rgb = np.array([r_f, g_f, b_f], dtype=np.float32)

            # --- 5d. Stamp Gaussian glows ---
            for px, py, scale in positions:
                dx2 = (X_GRID - px) ** 2
                dy2 = (Y_GRID - py) ** 2
                d2 = dx2 + dy2
                glow = np.exp(-d2 / (2.0 * glow_sigma ** 2)).astype(np.float32)
                strength = 0.24 * scale * beat_boost
                self._field += glow[..., None] * moth_rgb[None, None, :] * strength

            # --- 5e. Beat halo ring ---
            if is_beat:
                d2 = (X_GRID - moth.x) ** 2 + (Y_GRID - moth.y) ** 2
                ring_r = 1.1 + bass * 1.8
                ring_d = np.sqrt(d2)
                halo = np.exp(-((ring_d - ring_r) ** 2) / 0.24).astype(np.float32)
                self._field += halo[..., None] * moth_rgb[None, None, :] * 0.45

        # --- 6. Blur-preserve ---
        for ch in range(3):
            smoothed = blur3(self._field[:, :, ch]).astype(np.float32)
            preserve_factor = 0.92 + mids * 0.06
            self._field[:, :, ch] = np.maximum(
                self._field[:, :, ch], smoothed * preserve_factor
            )

        # Mask invalid cells after blur to prevent boundary energy leak
        self._field *= VALID_FLOAT[..., None]

        # --- 7. Shimmer ---
        luminance = self._field.mean(axis=2)
        shimmer = gradient_mag(luminance).astype(np.float32) * (0.35 + highs * 0.75)
        shimmer_color = np.array([0.3, 0.4, 0.6], dtype=np.float32)
        self._field += shimmer[..., None] * shimmer_color[None, None, :]

        # --- 8. Moonlight: wide soft Gaussian centered on grid ---
        moon_hue = (hue_root + 0.6) % 1.0
        moon_r, moon_g, moon_b = colorsys.hsv_to_rgb(moon_hue, 0.3, 1.0)
        moon_rgb = np.array([moon_r, moon_g, moon_b], dtype=np.float32)

        # Spatial value: Gaussian from grid center, broad sigma
        cx_moon, cy_moon = _X_MAX / 2.0, _Y_MAX / 2.0
        moon_sigma = (_X_MAX * 0.55) ** 2
        moon_val = np.exp(
            -((X_GRID - cx_moon) ** 2 + (Y_GRID - cy_moon) ** 2) / moon_sigma
        ).astype(np.float32)
        moon_strength = 0.06
        self._field += moon_val[..., None] * moon_rgb[None, None, :] * moon_strength

        # --- 9. Clip, mask, convert ---
        np.clip(self._field, 0.0, 1.0, out=self._field)
        self._field *= VALID_FLOAT[..., None]

        return grid_to_leds(self._field)
