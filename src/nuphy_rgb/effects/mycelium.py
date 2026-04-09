"""Mycelium: organic, phosphorescent tendril growth driven by music beats."""

import colorsys
import random
from dataclasses import dataclass

import numpy as np

from nuphy_rgb.audio import AudioFrame, ExpFilter
from nuphy_rgb.effects.grid import MAX_COLS, NEIGHBORS, NUM_LEDS, NUM_ROWS, RC_TO_LED, grid_to_leds


@dataclass
class _Tendril:
    row: int
    col: int
    hue: float
    energy: float
    age: int
    max_age: int
    alive: bool = True


def _hue_from_bands(bass: float, mids: float, highs: float, rng: random.Random) -> float:
    """Pick a hue weighted by band energies.

    Bass -> red/warm  (0.0 - 0.08)
    Mids -> green     (0.25 - 0.42)
    Highs -> blue/cool (0.58 - 0.78)
    """
    total = bass + mids + highs
    if total < 1e-9:
        # No signal: pick a random greenish hue (phosphorescent default)
        return rng.uniform(0.25, 0.42)

    r = rng.random()
    bass_w = bass / total
    mids_w = mids / total
    if r < bass_w:
        return rng.uniform(0.0, 0.08)
    elif r < bass_w + mids_w:
        return rng.uniform(0.25, 0.42)
    else:
        return rng.uniform(0.58, 0.78)


class Mycelium:
    """Organic phosphorescent tendril growth synced to music beats.

    On each beat, tendrils spawn at random keyboard positions and grow
    outward through neighboring keys, leaving a fading bioluminescent trail.
    Color reflects the dominant frequency band: bass=red, mids=green, highs=blue.
    """

    name = "Mycelium"

    def __init__(
        self,
        num_leds: int = NUM_LEDS,
        max_tendrils: int = 60,
        seed: int | None = None,
    ):
        self._num_leds = num_leds
        self._max_tendrils = max_tendrils
        self._rng = random.Random(seed)
        self._tendrils: list[_Tendril] = []
        self._glow = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float32)
        self._rms_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)
        self._occupied: set[tuple[int, int]] = set()

    def _stamp(self, row: int, col: int, hue: float, energy: float) -> None:
        """Blend HSV color into the glow grid at (row, col) using max blend."""
        r_f, g_f, b_f = colorsys.hsv_to_rgb(hue, 0.95, min(energy * 1.5, 1.0))
        self._glow[row, col, 0] = max(self._glow[row, col, 0], r_f)
        self._glow[row, col, 1] = max(self._glow[row, col, 1], g_f)
        self._glow[row, col, 2] = max(self._glow[row, col, 2], b_f)

    def _spawn_tendrils(self, frame: AudioFrame) -> None:
        """Spawn 2-5 new tendrils at random unoccupied grid positions."""
        all_positions = list(RC_TO_LED.keys())
        unoccupied = [p for p in all_positions if p not in self._occupied]
        if not unoccupied:
            return

        bonus = min(int(frame.onset_strength * 5), 3)
        count = self._rng.randint(2, 5) + bonus
        slots = self._max_tendrils - len(self._tendrils)
        count = min(count, slots, len(unoccupied))

        positions = self._rng.sample(unoccupied, count)
        for row, col in positions:
            hue = _hue_from_bands(frame.bass, frame.mids, frame.highs, self._rng)
            max_age = self._rng.randint(8, 20)
            t = _Tendril(
                row=row,
                col=col,
                hue=hue,
                energy=1.0,
                age=0,
                max_age=max_age,
            )
            self._tendrils.append(t)
            self._occupied.add((row, col))

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        # 1. Smooth RMS
        rms = self._rms_filter.update(frame.rms)

        # 2. Decay glow (modulated by spectral flux — faster decay during busy passages)
        decay = 0.93 - frame.spectral_flux * 0.05
        self._glow *= decay

        # 3. Phosphorescent base: keep a minimum green floor
        self._glow[:, :, 1] = np.maximum(self._glow[:, :, 1], 0.02)

        # 4. On beat: spawn new tendrils
        if frame.is_beat and len(self._tendrils) < self._max_tendrils:
            self._spawn_tendrils(frame)

        # 5. Grow existing tendrils
        forks: list[_Tendril] = []
        for t in self._tendrils:
            if not t.alive:
                continue

            # Stamp current position
            self._stamp(t.row, t.col, t.hue, t.energy)

            # Advance age and decay energy
            t.age += 1
            t.energy *= 0.82

            # Check death conditions
            if t.age >= t.max_age or t.energy < 0.05:
                t.alive = False
                continue

            # Growth: move to a random unoccupied neighbor
            growth_chance = 0.4 + 0.5 * rms
            if self._rng.random() < growth_chance:
                nbrs = NEIGHBORS.get((t.row, t.col), [])
                free_nbrs = [n for n in nbrs if n not in self._occupied]
                if free_nbrs:
                    nr, nc = self._rng.choice(free_nbrs)
                    self._occupied.add((nr, nc))
                    t.row = nr
                    t.col = nc

            # Fork: 20% chance to spawn a child tendril
            if (
                self._rng.random() < 0.20
                and len(self._tendrils) + len(forks) < self._max_tendrils
            ):
                nbrs = NEIGHBORS.get((t.row, t.col), [])
                free_nbrs = [n for n in nbrs if n not in self._occupied]
                if free_nbrs:
                    fr, fc = self._rng.choice(free_nbrs)
                    hue_shift = self._rng.choice([-0.03, 0.03])
                    fork = _Tendril(
                        row=fr,
                        col=fc,
                        hue=(t.hue + hue_shift) % 1.0,
                        energy=t.energy * 0.7,
                        age=0,
                        max_age=self._rng.randint(8, 16),
                    )
                    self._occupied.add((fr, fc))
                    forks.append(fork)

        # Mid-beat fork burst: snapshot positions and spawn extra forks
        if frame.mid_beat:
            snapshot_occupied = (
                {(t.row, t.col) for t in self._tendrils if t.alive}
                | {(f.row, f.col) for f in forks}
            )
            mid_forks: list[_Tendril] = []
            for t in self._tendrils:
                if not t.alive:
                    continue
                if len(self._tendrils) + len(forks) + len(mid_forks) >= self._max_tendrils:
                    break
                nbrs = NEIGHBORS.get((t.row, t.col), [])
                free_nbrs = [n for n in nbrs if n not in snapshot_occupied]
                if free_nbrs:
                    fr, fc = self._rng.choice(free_nbrs)
                    fork = _Tendril(
                        row=fr,
                        col=fc,
                        hue=(t.hue + self._rng.choice([-0.05, 0.05])) % 1.0,
                        energy=t.energy * 0.6,
                        age=0,
                        max_age=self._rng.randint(6, 12),
                    )
                    snapshot_occupied.add((fr, fc))
                    mid_forks.append(fork)
            forks.extend(mid_forks)

        # Collect forks after the loop to avoid mutating list during iteration
        self._tendrils.extend(forks)

        # 6. Clean up dead tendrils, rebuild occupied from live positions
        self._tendrils = [t for t in self._tendrils if t.alive]
        self._occupied = {(t.row, t.col) for t in self._tendrils}

        # 7. Convert grid to LED list
        return grid_to_leds(self._glow)
