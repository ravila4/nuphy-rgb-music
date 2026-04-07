"""Cathedral of Spores -- Gray-Scott reaction-diffusion music visualizer.

A living mycelial network grows and pulses across the keyboard in response to
audio. Beat onsets seed new colonies; frequency content tints the spreading
filaments.
"""

import colorsys
import time

import numpy as np

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.grid import (
    LED_ROW_COL,
    MAX_COLS,
    NUM_LEDS,
    NUM_ROWS,
    VALID_FLOAT,
    VALID_MASK,
    blur3,
    gradient_mag,
    grid_to_leds,
)
from nuphy_rgb.visualizer import freq_to_hue


def _laplacian(field: np.ndarray) -> np.ndarray:
    """Edge-padded discrete Laplacian on a (NUM_ROWS, MAX_COLS) field.

    Axial neighbours weighted 0.2, diagonal neighbours 0.05, centre -1.0.
    """
    padded = np.pad(field, 1, mode="edge")

    center = padded[1:-1, 1:-1]

    # Axial neighbours (up, down, left, right) -- weight 0.2 each
    axial = (
        padded[0:-2, 1:-1]   # up
        + padded[2:,  1:-1]  # down
        + padded[1:-1, 0:-2] # left
        + padded[1:-1, 2:]   # right
    )

    # Diagonal neighbours -- weight 0.05 each
    diag = (
        padded[0:-2, 0:-2]  # top-left
        + padded[0:-2, 2:]  # top-right
        + padded[2:,  0:-2] # bottom-left
        + padded[2:,  2:]   # bottom-right
    )

    return axial * 0.2 + diag * 0.05 - center


def _hsv_rgb_grid(
    h_grid: np.ndarray,
    s: float,
    v_grid: np.ndarray,
) -> np.ndarray:
    """Convert per-cell HSV to an RGB grid, only touching valid cells.

    Parameters
    ----------
    h_grid : (NUM_ROWS, MAX_COLS) float array, hues in [0, 1]
    s      : scalar saturation
    v_grid : (NUM_ROWS, MAX_COLS) float array, values in [0, 1]

    Returns
    -------
    (NUM_ROWS, MAX_COLS, 3) float32 array in [0, 1]
    """
    out = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float32)
    rows, cols = np.where(VALID_MASK)
    for r, c in zip(rows, cols):
        h = float(h_grid[r, c])
        v = float(v_grid[r, c])
        rf, gf, bf = colorsys.hsv_to_rgb(h, s, v)
        out[r, c, 0] = rf
        out[r, c, 1] = gf
        out[r, c, 2] = bf
    return out


class CathedralOfSpores:
    """Gray-Scott reaction-diffusion visualizer.

    A and B fields evolve on the (NUM_ROWS, MAX_COLS) grid.  Beat onsets
    seed new colonies; audio parameters modulate the reaction kinetics so
    the growth patterns reflect the music in real time.
    """

    name = "Cathedral of Spores"

    def __init__(self) -> None:
        self._a: np.ndarray = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float32)
        self._b: np.ndarray = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float32)
        self._tint: np.ndarray = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float32)
        self._last_t: float = time.monotonic()

        # Seed one initial colony at the horizontal centre of each row.
        # A=0.8, B=0.25 gives the autocatalytic reaction (a*b^2) a nonzero start
        # so colonies can self-sustain and grow.
        rng = np.random.default_rng(42)
        for row in range(NUM_ROWS):
            col = MAX_COLS // 2
            self._a[row, col] = 0.8
            self._b[row, col] = 0.25
            self._tint[row, col] = rng.random()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        """Compute one frame and return 84 (R, G, B) tuples."""
        # 1. Time step
        now = frame.timestamp if frame.timestamp > 0 else time.monotonic()
        dt = min(now - self._last_t, 0.1)   # clamp runaway dt on first frame
        if dt <= 0:
            dt = 1.0 / 60.0
        self._last_t = now

        bass = float(frame.bass)
        mids = float(frame.mids)
        highs = float(frame.highs)
        rms = float(frame.rms)
        freq = float(frame.dominant_freq)
        tint_source = freq_to_hue(freq)

        # 2. Beat seeding -- place a new colony at a deterministic position
        if frame.is_beat:
            seed_val = int(abs(frame.timestamp * 1000 + freq + bass * 100)) % NUM_LEDS
            s_row, s_col = LED_ROW_COL[seed_val]
            # Seed with high A and nonzero B so the autocatalytic reaction starts
            self._a[s_row, s_col] = 1.0
            self._b[s_row, s_col] = 0.25
            self._tint[s_row, s_col] = freq_to_hue(freq)

        # 3. Gray-Scott parameters modulated by audio
        feed = 0.018 + bass * 0.04 + rms * 0.02
        kill = 0.03 + highs * 0.055
        da   = 0.22 + mids * 0.1
        db   = 0.08 + highs * 0.05

        # 4. Two reaction-diffusion sub-steps
        for _ in range(2):
            lap_a = _laplacian(self._a)
            lap_b = _laplacian(self._b)
            reaction = self._a * self._b * self._b
            self._a += dt * (da * lap_a - reaction + feed * (1.0 - self._a))
            self._b += dt * (db * lap_b + reaction - (kill + feed) * self._b)
            self._a = np.clip(self._a, 0.0, 1.0) * VALID_FLOAT
            self._b = np.clip(self._b, 0.0, 1.0) * VALID_FLOAT

        # 5. Visual extraction
        growth   = np.clip(self._a - self._b * 0.7, 0.0, 1.0)
        branch   = np.clip(gradient_mag(growth) * (1.4 + highs * 1.6), 0.0, 1.0)
        membrane = np.clip((blur3(growth) - growth) * -3.0, 0.0, 1.0)

        # 6. Tint drift
        self._tint = (
            self._tint * 0.985
            + growth * 0.012
            + tint_source * 0.003
        )
        self._tint = blur3(self._tint) * 0.5 + self._tint * 0.5

        # 7. Two hue channels
        hue_a = (tint_source + 0.18 + self._tint * 0.25) % 1.0
        hue_b = (tint_source + 0.62 - self._tint * 0.18) % 1.0

        # 8. Composite 3 layers (core / rim / glass) via additive blend
        #    core  -- main growth body, saturated, full value
        #    rim   -- branch edges, desaturated glow
        #    glass -- membrane shimmer, hue_b channel
        core  = _hsv_rgb_grid(hue_a, 0.85, growth)
        rim   = _hsv_rgb_grid(hue_a, 0.40, branch)
        glass = _hsv_rgb_grid(hue_b, 0.70, membrane)

        rgb = core + rim + glass   # additive blend (float, may exceed 1)

        # 9. Pulse on beat / RMS
        beat_bonus = 0.25 if frame.is_beat else 0.0
        rgb += growth[..., np.newaxis] * (0.1 + rms * 0.25 + beat_bonus)

        # 10. Clip, apply validity mask, quantise and flatten
        rgb = np.clip(rgb, 0.0, 1.0)
        rgb *= VALID_FLOAT[..., np.newaxis]

        return grid_to_leds(rgb)
