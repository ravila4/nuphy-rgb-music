"""Navier-Stokes: Stable Fluids on the 6x16 keyboard grid.

Two opposed dye streams (red from left driven by bass, cyan from right
driven by highs) shear past each other in the middle of an internal
12x32 grid, generating Kelvin-Helmholtz vortices that roll up and drift.
The fluid is computed via Jos Stam's Stable Fluids algorithm with
vorticity confinement (Fedkiw 2001) instead of explicit viscosity, then
2x2-downsampled to the 6x16 keyboard output.

See research/navier_stokes.md for the full design rationale.
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
_TOP_STREAM_ROW = 3
_BOT_STREAM_ROW = 8
_PRESSURE_ITERS = 20
_INTERNAL_SUBSTEPS = 3
_MAX_VELOCITY = 20.0
_DEFAULT_DT = 1.0 / 30.0
_MAX_DT = 1.0 / 15.0


class NavierStokes:
    name = "Navier-Stokes"

    def __init__(self) -> None:
        self._u = np.zeros((_INTERNAL_H, _INTERNAL_W), dtype=np.float64)
        self._v = np.zeros((_INTERNAL_H, _INTERNAL_W), dtype=np.float64)
        self._dye = np.zeros((_INTERNAL_H, _INTERNAL_W, 3), dtype=np.float64)
        self._last_timestamp: float | None = None

        # Cached coordinate grids for vectorized advection backtrace.
        j_idx, i_idx = np.meshgrid(
            np.arange(_INTERNAL_H, dtype=np.float64),
            np.arange(_INTERNAL_W, dtype=np.float64),
            indexing="ij",
        )
        self._i_idx = i_idx
        self._j_idx = j_idx

        self.params: dict[str, VisualizerParam] = {
            "vorticity_gain": VisualizerParam(
                value=2.0, default=2.0, min=0.0, max=8.0,
                description="Vorticity confinement strength. The single knob for laminar vs swirly. Multiplied by (0.5 + mids) so mids modulates swirliness.",
            ),
            "dye_decay": VisualizerParam(
                value=0.97, default=0.97, min=0.90, max=1.00,
                description="Per-frame dye fade. Lower = faster return to black on silence.",
            ),
            "velocity_decay": VisualizerParam(
                value=0.99, default=0.99, min=0.95, max=1.00,
                description="Per-frame velocity damping. Without this, energy accumulates and the fluid eventually saturates.",
            ),
            "injection_force": VisualizerParam(
                value=5.0, default=5.0, min=0.5, max=20.0,
                description="Base force magnitude streams push with. Tunes drama.",
            ),
            "jet_speed": VisualizerParam(
                value=60.0, default=60.0, min=10.0, max=150.0,
                description="Velocity multiplier on injected jets (cells/sec per unit force). Controls how fast streams traverse the grid to meet in the middle. Was hardcoded 30.0; raised 2026-04-11.",
            ),
            "brightness_gain": VisualizerParam(
                value=3.2, default=3.2, min=0.2, max=4.0,
                description="Output brightness multiplier applied after downsample.",
            ),
            "highs_gain": VisualizerParam(
                value=10.0, default=10.0, min=0.5, max=10.0,
                description="Compensation gain on the right (cyan, highs-driven) stream. Default at ceiling because AGC'd highs averages much lower than bass on typical music; tuned 2026-04-11 — even 8x compensation left the right stream visibly weaker.",
            ),
            "silence_gate": VisualizerParam(
                value=0.02, default=0.02, min=0.0, max=0.1,
                description="raw_rms threshold below which no injection happens.",
            ),
            "beat_surge": VisualizerParam(
                value=7.0, default=7.0, min=1.0, max=10.0,
                description="Multiplier on injection force when is_beat / high_beat fires for the corresponding stream. Tuned 2026-04-11 — beats need a heavy punch on top of the steady flow to read as discrete events.",
            ),
            "stream_width": VisualizerParam(
                value=1.0, default=1.0, min=0.0, max=3.0,
                description="Half-width of injection band in internal cells. 0 = single row, 2 = 5 rows thick.",
            ),
            "chroma_tint": VisualizerParam(
                value=0.5, default=0.5, min=0.0, max=1.0,
                description="How much chroma argmax rotates the base red/cyan pair around the wheel. 0 = fixed, 1 = full pitch-driven hue rotation.",
            ),
            "turbulence_seed": VisualizerParam(
                value=0.15, default=0.15, min=0.0, max=0.3,
                description="Random force amplitude scaled by onset_strength. Prevents drone music from looking dead. Tuned 2026-04-11 — 0.05 was too subtle to feel.",
            ),
        }

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._compute_dt(frame.timestamp)
        sub_dt = dt / _INTERNAL_SUBSTEPS

        for _ in range(_INTERNAL_SUBSTEPS):
            self._add_forces(frame, sub_dt)
            self._u = self._advect_scalar(self._u, sub_dt)
            self._v = self._advect_scalar(self._v, sub_dt)
            self._apply_walls()
            self._vorticity_confinement(frame, sub_dt)
            self._project()
            self._dye = self._advect_color(self._dye, sub_dt)

            self._u *= self.params["velocity_decay"].get()
            self._v *= self.params["velocity_decay"].get()

        # Dye fades once per render, not per substep.
        self._dye *= self.params["dye_decay"].get()

        np.clip(self._u, -_MAX_VELOCITY, _MAX_VELOCITY, out=self._u)
        np.clip(self._v, -_MAX_VELOCITY, _MAX_VELOCITY, out=self._v)
        np.clip(self._dye, 0.0, 1.0, out=self._dye)

        return self._render_to_leds()

    def _compute_dt(self, timestamp: float) -> float:
        if self._last_timestamp is None:
            dt = _DEFAULT_DT
        else:
            dt = max(timestamp - self._last_timestamp, 1e-4)
        self._last_timestamp = timestamp
        return min(dt, _MAX_DT)

    def _apply_walls(self) -> None:
        # No-slip vertical walls: zero normal velocity at top and bottom rows.
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

    def _vorticity_confinement(self, frame: AudioFrame, dt: float) -> None:
        # curl: w = dv/dx - du/dy
        dv_dx = 0.5 * (np.roll(self._v, -1, axis=1) - np.roll(self._v, 1, axis=1))
        du_dy = np.zeros_like(self._u)
        du_dy[1:-1, :] = 0.5 * (self._u[2:, :] - self._u[:-2, :])
        w = dv_dx - du_dy
        abs_w = np.abs(w)

        # Gradient of |curl|: points from low-curl regions toward high-curl
        # regions. Confinement adds force perpendicular to this gradient,
        # which spins up the existing vortices instead of creating new ones.
        grad_x = 0.5 * (np.roll(abs_w, -1, axis=1) - np.roll(abs_w, 1, axis=1))
        grad_y = np.zeros_like(abs_w)
        grad_y[1:-1, :] = 0.5 * (abs_w[2:, :] - abs_w[:-2, :])
        norm = np.sqrt(grad_x * grad_x + grad_y * grad_y) + 1e-8
        nx = grad_x / norm
        ny = grad_y / norm

        eps = self.params["vorticity_gain"].get() * (0.5 + max(0.0, min(frame.mids, 1.0)))
        self._u += dt * eps * (ny * w)
        self._v += dt * eps * (-nx * w)

    def _project(self) -> None:
        # Divergence of velocity field.  x is periodic; y uses one-sided
        # differences at walls (where v is zero anyway).
        div = np.zeros_like(self._u)
        div_x = 0.5 * (np.roll(self._u, -1, axis=1) - np.roll(self._u, 1, axis=1))
        div_y = np.zeros_like(self._u)
        div_y[1:-1, :] = 0.5 * (self._v[2:, :] - self._v[:-2, :])
        div = div_x + div_y

        # Solve ∇²p = div via Jacobi iteration. Standard 5-point stencil
        # with x-wrap and y-edge replication for the wall boundary.
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

        # Subtract pressure gradient to make velocity field divergence-free.
        grad_px = 0.5 * (np.roll(p, -1, axis=1) - np.roll(p, 1, axis=1))
        grad_py = np.zeros_like(p)
        grad_py[1:-1, :] = 0.5 * (p[2:, :] - p[:-2, :])
        self._u -= grad_px
        self._v -= grad_py
        self._apply_walls()

    def _add_forces(self, frame: AudioFrame, dt: float) -> None:
        if frame.raw_rms < self.params["silence_gate"].get():
            return

        force = self.params["injection_force"].get()
        surge = self.params["beat_surge"].get()
        half_w = int(round(self.params["stream_width"].get()))
        tint = self.params["chroma_tint"].get()
        jet_speed = self.params["jet_speed"].get()

        chroma_hue = self._chroma_hue(frame)

        # Top stream: red, flowing right, driven by bass.
        bass_force = force * max(0.0, min(frame.bass, 1.0))
        if frame.is_beat:
            bass_force *= surge
        if bass_force > 0.0:
            r0 = max(0, _TOP_STREAM_ROW - half_w)
            r1 = min(_INTERNAL_H, _TOP_STREAM_ROW + half_w + 1)
            self._u[r0:r1, 0:5] += dt * bass_force * jet_speed
            red_h = (0.0 + chroma_hue * tint) % 1.0
            r, g, b = colorsys.hsv_to_rgb(red_h, 0.95, 1.0)
            density = bass_force * dt * 6.0
            self._dye[r0:r1, 0:5, 0] += density * r
            self._dye[r0:r1, 0:5, 1] += density * g
            self._dye[r0:r1, 0:5, 2] += density * b

        # Bottom stream: cyan, flowing left, driven by highs.
        # The highs_gain compensation here is critical: on typical music
        # the AGC normalizes bands relative to each other, but bass content
        # is still ~2-3x more energetic than highs in absolute terms, and
        # is_beat fires far more frequently than high_beat. Without this
        # gain the right stream is invisible against the left.
        high_force = force * max(0.0, min(frame.highs, 1.0)) * self.params["highs_gain"].get()
        # Both mid_beat and high_beat surge the right stream — high_beat
        # alone is too rare to matter, mid_beat catches hi-hats and cymbals.
        if frame.high_beat or frame.mid_beat:
            high_force *= surge
        if high_force > 0.0:
            r0 = max(0, _BOT_STREAM_ROW - half_w)
            r1 = min(_INTERNAL_H, _BOT_STREAM_ROW + half_w + 1)
            self._u[r0:r1, -5:] -= dt * high_force * jet_speed
            cyan_h = (0.5 + chroma_hue * tint) % 1.0
            r, g, b = colorsys.hsv_to_rgb(cyan_h, 0.95, 1.0)
            density = high_force * dt * 6.0
            self._dye[r0:r1, -5:, 0] += density * r
            self._dye[r0:r1, -5:, 1] += density * g
            self._dye[r0:r1, -5:, 2] += density * b

        # Continuous turbulence: small always-on random force plus onset
        # bump.  The always-on component keeps the clash zone alive
        # between beats (drone music was previously dead); the onset
        # bump adds a spike on transients.  Together they keep the flow
        # constantly stirred so dye traverses the grid instead of
        # settling near the injection edges.
        seed = self.params["turbulence_seed"].get()
        if seed > 0.0:
            baseline = 0.3  # always-on fraction of turbulence_seed
            onset_bump = float(frame.onset_strength)
            scale = seed * (baseline + onset_bump)
            self._u += np.random.randn(_INTERNAL_H, _INTERNAL_W) * scale
            self._v += np.random.randn(_INTERNAL_H, _INTERNAL_W) * scale

    def _chroma_hue(self, frame: AudioFrame) -> float:
        chroma = np.asarray(frame.chroma, dtype=np.float64)
        if chroma.sum() <= 1e-6:
            return 0.0
        return float(int(np.argmax(chroma))) / float(len(chroma))

    def _render_to_leds(self) -> list[tuple[int, int, int]]:
        # 2x2 max-pool downsample so the brightest cell in each block
        # wins.  The mean filter this replaced was suspected of eating
        # thin swirls on the v1 contact sheet; max-pool preserves them.
        out = self._dye.reshape(NUM_ROWS, 2, MAX_COLS, 2, 3).max(axis=(1, 3))
        brightness = self.params["brightness_gain"].get()
        out = np.clip(out * brightness, 0.0, 1.0)
        return grid_to_leds(out)
