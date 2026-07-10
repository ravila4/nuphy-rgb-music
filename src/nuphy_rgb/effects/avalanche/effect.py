"""Avalanche: a Bak-Tang-Wiesenfeld sandpile fed by the music.

Each key holds grains of sand. The 16 spectrum bins rain grains onto the 16
columns of the top row -- bass sand on the left, treble on the right, each
grain carrying its column's hue. When a cell reaches 4 grains it topples,
throwing grains onto its neighbors (gravity-biased downward), which may
topple in turn. One topple-sweep runs per frame, so a deep cascade ripples
across the board as a white front over several frames instead of resolving
instantly. Sand pouring off the edges (and into the missing-key gaps) is the
dissipation that holds the pile at criticality.

The pile's load state is musical tension with no scripting: a build-up
deposits sand fast and drives cells toward threshold, so the drop's beat
clump triggers a board-spanning avalanche. Avalanche sizes follow a power
law -- most beats cause local slumps, the keyboard-wide cascade is rare and
earned by the song's structure. Color mixes as sand flows, leaving a
sediment record of the song's spectrum.

Brightness is a readout of model state: value = grain count, white flash =
topple, hue = deposition history. Silence stops the rain, lets in-flight
cascades run out, then cools the embers to black.

See research/avalanche.md for the design doc.
"""

from __future__ import annotations

import colorsys

import numpy as np

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.grid import MAX_COLS, NUM_ROWS, VALID_MASK, grid_to_leds
from nuphy_rgb.visualizer_params import VisualizerParam

_DEFAULT_DT = 1.0 / 30.0
_MAX_DT = 0.1
_REF_FPS = 30.0

TOPPLE_THRESHOLD = 4.0
_Z_CAP = 8.0           # backlog bound; cells above threshold topple anyway
_FRESH_WEIGHT = 2.0    # incoming sand outweighs resident sand in hue mixing
_SILENCE_RMS = 0.02

# Grain pigment per deposit column: red bass on the left through violet
# treble on the right. Spectrum bins are log-spaced, so a linear ramp over
# columns matches freq_to_hue() of the bin centers.
_COL_HUE = 0.83 * np.arange(MAX_COLS, dtype=np.float64) / (MAX_COLS - 1)

_TWO_PI = 2.0 * np.pi


def z_to_value(z: np.ndarray) -> np.ndarray:
    """Grain count -> brightness. Near-critical cells are the brightest
    stable state, so visual tension equals dynamical tension."""
    return np.interp(z, [0.0, 1.0, 2.0, 3.0], [0.0, 0.15, 0.4, 0.8])


def mix_hue(
    hue_a: np.ndarray, w_a: np.ndarray, hue_b: np.ndarray, w_b: np.ndarray
) -> np.ndarray:
    """Weighted circular mean of two hue fields. Keeps hue_a where the
    total weight vanishes (empty cells, antipodal cancellation)."""
    vec = w_a * np.exp(1j * _TWO_PI * hue_a) + w_b * np.exp(1j * _TWO_PI * hue_b)
    mixed = (np.angle(vec) / _TWO_PI) % 1.0
    return np.where(np.abs(vec) > 1e-9, mixed, hue_a)


def sample_columns(
    spectrum: tuple[float, ...], n: int, rng: np.random.Generator
) -> np.ndarray:
    """Sample n deposit columns from the flattened spectrum distribution.

    Weights are sqrt(spectrum): bass dominates highs 3-4x on real music, and
    linear weighting starves the treble columns of sand entirely.
    No spectral energy means no sand: returns an empty array.
    """
    if n <= 0:
        return np.empty(0, dtype=np.intp)
    s = np.sqrt(np.maximum(np.asarray(spectrum, dtype=np.float64), 0.0))
    total = s.sum()
    if total <= 1e-9:
        return np.empty(0, dtype=np.intp)
    return rng.choice(len(s), size=n, p=s / total)


