"""Conway's Jukebox: Game of Life on the keyboard, DJ'd by the music.

Each cell is a live/dead agent under Conway's rules. Beats inject seed
patterns (R-pentomino on bass, glider on mid, sparkle on highs). The chroma
class of the music at seed-time dyes newborn cells. Freshly-born cells flash
white and mature into their birth color. Dying cells leave a ghost afterglow.

The keyboard's irregular row lengths (16/15/15/14/14/10) are part of the
substrate — the modifier row is a hostile zone where life dies faster for
lack of neighbors. See research/conways_jukebox.md for the full design.
"""

from __future__ import annotations

import colorsys
import random

import numpy as np

from nuphy_rgb.plugin_api import (
    AudioFrame,
    MAX_COLS,
    NEIGHBORS,
    NUM_ROWS,
    RC_TO_LED,
    VALID_MASK,
    VisualizerParam,
    grid_to_leds,
)

_DEFAULT_DT = 1.0 / 30.0

# Canonical seed shapes, expressed as (dr, dc) offsets from an anchor cell.
_R_PENTOMINO: tuple[tuple[int, int], ...] = (
    (0, 1), (0, 2),
    (1, 0), (1, 1),
    (2, 1),
)
_GLIDER: tuple[tuple[int, int], ...] = (
    (0, 1),
    (1, 2),
    (2, 0), (2, 1), (2, 2),
)
_BLINKER: tuple[tuple[int, int], ...] = (
    (0, 0), (0, 1), (0, 2),
)

_VALID_CELLS: list[tuple[int, int]] = sorted(RC_TO_LED.keys())


