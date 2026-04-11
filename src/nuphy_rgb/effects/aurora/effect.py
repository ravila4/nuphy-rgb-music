"""Aurora Borealis visualizer effect.

Music-reactive aurora with physically-grounded emission colors.
Audio energy maps to solar wind intensity — louder music produces
taller, brighter, more colorful curtains with real spectroscopic
color stratification.
"""

import math
from dataclasses import dataclass

import numpy as np

from nuphy_rgb.audio import AudioFrame, ExpFilter
from nuphy_rgb.effects.grid import MAX_COLS, NUM_ROWS, VALID_MASK, grid_to_leds

# VALID_MASK is bool; we need float for broadcasting
_VALID_FLOAT = VALID_MASK.astype(np.float32)

# Real aurora emission line RGB values (from spectroscopy)
_O_GREEN = np.array([75.0, 255.0, 30.0]) / 255.0   # 557.7nm oxygen
_O_RED = np.array([255.0, 50.0, 0.0]) / 255.0       # 630.0nm oxygen
_N2_BLUE = np.array([55.0, 0.0, 255.0]) / 255.0     # 391.4nm nitrogen
_N2_PINK = np.array([255.0, 20.0, 60.0]) / 255.0    # ~670nm nitrogen

# Vertical emission color weights per row (6 rows).
# Row 0 = high altitude (red), Row 2-3 = green peak, Row 4-5 = blue/violet.
_ROW_EMISSION_WEIGHTS = np.array([
    [0.80, 0.20, 0.00, 0.00],  # Row 0: red dominant
    [0.35, 0.60, 0.05, 0.00],  # Row 1: red-green blend
    [0.05, 0.90, 0.05, 0.00],  # Row 2: green peak
    [0.02, 0.70, 0.25, 0.03],  # Row 3: green-cyan
    [0.00, 0.15, 0.75, 0.10],  # Row 4: blue/violet
    [0.00, 0.05, 0.60, 0.35],  # Row 5: faint violet/pink
], dtype=np.float32)

_EMISSION_PALETTE = np.array([
    _O_RED, _O_GREEN, _N2_BLUE, _N2_PINK,
], dtype=np.float32)
_ROW_COLORS = _ROW_EMISSION_WEIGHTS @ _EMISSION_PALETTE  # (6, 3)

_DEFAULT_DT = 1.0 / 30.0
_COLS = np.arange(MAX_COLS, dtype=np.float32)


@dataclass(frozen=True)
class _CurtainConfig:
    """Static configuration for a single aurora curtain band."""

    start: float           # initial x-center
    width: float           # Gaussian sigma (columns)
    drift_speed: float     # cols/sec horizontal drift
    fold_wavelength: float  # fold sine period (columns)
    fold_speed: float      # fold travel speed (cols/sec)
    drape_amount: float    # per-row x-offset amplitude


# Three curtains with distinct drift speeds (no phase-lock)
_CURTAIN_CONFIGS = [
    _CurtainConfig(start=2.0,  width=2.0, drift_speed=1.8,
                   fold_wavelength=5.0, fold_speed=3.5, drape_amount=1.2),
    _CurtainConfig(start=9.0,  width=2.2, drift_speed=-1.3,
                   fold_wavelength=6.0, fold_speed=-2.8, drape_amount=1.0),
    _CurtainConfig(start=14.0, width=1.8, drift_speed=0.9,
                   fold_wavelength=4.5, fold_speed=2.2, drape_amount=1.4),
]