def _shift_down(a: np.ndarray) -> np.ndarray:
    out = np.zeros_like(a)
    out[1:, :] = a[:-1, :]
    return out


def _shift_up(a: np.ndarray) -> np.ndarray:
    out = np.zeros_like(a)
    out[:-1, :] = a[1:, :]
    return out


def _shift_right(a: np.ndarray) -> np.ndarray:
    out = np.zeros_like(a)
    out[:, 1:] = a[:, :-1]
    return out


def _shift_left(a: np.ndarray) -> np.ndarray:
    out = np.zeros_like(a)
    out[:, :-1] = a[:, 1:]
    return out


def topple_step(
    z: np.ndarray,
    hue: np.ndarray,
    gravity_bias: float,
    fresh_weight: float = _FRESH_WEIGHT,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One simultaneous topple sweep (no relaxation to completion).

    Every cell at or above threshold loses 4 grains, split between its
    cardinal neighbors: gravity_bias=0 is the isotropic BTW rule (1 each),
    gravity_bias=1 is fully directed (2 down, 1 left, 1 right, 0 up).
    Grains aimed off-grid or at missing-key cells are lost -- the boundary
    dissipation that keeps the pile critical. Returns (z, hue, toppled).
    """
    toppled = (z >= TOPPLE_THRESHOLD) & VALID_MASK
    if not toppled.any():
        return z.copy(), hue.copy(), toppled

    out = np.where(toppled, TOPPLE_THRESHOLD, 0.0)
    up_share = (1.0 - gravity_bias) / 4.0
    down_share = (1.0 + gravity_bias) / 4.0
    side_share = 0.25

    pigment = np.exp(1j * _TWO_PI * hue)
    incoming = np.zeros_like(z)
    incoming_vec = np.zeros_like(z, dtype=np.complex128)
    for shift, share in (
        (_shift_down, down_share),
        (_shift_up, up_share),
        (_shift_right, side_share),
        (_shift_left, side_share),
    ):
        amount = shift(out * share)
        incoming += amount
        incoming_vec += shift(out * share * pigment)

    new_z = (z - out + incoming) * VALID_MASK

    resident_w = z - out
    vec = resident_w * pigment + fresh_weight * incoming_vec
    mixed = (np.angle(vec) / _TWO_PI) % 1.0
    new_hue = np.where(np.abs(vec) > 1e-9, mixed, hue)

    return new_z, new_hue, toppled


class Avalanche:
    name = "Avalanche"

    def __init__(self) -> None:
        self._rng = np.random.default_rng(0x5A2D)
        self._z = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        self._hue = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        self._glow = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        self._rain_residual = 0.0
        self._bright = 0.0          # ember envelope (rms gate)
        self._topple_count = 0      # lifetime topples, for tests/diagnostics
        self._last_timestamp: float | None = None

        self.params: dict[str, VisualizerParam] = {
            "rain_rate": VisualizerParam(
                value=1.2, default=1.2, min=0.2, max=8.0,
                description="Max grains per frame at full loudness/onset. The loading rate that drives the pile toward criticality.",
            ),
            "clump_size": VisualizerParam(
                value=5.0, default=5.0, min=2.0, max=10.0,
                description="Grains dropped at the loudest spectral column on each beat -- the avalanche trigger.",
            ),
            "gravity_bias": VisualizerParam(
                value=0.5, default=0.5, min=0.0, max=1.0,
                description="0 = isotropic BTW topple (fractal patterns, no gravity); 1 = fully directed downward (waterfall, no upward cascades).",
            ),
            "glow_decay": VisualizerParam(
                value=0.85, default=0.85, min=0.6, max=0.97,
                description="Per-frame persistence of the white topple flash.",
            ),
            "evaporation": VisualizerParam(
                value=0.02, default=0.02, min=0.0, max=0.2,
                description="Fraction of the pile removed per second during silence, so a song's leftover tension doesn't ambush the next track.",
            ),
            "ember_decay": VisualizerParam(
                value=0.93, default=0.93, min=0.8, max=0.99,
                description="Per-frame brightness retention when the music drops. 0.93 cools to black in about 2 s.",
            ),
            "fresh_weight": VisualizerParam(
                value=3.0, default=3.0, min=1.0, max=8.0,
                description="How much incoming sand outweighs resident sand in hue mixing. Low = colors blend toward mud; high = fresh deposits recolor cells, keeping bass/treble identity.",
            ),
        }

    def _dt(self, timestamp: float) -> float:
        if self._last_timestamp is None:
            self._last_timestamp = timestamp
            return _DEFAULT_DT
        dt = timestamp - self._last_timestamp
        self._last_timestamp = timestamp
        if dt <= 0.0:
            return _DEFAULT_DT
        return min(dt, _MAX_DT)

    def _deposit(self, cols: np.ndarray) -> None:
        """Drop one grain per entry of cols onto row 0, mixing pigment."""
        if len(cols) == 0:
            return
        counts = np.bincount(cols, minlength=MAX_COLS).astype(np.float64)
        fresh = self.params["fresh_weight"].value
        self._hue[0] = mix_hue(self._hue[0], self._z[0], _COL_HUE, fresh * counts)
        self._z[0] += counts

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._dt(frame.timestamp)
        p = self.params

        # --- ember envelope: fast attack, slow release ----------------------
        loud = min(1.0, 1.4 * frame.rms)
        if loud > self._bright:
            self._bright = loud
        else:
            ember = p["ember_decay"].value
            self._bright = ember * self._bright + (1.0 - ember) * loud

        # --- rain: spectrum-directed deposition -----------------------------
        # Mostly onset-driven: SOC needs the drive slow relative to the
        # relaxation, and sustained-rms rain buries the pile in seconds.
        drive = min(1.0, 0.2 * frame.rms + 0.8 * frame.onset_strength)
        self._rain_residual += p["rain_rate"].value * drive * dt * _REF_FPS
        n_grains = int(self._rain_residual)
        self._rain_residual -= n_grains
        self._deposit(sample_columns(frame.spectrum, n_grains, self._rng))

        # --- beat clump at the loudest column --------------------------------
        if frame.is_beat:
            s = np.asarray(frame.spectrum, dtype=np.float64)
            if s.sum() > 1e-9:
                col = int(np.argmax(s))
                self._deposit(
                    np.full(int(p["clump_size"].value), col, dtype=np.intp)
                )

        # --- one topple sweep: cascades animate across frames ----------------
        self._z, self._hue, toppled = topple_step(
            self._z, self._hue, p["gravity_bias"].value, p["fresh_weight"].value
        )
        self._topple_count += int(toppled.sum())
        self._glow = np.minimum(
            self._glow * p["glow_decay"].value + toppled.astype(np.float64), 1.5
        )

        np.minimum(self._z, _Z_CAP, out=self._z)

        # --- silence: evaporate old sediment ---------------------------------
        if frame.rms < _SILENCE_RMS:
            self._z *= max(0.0, 1.0 - p["evaporation"].value * dt)

        # --- render -----------------------------------------------------------
        base = z_to_value(self._z)
        value = self._bright * np.minimum(1.0, base + self._glow)
        sat = 0.85 * (1.0 - np.minimum(1.0, self._glow))  # flash whitens

        grid = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        for r in range(NUM_ROWS):
            for c in range(MAX_COLS):
                v = float(value[r, c])
                if v <= 0.004 or not VALID_MASK[r, c]:
                    continue
                rr, gg, bb = colorsys.hsv_to_rgb(
                    float(self._hue[r, c]), float(sat[r, c]), v
                )
                grid[r, c, 0] = rr
                grid[r, c, 1] = gg
                grid[r, c, 2] = bb

        return grid_to_leds(grid)
