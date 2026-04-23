"""Double Pendulum: a single chaotic tip painting a rainbow phosphor trail.

One double pendulum is integrated with RK4; only the outer bob is
rendered.  Its tip is splatted bilinearly into a decaying RGB field each
frame with a wall-clock-driven rainbow hue.  Audio couples into the
physics through time dilation only: loud passages run the pendulum
faster against the fixed phosphor decay, so the orbit self-overlaps
and the trail thickens into a multi-hued knot; silence throttles the
physics, gates deposits, and lets damping wind the bobs down to rest.

See research/double_pendulum.md for the full design rationale.
"""

from __future__ import annotations

import colorsys

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
_SUBSTEPS = 8
_MAX_OMEGA = 25.0

# Pendulum geometry — pivot sits just above the top row, rods chosen so
# the hanging-rest tip lands at (8, 5.5), i.e. bottom-center of the grid.
_PIVOT_X = 8.0
_PIVOT_Y = -0.5
_L1 = 3.0
_L2 = 3.0


class DoublePendulum:
    name = "Double Pendulum"

    def __init__(self) -> None:
        # Start both bobs near the top (unstable region) so the first
        # few seconds are immediately chaotic instead of a slow fall.
        self._state = np.array([2.2, 2.6, 0.0, 0.0], dtype=np.float64)

        self._trails = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        self._last_timestamp: float | None = None
        self._rng = np.random.default_rng()

        self.params: dict[str, VisualizerParam] = {
            "tail_decay": VisualizerParam(
                value=0.92, default=0.92, min=0.70, max=0.995,
                description="Per-frame RGB decay (higher = longer phosphor tail)",
            ),
            "speed_gain": VisualizerParam(
                value=3.0, default=3.0, min=0.5, max=8.0,
                description="Audio → physics time dilation (loud = faster pendulum)",
            ),
            "base_speed": VisualizerParam(
                value=0.5, default=0.5, min=0.0, max=2.0,
                description="Physics speed floor at silence (0 = frozen)",
            ),
            "hue_rate": VisualizerParam(
                value=0.15, default=0.15, min=0.0, max=1.0,
                description="Rainbow cycles per wall-clock second",
            ),
            "gravity": VisualizerParam(
                value=9.8, default=9.8, min=2.0, max=30.0,
                description="Attractor character (low = floaty, high = snappy)",
            ),
            "damping": VisualizerParam(
                value=0.002, default=0.002, min=0.0, max=0.02,
                description="Linear angular friction (so silence reaches rest)",
            ),
            "beat_kick": VisualizerParam(
                value=2.0, default=2.0, min=0.0, max=8.0,
                description="Angular velocity impulse to the outer bob on beat",
            ),
            "deposit_gain": VisualizerParam(
                value=1.5, default=1.5, min=0.3, max=4.0,
                description="Splat brightness scale",
            ),
        }

    # ------------------------------------------------------------------
    # Main render loop
    # ------------------------------------------------------------------

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._compute_dt(frame.timestamp)

        # Time dilation — the only audio → physics coupling.
        base = self.params["base_speed"].get()
        gain = self.params["speed_gain"].get()
        speed_factor = max(0.0, base + gain * max(0.0, float(frame.raw_rms)))
        phys_dt = dt * speed_factor

        if frame.is_beat:
            self._apply_beat_kick()

        if phys_dt > 1e-6:
            g = self.params["gravity"].get()
            damp = self.params["damping"].get()
            sub_dt = phys_dt / _SUBSTEPS
            for _ in range(_SUBSTEPS):
                self._rk4_step(sub_dt, g, damp)
            self._wrap_angles()
            np.clip(self._state[2:4], -_MAX_OMEGA, _MAX_OMEGA, out=self._state[2:4])

        # Phosphor decay happens on wall-clock, not physics time, so
        # faster physics = more trajectory per decay step = denser trail.
        decay = self.params["tail_decay"].get()
        self._trails *= decay

        # Deposit the current tip into the RGB field.
        gate = min(max(float(frame.raw_rms) * 4.0, 0.0), 1.0)
        if gate > 1e-3:
            x_tip, y_tip = self._tip_position()
            hue = (float(frame.timestamp) * self.params["hue_rate"].get()) % 1.0
            r, g_, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            intensity = self.params["deposit_gain"].get() * gate
            self._splat(x_tip, y_tip, r * intensity, g_ * intensity, b * intensity)

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

    @staticmethod
    def _derivs(state: np.ndarray, g: float, damp: float) -> np.ndarray:
        theta1, theta2, omega1, omega2 = state
        delta = theta1 - theta2
        sin_d = np.sin(delta)
        cos_d = np.cos(delta)
        den = 3.0 - np.cos(2.0 * delta)

        num1 = (
            -3.0 * g * np.sin(theta1)
            - g * np.sin(theta1 - 2.0 * theta2)
            - 2.0 * sin_d * (omega2 * omega2 * _L2 + omega1 * omega1 * _L1 * cos_d)
        )
        alpha1 = num1 / (_L1 * den) - damp * omega1

        num2 = 2.0 * sin_d * (
            2.0 * omega1 * omega1 * _L1
            + 2.0 * g * np.cos(theta1)
            + omega2 * omega2 * _L2 * cos_d
        )
        alpha2 = num2 / (_L2 * den) - damp * omega2

        return np.array([omega1, omega2, alpha1, alpha2], dtype=np.float64)

    def _rk4_step(self, dt: float, g: float, damp: float) -> None:
        s = self._state
        k1 = self._derivs(s, g, damp)
        k2 = self._derivs(s + 0.5 * dt * k1, g, damp)
        k3 = self._derivs(s + 0.5 * dt * k2, g, damp)
        k4 = self._derivs(s + dt * k3, g, damp)
        self._state = s + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

    def _wrap_angles(self) -> None:
        self._state[0] = ((self._state[0] + np.pi) % (2.0 * np.pi)) - np.pi
        self._state[1] = ((self._state[1] + np.pi) % (2.0 * np.pi)) - np.pi

    def _apply_beat_kick(self) -> None:
        kick = self.params["beat_kick"].get()
        if kick <= 0.0:
            return
        sign = 1.0 if self._rng.random() > 0.5 else -1.0
        self._state[3] += sign * kick

    def _tip_position(self) -> tuple[float, float]:
        theta1 = float(self._state[0])
        theta2 = float(self._state[1])
        x = _PIVOT_X + _L1 * np.sin(theta1) + _L2 * np.sin(theta2)
        y = _PIVOT_Y + _L1 * np.cos(theta1) + _L2 * np.cos(theta2)
        return x, y

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _splat(self, x: float, y: float, r: float, g: float, b: float) -> None:
        # Bilinear deposit with per-cell bounds clipping (no wrap — the
        # reach disk can extend off-grid on high-amplitude upswings).
        c0 = int(np.floor(x))
        r0 = int(np.floor(y))
        fx = x - c0
        fy = y - r0
        weights = (
            (r0, c0, (1.0 - fx) * (1.0 - fy)),
            (r0, c0 + 1, fx * (1.0 - fy)),
            (r0 + 1, c0, (1.0 - fx) * fy),
            (r0 + 1, c0 + 1, fx * fy),
        )
        t = self._trails
        for rr, cc, w in weights:
            if 0 <= rr < NUM_ROWS and 0 <= cc < MAX_COLS:
                t[rr, cc, 0] += w * r
                t[rr, cc, 1] += w * g
                t[rr, cc, 2] += w * b
