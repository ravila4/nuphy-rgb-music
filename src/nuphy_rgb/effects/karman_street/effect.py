"""Kármán Street: vortex shedding past an obstacle.

A uniform bass-gated freestream flows rightward past a fixed square obstacle
in an internal 12x32 grid. The wake sheds alternating vortices (Kármán
vortex street) that drift downstream and wrap periodically. Dye is injected
by a Lagrangian cursor that rides the flow upstream of the obstacle, and
buoyancy couples warm/cool dye to vertical momentum so bass pumps warm
phase up and highs pull it down.

Designed after the v1 (two-stream K-H shear) effect failed its go/no-go
check — see research/navier_stokes.md for the postmortem. K-H was
physically out of reach on a 12x32 grid (Re_δ ~16 vs ~50 threshold, rollup
time 3s vs traversal time 1.6s). Kármán shedding at Re_D ~30 past a D=3
obstacle actually fires on this grid — confirmed via kymograph + FFT in
.scratch/karman_shedding_check.py before building.

See research/navier_stokes.md for full design rationale.
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

_INTERNAL_H = NUM_ROWS * 2   # 12
_INTERNAL_W = MAX_COLS * 2   # 32
_OBSTACLE_SIZE = 3
_OBSTACLE_ROW = _INTERNAL_H // 2 - _OBSTACLE_SIZE // 2  # 4
_OBSTACLE_COL = 8
_PRESSURE_ITERS = 20
_INTERNAL_SUBSTEPS = 2
_MAX_VELOCITY = 30.0
_DEFAULT_DT = 1.0 / 30.0
_MAX_DT = 1.0 / 15.0


class KarmanStreet:
    name = "Kármán Street"

    def __init__(self) -> None:
        self._u = np.zeros((_INTERNAL_H, _INTERNAL_W), dtype=np.float64)
        self._v = np.zeros((_INTERNAL_H, _INTERNAL_W), dtype=np.float64)
        self._dye = np.zeros((_INTERNAL_H, _INTERNAL_W, 3), dtype=np.float64)
        # Warm/cool scalar tracers for buoyancy coupling — separate from
        # RGB dye so the force doesn't depend on current hue.
        self._warm = np.zeros((_INTERNAL_H, _INTERNAL_W), dtype=np.float64)
        self._cool = np.zeros((_INTERNAL_H, _INTERNAL_W), dtype=np.float64)

        # Obstacle mask: square block the projector zeroes velocity inside.
        self._obstacle = np.zeros((_INTERNAL_H, _INTERNAL_W), dtype=bool)
        self._obstacle[
            _OBSTACLE_ROW:_OBSTACLE_ROW + _OBSTACLE_SIZE,
            _OBSTACLE_COL:_OBSTACLE_COL + _OBSTACLE_SIZE,
        ] = True
        self._free = ~self._obstacle

        # Two Lagrangian dye cursors — one for each phase — advected by
        # local flow. Spatial separation prevents the "warm + cool in the
        # same cell = warm white" additive-mix bug. Both start center-left
        # and drift to their targets as buoyancy pulls them apart.
        center_y = float(_INTERNAL_H / 2)
        self._warm_cursor_x = 2.0
        self._warm_cursor_y = center_y
        self._cool_cursor_x = 2.0
        self._cool_cursor_y = center_y

        # Cached coordinate grids for advection backtrace.
        j_idx, i_idx = np.meshgrid(
            np.arange(_INTERNAL_H, dtype=np.float64),
            np.arange(_INTERNAL_W, dtype=np.float64),
            indexing="ij",
        )
        self._i_idx = i_idx
        self._j_idx = j_idx
        self._rng = np.random.default_rng(0)
        self._last_timestamp: float | None = None

        self.params: dict[str, VisualizerParam] = {
            "freestream_idle": VisualizerParam(
                value=8.0, default=8.0, min=0.0, max=20.0,
                description="Baseline freestream speed on silence. Too low and shedding stops; too high and everything blurs.",
            ),
            "freestream_bass_gain": VisualizerParam(
                value=18.0, default=18.0, min=0.0, max=30.0,
                description="Bass multiplier added to freestream. Bass = stronger current = faster shedding.",
            ),
            "buoyancy_gain": VisualizerParam(
                value=8.0, default=8.0, min=0.0, max=20.0,
                description="Vertical force per unit warm dye. Bass pumps warm up, highs pull it down via signed buoyancy.",
            ),
            "cooling_gain": VisualizerParam(
                value=10.0, default=10.0, min=0.0, max=20.0,
                description="Highs-driven negative buoyancy. Higher = more aggressive sink on hi-hats.",
            ),
            "cursor_drift_amp": VisualizerParam(
                value=0.6, default=0.6, min=0.0, max=2.0,
                description="Vertical audio drive on the Lagrangian dye cursor (scaled by chroma column).",
            ),
            "dye_density": VisualizerParam(
                value=4.0, default=4.0, min=0.5, max=10.0,
                description="Dye injection rate at the cursor position.",
            ),
            "dye_decay": VisualizerParam(
                value=0.97, default=0.97, min=0.90, max=1.00,
                description="Per-frame dye fade. Lower = faster return to black on silence.",
            ),
            "velocity_decay": VisualizerParam(
                value=0.995, default=0.995, min=0.95, max=1.00,
                description="Per-frame velocity damping. Less than v1 because Kármán relies on coherent wake circulation.",
            ),
            "vorticity_gain": VisualizerParam(
                value=3.0, default=3.0, min=0.0, max=8.0,
                description="Vorticity confinement strength. Fights numerical diffusion on shed vortices.",
            ),
            "beat_kick": VisualizerParam(
                value=6.0, default=6.0, min=0.0, max=15.0,
                description="On is_beat, inject a vertical momentum kick just upstream of the obstacle. The drum-hit shed.",
            ),
            "turbulence_seed": VisualizerParam(
                value=0.08, default=0.08, min=0.0, max=0.3,
                description="Random force amplitude scaled by onset_strength. Keeps drone music alive and seeds shedding.",
            ),
            "brightness_gain": VisualizerParam(
                value=5.0, default=5.0, min=0.2, max=20.0,
                description="Output brightness multiplier applied after downsample.",
            ),
            "silence_gate": VisualizerParam(
                value=0.02, default=0.02, min=0.0, max=0.1,
                description="raw_rms threshold below which no cursor injection happens.",
            ),
            "chroma_tint": VisualizerParam(
                value=0.7, default=0.7, min=0.0, max=1.0,
                description="How much chroma argmax rotates the warm/cool hue pair.",
            ),
        }

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._compute_dt(frame.timestamp)
        sub_dt = dt / _INTERNAL_SUBSTEPS

        for _ in range(_INTERNAL_SUBSTEPS):
            self._step(frame, sub_dt)

        # Dye fades once per render, not per substep.
        self._dye *= self.params["dye_decay"].get()
        self._warm *= self.params["dye_decay"].get()
        self._cool *= self.params["dye_decay"].get()
        np.clip(self._dye, 0.0, 1.0, out=self._dye)

        return self._render_to_leds()

    def _compute_dt(self, timestamp: float) -> float:
        if self._last_timestamp is None:
            dt = _DEFAULT_DT
        else:
            dt = max(timestamp - self._last_timestamp, 1e-4)
        self._last_timestamp = timestamp
        return min(dt, _MAX_DT)

    def _step(self, frame: AudioFrame, dt: float) -> None:
        self._apply_freestream_force(frame)
        self._apply_buoyancy(frame, dt)
        self._apply_beat_kick(frame, dt)
        self._apply_turbulence(frame)
        self._enforce_obstacle()

        self._u = self._advect_scalar(self._u, dt)
        self._v = self._advect_scalar(self._v, dt)
        self._warm = self._advect_scalar(self._warm, dt)
        self._cool = self._advect_scalar(self._cool, dt)
        self._dye = self._advect_color(self._dye, dt)

        self._enforce_obstacle()
        self._vorticity_confinement(dt)
        self._project()

        self._u *= self.params["velocity_decay"].get()
        self._v *= self.params["velocity_decay"].get()
        np.clip(self._u, -_MAX_VELOCITY, _MAX_VELOCITY, out=self._u)
        np.clip(self._v, -_MAX_VELOCITY, _MAX_VELOCITY, out=self._v)

        self._inject_from_cursor(frame, dt)
        self._advance_cursor(frame, dt)

    def _target_freestream(self, frame: AudioFrame) -> float:
        idle = self.params["freestream_idle"].get()
        gain = self.params["freestream_bass_gain"].get()
        bass = max(0.0, min(float(frame.bass), 1.0))
        if frame.raw_rms < self.params["silence_gate"].get():
            return idle * 0.3
        return idle + gain * bass

    def _apply_freestream_force(self, frame: AudioFrame) -> None:
        # Restore the spatial mean of u toward target. Doesn't damp local
        # fluctuations — only the bulk transport.
        target = self._target_freestream(frame)
        mean_u = self._u[self._free].mean()
        self._u[self._free] += (target - mean_u) * 0.3

    def _apply_buoyancy(self, frame: AudioFrame, dt: float) -> None:
        bass = max(0.0, min(float(frame.bass), 1.0))
        highs = max(0.0, min(float(frame.highs), 1.0))
        g = (
            self.params["buoyancy_gain"].get() * bass
            - self.params["cooling_gain"].get() * highs
        )
        # Positive g → warm rises (row index decreases in screen, but here
        # we use row 0 as top of the grid so negative v = up).
        self._v -= dt * g * self._warm
        self._v += dt * g * self._cool * 0.5  # cool is lighter opposition

    def _apply_beat_kick(self, frame: AudioFrame, dt: float) -> None:
        kick = self.params["beat_kick"].get()
        if kick <= 0.0:
            return
        if frame.is_beat:
            # Vertical jet just upstream of the obstacle to shed a pair.
            col = max(0, _OBSTACLE_COL - 2)
            self._v[:, col:col + 2] += dt * kick * 30.0
            self._warm[:, col:col + 2] += 0.3
        if frame.high_beat or frame.mid_beat:
            col = max(0, _OBSTACLE_COL - 2)
            self._v[:, col:col + 2] -= dt * kick * 20.0
            self._cool[:, col:col + 2] += 0.25

    def _apply_turbulence(self, frame: AudioFrame) -> None:
        seed = self.params["turbulence_seed"].get()
        onset = float(getattr(frame, "onset_strength", 0.0))
        if seed > 0.0 and onset > 0.0:
            scale = seed * onset
            self._u += self._rng.standard_normal(self._u.shape) * scale
            self._v += self._rng.standard_normal(self._v.shape) * scale

    def _enforce_obstacle(self) -> None:
        self._u[self._obstacle] = 0.0
        self._v[self._obstacle] = 0.0
        self._v[0, :] = 0.0
        self._v[-1, :] = 0.0

    def _advect_scalar(self, field: np.ndarray, dt: float) -> np.ndarray:
        x = self._i_idx - dt * self._u
        y = self._j_idx - dt * self._v
        x = x % _INTERNAL_W
        y = np.clip(y, 0.0, _INTERNAL_H - 1.0 - 1e-6)

        i0 = x.astype(np.int64)
        j0 = y.astype(np.int64)
        i1 = (i0 + 1) % _INTERNAL_W
        j1 = np.minimum(j0 + 1, _INTERNAL_H - 1)
        fx = x - i0
        fy = y - j0

        return (
            (1 - fy) * (1 - fx) * field[j0, i0]
            + (1 - fy) * fx * field[j0, i1]
            + fy * (1 - fx) * field[j1, i0]
            + fy * fx * field[j1, i1]
        )

    def _advect_color(self, field: np.ndarray, dt: float) -> np.ndarray:
        x = self._i_idx - dt * self._u
        y = self._j_idx - dt * self._v
        x = x % _INTERNAL_W
        y = np.clip(y, 0.0, _INTERNAL_H - 1.0 - 1e-6)

        i0 = x.astype(np.int64)
        j0 = y.astype(np.int64)
        i1 = (i0 + 1) % _INTERNAL_W
        j1 = np.minimum(j0 + 1, _INTERNAL_H - 1)
        fx = (x - i0)[..., None]
        fy = (y - j0)[..., None]

        return (
            (1 - fy) * (1 - fx) * field[j0, i0]
            + (1 - fy) * fx * field[j0, i1]
            + fy * (1 - fx) * field[j1, i0]
            + fy * fx * field[j1, i1]
        )

    def _vorticity_confinement(self, dt: float) -> None:
        dv_dx = 0.5 * (np.roll(self._v, -1, axis=1) - np.roll(self._v, 1, axis=1))
        du_dy = np.zeros_like(self._u)
        du_dy[1:-1, :] = 0.5 * (self._u[2:, :] - self._u[:-2, :])
        w = dv_dx - du_dy
        abs_w = np.abs(w)

        grad_x = 0.5 * (np.roll(abs_w, -1, axis=1) - np.roll(abs_w, 1, axis=1))
        grad_y = np.zeros_like(abs_w)
        grad_y[1:-1, :] = 0.5 * (abs_w[2:, :] - abs_w[:-2, :])
        norm = np.sqrt(grad_x * grad_x + grad_y * grad_y) + 1e-8
        nx = grad_x / norm
        ny = grad_y / norm

        eps = self.params["vorticity_gain"].get()
        self._u += dt * eps * (ny * w)
        self._v += dt * eps * (-nx * w)

    def _project(self) -> None:
        div_x = 0.5 * (np.roll(self._u, -1, axis=1) - np.roll(self._u, 1, axis=1))
        div_y = np.zeros_like(self._u)
        div_y[1:-1, :] = 0.5 * (self._v[2:, :] - self._v[:-2, :])
        div = div_x + div_y

        p = np.zeros_like(self._u)
        for _ in range(_PRESSURE_ITERS):
            p_xm = np.roll(p, 1, axis=1)
            p_xp = np.roll(p, -1, axis=1)
            p_ym = np.empty_like(p)
            p_ym[1:, :] = p[:-1, :]
            p_ym[0, :] = p[0, :]
            p_yp = np.empty_like(p)
            p_yp[:-1, :] = p[1:, :]
            p_yp[-1, :] = p[-1, :]
            p = 0.25 * (p_xm + p_xp + p_ym + p_yp - div)

        grad_px = 0.5 * (np.roll(p, -1, axis=1) - np.roll(p, 1, axis=1))
        grad_py = np.zeros_like(p)
        grad_py[1:-1, :] = 0.5 * (p[2:, :] - p[:-2, :])
        self._u -= grad_px
        self._v -= grad_py
        self._enforce_obstacle()

    def _chroma_hue(self, frame: AudioFrame) -> float:
        chroma = np.asarray(frame.chroma, dtype=np.float64)
        if chroma.sum() <= 1e-6:
            return 0.0
        return float(int(np.argmax(chroma))) / float(len(chroma))

    def _stamp_cursor(
        self,
        cx: float,
        cy: float,
        rgb: tuple[float, float, float],
        rgb_density: float,
        scalar: np.ndarray,
        scalar_density: float,
    ) -> None:
        ci = int(round(cx)) % _INTERNAL_W
        cj = int(np.clip(round(cy), 0, _INTERNAL_H - 1))
        ii = np.arange(ci - 1, ci + 2) % _INTERNAL_W
        jj = np.clip(np.arange(cj - 1, cj + 2), 0, _INTERNAL_H - 1)
        rows, cols = np.meshgrid(jj, ii, indexing="ij")
        self._dye[rows, cols, 0] += rgb_density * rgb[0]
        self._dye[rows, cols, 1] += rgb_density * rgb[1]
        self._dye[rows, cols, 2] += rgb_density * rgb[2]
        scalar[rows, cols] += scalar_density

    def _inject_from_cursor(self, frame: AudioFrame, dt: float) -> None:
        if frame.raw_rms < self.params["silence_gate"].get():
            return

        base_density = self.params["dye_density"].get() * dt
        tint = self.params["chroma_tint"].get()
        hue_shift = self._chroma_hue(frame) * tint
        warm_h = (0.05 + hue_shift) % 1.0
        cool_h = (0.55 + hue_shift) % 1.0

        bass = max(0.0, min(float(frame.bass), 1.0))
        highs = max(0.0, min(float(frame.highs), 1.0))

        if bass > 0.05:
            wr, wg, wb = colorsys.hsv_to_rgb(warm_h, 0.95, 1.0)
            density = base_density * bass
            self._stamp_cursor(
                self._warm_cursor_x, self._warm_cursor_y,
                (wr, wg, wb), density, self._warm, density,
            )
        if highs > 0.05:
            cr, cg, cb = colorsys.hsv_to_rgb(cool_h, 0.95, 1.0)
            density = base_density * highs
            self._stamp_cursor(
                self._cool_cursor_x, self._cool_cursor_y,
                (cr, cg, cb), density, self._cool, density,
            )

    def _advance_cursor(self, frame: AudioFrame, dt: float) -> None:
        drift = self.params["cursor_drift_amp"].get()
        chroma_offset = (self._chroma_hue(frame) - 0.5) * (_INTERNAL_H * 0.3)
        center_y = _INTERNAL_H / 2
        # Small offsets around center — buoyancy does most of the separating.
        warm_target = center_y + 1.5 + chroma_offset
        cool_target = center_y - 1.5 + chroma_offset

        self._warm_cursor_x, self._warm_cursor_y = self._step_cursor(
            self._warm_cursor_x, self._warm_cursor_y, warm_target, drift, dt,
        )
        self._cool_cursor_x, self._cool_cursor_y = self._step_cursor(
            self._cool_cursor_x, self._cool_cursor_y, cool_target, drift, dt,
        )

    def _step_cursor(
        self, cx: float, cy: float, y_target: float, drift: float, dt: float,
    ) -> tuple[float, float]:
        ci = int(round(cx)) % _INTERNAL_W
        cj = int(np.clip(round(cy), 0, _INTERNAL_H - 1))
        uu = float(self._u[cj, ci])
        vv = float(self._v[cj, ci])
        vy_drive = drift * (y_target - cy) * 2.0
        cx += dt * uu
        cy += dt * (vv + vy_drive)
        if cx > _OBSTACLE_COL - 1 or cx < 0:
            cx = 2.0
        cy = float(np.clip(cy, 1.0, _INTERNAL_H - 2.0))
        return cx, cy

    def _render_to_leds(self) -> list[tuple[int, int, int]]:
        # 2x2 max-pool downsample so the most-saturated cell in each block
        # wins — preserves thin shed vortex cores that v1's mean smeared.
        reshaped = self._dye.reshape(NUM_ROWS, 2, MAX_COLS, 2, 3)
        out = reshaped.max(axis=(1, 3))
        brightness = self.params["brightness_gain"].get()
        out = np.clip(out * brightness, 0.0, 1.0)
        return grid_to_leds(out)