class Aurora:
    """Aurora Borealis: music-reactive curtains with real emission physics."""

    name = "Aurora Borealis"

    def __init__(self) -> None:
        self._t: float = 0.0
        self._last_timestamp: float | None = None

        self._hem_drop: float = 0.0
        self._burst: float = 0.0
        # Slow red channel accumulator (mimics O 630nm slow emission)
        self._red_glow = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float32)
        self._prev_frame = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float32)
        self._energy_filter = ExpFilter(alpha_rise=0.6, alpha_decay=0.1)

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._compute_dt(frame.timestamp)

        # --- Audio → parameters ---
        energy = self._energy_filter.update(min(frame.raw_rms * 3.0, 1.0))
        drift_speed = 0.3 + frame.mids * 1.5
        self._t += drift_speed * dt

        # Decay first, then add impulses (so beat peak isn't immediately eroded)
        self._hem_drop *= 0.88
        self._burst *= 0.90
        if frame.is_beat:
            self._hem_drop = 1.8
            self._burst = min(self._burst + 0.5, 1.0)

        # Spectral flux drives fold shimmer speed (K-H turbulence)
        flux_fold_boost = frame.spectral_flux * 2.0

        # --- Vertical extent (clamped to preserve curtain silhouette) ---
        curtain_height = min(energy * 1.2 + self._hem_drop * 0.15, 1.0)
        base_hem = min(2.0 + curtain_height * 3.5, 4.5)
        hem = (
            base_hem + np.sin(_COLS * 0.6 + self._t * 0.3) * 0.8
            + self._hem_drop * 0.5
        )
        base_top = max(3.0 - curtain_height * 3.0, 0.5)
        top = base_top - np.sin(_COLS * 0.45 + self._t * 0.25) * 0.4

        # Audio color perturbation (same for all rows — compute once)
        audio_color_bump = (
            _O_GREEN * frame.bass * 0.15
            + _N2_BLUE * frame.mids * 0.10
            + _O_RED * frame.highs * 0.12
        )

        # --- Build grid ---
        rgb_grid = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float32)

        for row in range(NUM_ROWS):
            row_f = float(row)

            # Vertical fade masks
            fade_top = np.clip((row_f - top + 1.0) / 1.5, 0.0, 1.0)
            fade_bottom = np.clip((hem - row_f) / 1.5, 0.0, 1.0)
            vertical_mask = fade_top * fade_bottom

            # Accumulate curtain contributions for this row
            col_brightness = np.zeros(MAX_COLS, dtype=np.float32)

            for cfg in _CURTAIN_CONFIGS:
                # Linear drift with wrap-around
                center = (cfg.start + self._t * cfg.drift_speed) % MAX_COLS

                # Per-row drape: x-offset varies by row, creating wavy curtain shape
                drape_offset = cfg.drape_amount * math.sin(
                    row_f * 1.2 + self._t * 0.4
                )
                draped_center = center + drape_offset

                # Gaussian envelope (narrow — ~3-5 cols visible)
                dx = _COLS - draped_center
                dx = dx - MAX_COLS * np.round(dx / MAX_COLS)  # wrap to [-8, 8]
                envelope = np.exp(-0.5 * (dx / cfg.width) ** 2)

                # Fold brightness anchored to curtain position (travels with curtain).
                # spectral_flux boosts fold speed for K-H turbulence shimmer.
                fold_phase = (
                    dx * (2.0 * math.pi / cfg.fold_wavelength)
                    + self._t * (cfg.fold_speed + flux_fold_boost)
                )
                fold = 0.55 + 0.45 * np.sin(fold_phase)  # range [0.1, 1.0]

                col_brightness += envelope * fold

            col_brightness = np.clip(col_brightness, 0.0, 1.5)

            # Combined brightness
            brightness = col_brightness * vertical_mask * (energy + self._burst * 0.5)
            brightness = np.clip(brightness, 0.0, 1.0)

            # Emission color for this row
            color = _ROW_COLORS[row] + audio_color_bump

            # Saturation depth cue: bright peaks desaturate toward white
            white_mix = brightness ** 2 * 0.35
            desaturated = (
                color[None, :] * (1.0 - white_mix[:, None])
                + white_mix[:, None]
            )

            rgb_grid[row] = desaturated * brightness[:, None]

        # --- Red channel slow decay (O 630nm ~2s lifetime) ---
        red_decay = 0.97 if dt < 0.05 else (0.97 ** (dt / _DEFAULT_DT))
        self._red_glow = np.maximum(self._red_glow * red_decay, rgb_grid[:, :, 0])
        rgb_grid[:, :, 0] = self._red_glow

        # --- Temporal smoothing ---
        alpha_rise = 0.5
        alpha_decay = 0.35
        rising = rgb_grid > self._prev_frame
        alpha = np.where(rising, alpha_rise, alpha_decay)
        smoothed = alpha * rgb_grid + (1.0 - alpha) * self._prev_frame
        self._prev_frame = smoothed

        smoothed *= _VALID_FLOAT[:, :, None]
        return grid_to_leds(smoothed)

    def _compute_dt(self, timestamp: float) -> float:
        if self._last_timestamp is None:
            dt = _DEFAULT_DT
        else:
            dt = max(timestamp - self._last_timestamp, 1e-4)
        self._last_timestamp = timestamp
        return dt
