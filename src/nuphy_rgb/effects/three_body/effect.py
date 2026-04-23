"""Three Body: bounded gravitational chaos on the 6x16 keyboard grid.

Three point masses on a torus (grid wraps left-right and top-bottom),
interacting via softened Newtonian gravity integrated with velocity Verlet.
Each body owns one audio band — bass = red, mids = green, highs = blue — so
louder bands produce heavier bodies that pull the system harder (continuous
gravitational perturbation).  Beats deliver random-direction velocity
impulses to the matching body (discrete energy perturbation).  Trails are
exponentially decaying per-channel brightness fields deposited bilinearly
at each body's sub-pixel position; trail lifetime scales with volume, so
quiet passages leave short arcs and loud ones paint the whole phase
portrait.

See research/three_body.md for the full design rationale.
"""

from __future__ import annotations

import numpy as np

from nuphy_rgb.plugin_api import (
    AudioFrame,
    MAX_COLS,
    NUM_ROWS,
    VisualizerParam,
    grid_to_leds,
)

_DEFAULT_DT = 1.0 / 30.0
_MAX_DT = 0.1
_N_BODIES = 3
_SUBSTEPS = 6
_W = float(MAX_COLS)  # 16
_H = float(NUM_ROWS)  # 6


def _wrap(value: np.ndarray, size: float) -> np.ndarray:
    return value - np.floor(value / size) * size


def _min_image(delta: float, size: float) -> float:
    # Shortest displacement on a periodic domain of length `size`.
    return delta - size * round(delta / size)