class ConwaysJukebox:
    name = "Conway's Jukebox"

    def __init__(self) -> None:
        shape = (NUM_ROWS, MAX_COLS)
        self._alive = np.zeros(shape, dtype=bool)
        self._age = np.zeros(shape, dtype=np.int32)
        self._hue = np.zeros(shape, dtype=np.float64)
        self._ghost = np.zeros(shape, dtype=np.float64)
        self._ghost_hue = np.zeros(shape, dtype=np.float64)

        self._last_timestamp: float | None = None
        self._time = 0.0
        self._tick_accum = 0.0
        self._last_beat_tick_t = -1.0
        self._silence_brightness = 0.0
        self._rng = random.Random()

        self.params: dict[str, VisualizerParam] = {
            "tick_rate": VisualizerParam(
                value=6.0, default=6.0, min=1.0, max=20.0,
                description="Conway generations per second between beats.",
            ),
            "silence_thresh": VisualizerParam(
                value=0.02, default=0.02, min=0.0, max=0.2,
                description="raw_rms below this freezes the colony.",
            ),
            "ghost_decay": VisualizerParam(
                value=0.85, default=0.85, min=0.60, max=0.97,
                description="Afterglow falloff per frame for dying cells.",
            ),
            "min_population": VisualizerParam(
                value=3.0, default=3.0, min=0.0, max=20.0,
                description="Auto-seed if population drops below this.",
            ),
            "r_pent_chance": VisualizerParam(
                value=0.7, default=0.7, min=0.0, max=1.0,
                description="Bass-beat chance of R-pentomino vs simple blinker.",
            ),
            "beat_tick_cooldown_ms": VisualizerParam(
                value=80.0, default=80.0, min=20.0, max=400.0,
                description="Minimum gap between beat-forced Conway ticks.",
            ),
            "silence_fade_rate": VisualizerParam(
                value=0.93, default=0.93, min=0.70, max=0.99,
                description="Per-frame brightness falloff during silence. Lower = faster to black.",
            ),
        }

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._compute_dt(frame.timestamp)
        self._time += dt

        # Ghost afterglow decays every frame regardless of tick state
        ghost_decay = self.params["ghost_decay"].get() ** (dt / _DEFAULT_DT)
        self._ghost *= ghost_decay

        silence = frame.raw_rms < self.params["silence_thresh"].get()

        if silence:
            fade = self.params["silence_fade_rate"].get() ** (dt / _DEFAULT_DT)
            self._silence_brightness *= fade
        else:
            self._silence_brightness = 1.0

        if not silence:
            chroma_hue = _chroma_argmax_hue(frame.chroma)

            # Beat-driven seed injections. Each beat also forces a tick so
            # the seed takes a step immediately, giving the "drop" feeling.
            cooldown = self.params["beat_tick_cooldown_ms"].get() / 1000.0
            beat_this_frame = False
            onset = max(0.0, min(frame.onset_strength, 1.0))

            if frame.is_beat:
                self._inject_bass_seed(chroma_hue, onset)
                beat_this_frame = True
            if frame.mid_beat:
                self._inject_mid_seed(chroma_hue, onset)
                beat_this_frame = True
            if frame.high_beat:
                self._inject_high_seed(chroma_hue, onset)
                beat_this_frame = True

            if beat_this_frame and (self._time - self._last_beat_tick_t) >= cooldown:
                self._step_generation(chroma_hue)
                self._last_beat_tick_t = self._time

            # Steady-tempo evolution independent of beats
            tick_interval = 1.0 / max(self.params["tick_rate"].get(), 0.1)
            self._tick_accum += dt
            # Cap catch-up to avoid death spirals after long pauses
            max_ticks_per_frame = 4
            ticks_done = 0
            while self._tick_accum >= tick_interval and ticks_done < max_ticks_per_frame:
                self._step_generation(chroma_hue)
                self._tick_accum -= tick_interval
                ticks_done += 1
            if ticks_done == max_ticks_per_frame:
                self._tick_accum = 0.0

            # Auto-seed if population collapses. Keeps the colony from
            # going permanently extinct mid-song.
            if int(self._alive.sum()) < int(self.params["min_population"].get()):
                self._inject_high_seed(chroma_hue, 0.5)
        else:
            # Silence freezes the sim in place. Ghost still decays (handled
            # above), but no ticks and no seeds.
            self._tick_accum = 0.0

        return self._render_rgb()

    def _compute_dt(self, timestamp: float) -> float:
        if self._last_timestamp is None:
            dt = _DEFAULT_DT
        else:
            dt = max(timestamp - self._last_timestamp, 1e-4)
        self._last_timestamp = timestamp
        return dt

    def _step_generation(self, fallback_hue: float) -> None:
        alive = self._alive
        new_alive = np.zeros_like(alive)
        new_age = np.zeros_like(self._age)
        new_hue = self._hue.copy()

        for rc in _VALID_CELLS:
            r, c = rc
            nbrs = NEIGHBORS[rc]
            n_live = 0
            parent_hues: list[float] = []
            for nr, nc in nbrs:
                if alive[nr, nc]:
                    n_live += 1
                    parent_hues.append(float(self._hue[nr, nc]))

            if alive[r, c]:
                if n_live == 2 or n_live == 3:
                    new_alive[r, c] = True
                    new_age[r, c] = self._age[r, c] + 1
                    new_hue[r, c] = self._hue[r, c]
                else:
                    # Death: deposit a ghost
                    self._ghost[r, c] = max(self._ghost[r, c], 0.7)
                    self._ghost_hue[r, c] = self._hue[r, c]
            else:
                if n_live == 3:
                    new_alive[r, c] = True
                    new_age[r, c] = 0
                    new_hue[r, c] = _average_hue(parent_hues) if parent_hues else fallback_hue

        self._alive = new_alive & VALID_MASK
        self._age = new_age
        self._hue = new_hue

    def _inject_bass_seed(self, hue: float, onset: float) -> None:
        # Strong bass → R-pentomino (chaos). Weak → blinker (gentle).
        if self._rng.random() < self.params["r_pent_chance"].get():
            pattern = _R_PENTOMINO
        else:
            pattern = _BLINKER
        self._stamp_pattern(pattern, hue, bias_row=1)
        # Strong onsets drop two seeds for maximum chaos
        if onset > 0.6:
            self._stamp_pattern(pattern, hue, bias_row=2)

    def _inject_mid_seed(self, hue: float, onset: float) -> None:
        # Mid beats → gliders. They travel diagonally, reinforcing "motion".
        self._stamp_pattern(_GLIDER, hue, bias_row=0)
        if onset > 0.5:
            self._stamp_pattern(_GLIDER, hue, bias_row=2)

    def _inject_high_seed(self, hue: float, onset: float) -> None:
        # Highs → sparkle cells scattered anywhere
        count = 1 + int(round(onset * 2))
        for _ in range(count):
            rc = self._rng.choice(_VALID_CELLS)
            r, c = rc
            self._alive[r, c] = True
            self._age[r, c] = 0
            self._hue[r, c] = hue

    def _stamp_pattern(
        self,
        pattern: tuple[tuple[int, int], ...],
        hue: float,
        bias_row: int,
    ) -> None:
        # Pick an anchor that leaves room for the whole pattern inside a
        # valid region. Retry a few times; if nothing fits, no-op.
        max_dr = max(dr for dr, _ in pattern)
        max_dc = max(dc for _, dc in pattern)
        for _ in range(10):
            anchor_r = self._rng.randint(0, max(0, NUM_ROWS - 1 - max_dr))
            anchor_r = max(0, min(NUM_ROWS - 1 - max_dr, bias_row + anchor_r // 2))
            anchor_c = self._rng.randint(0, max(0, MAX_COLS - 1 - max_dc))
            cells = [(anchor_r + dr, anchor_c + dc) for dr, dc in pattern]
            if all((r, c) in RC_TO_LED for r, c in cells):
                for r, c in cells:
                    self._alive[r, c] = True
                    self._age[r, c] = 0
                    self._hue[r, c] = hue
                return

    def _render_rgb(self) -> list[tuple[int, int, int]]:
        rgb = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        silence_scale = self._silence_brightness
        if silence_scale < 1e-3:
            return grid_to_leds(rgb)

        # Live cells first: fresh = white, mature = full color
        live_cells = np.argwhere(self._alive)
        for r, c in live_cells:
            age = int(self._age[r, c])
            sat = min(1.0, age / 3.0)
            val = 1.0 if age < 8 else max(0.75, 1.0 - (age - 8) * 0.02)
            val *= silence_scale
            r_, g_, b_ = colorsys.hsv_to_rgb(float(self._hue[r, c]), sat, val)
            rgb[r, c, 0] = r_
            rgb[r, c, 1] = g_
            rgb[r, c, 2] = b_

        # Ghosts layered behind live cells (only if the live layer is dim)
        ghost_cells = np.argwhere(self._ghost > 1e-3)
        for r, c in ghost_cells:
            if self._alive[r, c]:
                continue
            g = float(self._ghost[r, c]) * silence_scale
            r_, g_, b_ = colorsys.hsv_to_rgb(float(self._ghost_hue[r, c]), 1.0, g)
            rgb[r, c, 0] = r_
            rgb[r, c, 1] = g_
            rgb[r, c, 2] = b_

        return grid_to_leds(rgb)


def _chroma_argmax_hue(chroma: tuple[float, ...]) -> float:
    if not chroma:
        return 0.0
    # 12 pitch classes → 12 evenly-spaced hues around the wheel
    idx = int(np.argmax(np.asarray(chroma, dtype=np.float64)))
    return (idx / 12.0) % 1.0


def _average_hue(hues: list[float]) -> float:
    # Circular mean so wrap-around (e.g. 0.95 + 0.05) doesn't average to 0.5
    if not hues:
        return 0.0
    angles = np.asarray(hues, dtype=np.float64) * 2.0 * np.pi
    mean = np.arctan2(np.sin(angles).mean(), np.cos(angles).mean())
    return float((mean / (2.0 * np.pi)) % 1.0)