class ThreeBody:
    name = "Three Body"

    def __init__(self) -> None:
        rng = np.random.default_rng()

        # Spread bodies out so the first frame isn't a singular collapse.
        self._pos = np.array(
            [
                [0.25 * _W, 0.50 * _H],
                [0.55 * _W, 0.25 * _H],
                [0.80 * _W, 0.70 * _H],
            ],
            dtype=np.float64,
        )

        angles = rng.uniform(0.0, 2.0 * np.pi, _N_BODIES)
        speed = 3.0
        self._vel = np.stack([np.cos(angles), np.sin(angles)], axis=1) * speed
        # Zero net momentum so the center of mass stays put.
        self._vel -= self._vel.mean(axis=0, keepdims=True)
        self._acc = np.zeros((_N_BODIES, 2), dtype=np.float64)

        self._trails = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        self._last_timestamp: float | None = None
        self._rng = rng

        self.params: dict[str, VisualizerParam] = {
            "G": VisualizerParam(
                value=4.0, default=4.0, min=0.5, max=12.0,
                description="Gravitational constant (higher = tighter orbits)",
            ),
            "softening": VisualizerParam(
                value=0.8, default=0.8, min=0.3, max=2.0,
                description="Plummer softening radius in grid cells (avoids r=0 singularity)",
            ),
            "base_mass": VisualizerParam(
                value=0.4, default=0.4, min=0.1, max=1.0,
                description="Minimum body mass at silence",
            ),
            "mass_gain": VisualizerParam(
                value=1.6, default=1.6, min=0.0, max=4.0,
                description="Audio band contribution to body mass",
            ),
            "beat_kick": VisualizerParam(
                value=6.0, default=6.0, min=0.0, max=15.0,
                description="Velocity impulse applied to the body whose band beat fired",
            ),
            "max_speed": VisualizerParam(
                value=18.0, default=18.0, min=5.0, max=40.0,
                description="Per-body speed ceiling — prevents runaway from resonant kicks",
            ),
            "drag": VisualizerParam(
                value=0.02, default=0.02, min=0.0, max=0.2,
                description="Silence-proportional velocity drag (per second)",
            ),
            "decay_low": VisualizerParam(
                value=0.80, default=0.80, min=0.60, max=0.95,
                description="Trail decay at silence (lower = shorter tails)",
            ),
            "decay_high": VisualizerParam(
                value=0.96, default=0.96, min=0.90, max=0.99,
                description="Trail decay at full volume (higher = longer tails)",
            ),
            "body_brightness": VisualizerParam(
                value=1.3, default=1.3, min=0.3, max=3.0,
                description="Deposit intensity per body",
            ),
        }

    # ------------------------------------------------------------------
    # Main render loop
    # ------------------------------------------------------------------

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._compute_dt(frame.timestamp)
        masses = self._compute_masses(frame)

        self._apply_beat_kicks(frame)

        sub_dt = dt / _SUBSTEPS
        for _ in range(_SUBSTEPS):
            self._verlet_step(sub_dt, masses)

        self._apply_drag(dt, frame.raw_rms)
        self._clamp_speed()

        decay = self._compute_decay(frame.raw_rms)
        self._trails *= decay
        self._deposit(masses, frame.raw_rms)
        np.clip(self._trails, 0.0, 1.0, out=self._trails)

        return grid_to_leds(self._trails)

    # ------------------------------------------------------------------
    # Time
    # ------------------------------------------------------------------

    def _compute_dt(self, timestamp: float) -> float:
        if self._last_timestamp is None:
            dt = _DEFAULT_DT
        else:
            dt = max(timestamp - self._last_timestamp, 1e-4)
        self._last_timestamp = timestamp
        return min(dt, _MAX_DT)

    # ------------------------------------------------------------------
    # Physics
    # ------------------------------------------------------------------

    def _compute_masses(self, frame: AudioFrame) -> np.ndarray:
        base = self.params["base_mass"].get()
        gain = self.params["mass_gain"].get()
        return np.array(
            [
                base + gain * max(0.0, float(frame.bass)),
                base + gain * max(0.0, float(frame.mids)),
                base + gain * max(0.0, float(frame.highs)),
            ],
            dtype=np.float64,
        )

    def _compute_accel(self, pos: np.ndarray, masses: np.ndarray) -> np.ndarray:
        G = self.params["G"].get()
        eps2 = self.params["softening"].get() ** 2
        acc = np.zeros_like(pos)
        for i in range(_N_BODIES):
            for j in range(_N_BODIES):
                if i == j:
                    continue
                dx = _min_image(float(pos[j, 0] - pos[i, 0]), _W)
                dy = _min_image(float(pos[j, 1] - pos[i, 1]), _H)
                r2 = dx * dx + dy * dy + eps2
                inv_r3 = r2 ** -1.5
                acc[i, 0] += G * masses[j] * dx * inv_r3
                acc[i, 1] += G * masses[j] * dy * inv_r3
        return acc

    def _verlet_step(self, dt: float, masses: np.ndarray) -> None:
        self._vel += 0.5 * self._acc * dt
        self._pos[:, 0] = _wrap(self._pos[:, 0] + self._vel[:, 0] * dt, _W)
        self._pos[:, 1] = _wrap(self._pos[:, 1] + self._vel[:, 1] * dt, _H)
        self._acc = self._compute_accel(self._pos, masses)
        self._vel += 0.5 * self._acc * dt

    def _apply_beat_kicks(self, frame: AudioFrame) -> None:
        kick = self.params["beat_kick"].get()
        if kick <= 0.0:
            return
        flags = (frame.is_beat, frame.mid_beat, frame.high_beat)
        for i, flagged in enumerate(flags):
            if not flagged:
                continue
            angle = self._rng.uniform(0.0, 2.0 * np.pi)
            self._vel[i, 0] += kick * np.cos(angle)
            self._vel[i, 1] += kick * np.sin(angle)

    def _apply_drag(self, dt: float, raw_rms: float) -> None:
        silence = 1.0 - min(max(raw_rms * 3.0, 0.0), 1.0)
        drag = self.params["drag"].get() * silence
        self._vel *= max(0.0, 1.0 - drag * dt * 30.0)

    def _clamp_speed(self) -> None:
        max_speed = self.params["max_speed"].get()
        speeds = np.linalg.norm(self._vel, axis=1)
        over = speeds > max_speed
        if np.any(over):
            self._vel[over] *= (max_speed / speeds[over])[:, None]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _compute_decay(self, raw_rms: float) -> float:
        # Volume-modulated trail lifetime: quiet = short tails, loud = long
        loud = min(max(raw_rms * 3.0, 0.0), 1.0)
        low = self.params["decay_low"].get()
        high = self.params["decay_high"].get()
        return low + (high - low) * loud

    def _deposit(self, masses: np.ndarray, raw_rms: float) -> None:
        gate = min(max(raw_rms * 4.0, 0.0), 1.0)
        if gate <= 1e-3:
            return
        intensity = self.params["body_brightness"].get() * gate
        base_mass = self.params["base_mass"].get()

        for i in range(_N_BODIES):
            x = float(self._pos[i, 0])
            y = float(self._pos[i, 1])
            brightness = intensity * (
                0.35 + 0.65 * min(masses[i] / (base_mass + 1.0), 1.5)
            )
            self._splat(i, x, y, brightness)

    def _splat(self, channel: int, x: float, y: float, value: float) -> None:
        # Bilinear deposit with torus wrap in both axes.
        c0 = int(np.floor(x)) % MAX_COLS
        r0 = int(np.floor(y)) % NUM_ROWS
        c1 = (c0 + 1) % MAX_COLS
        r1 = (r0 + 1) % NUM_ROWS
        fx = x - np.floor(x)
        fy = y - np.floor(y)
        t = self._trails
        t[r0, c0, channel] += (1.0 - fx) * (1.0 - fy) * value
        t[r0, c1, channel] += fx * (1.0 - fy) * value
        t[r1, c0, channel] += (1.0 - fx) * fy * value
        t[r1, c1, channel] += fx * fy * value
