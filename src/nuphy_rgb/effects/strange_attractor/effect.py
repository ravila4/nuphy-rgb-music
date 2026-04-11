"""Strange Attractor visualizer: 12 particles orbiting a Lorenz attractor.

Particles deposit glowing trails on nearby LEDs, with trail brightness and
hue updated each frame based on audio energy.
"""

import colorsys

import numpy as np

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.grid import LED_X, LED_Y, NUM_LEDS
from nuphy_rgb.visualizer_params import VisualizerParam

_NUM_PARTICLES = 12
_TRAIL_RADIUS = 0.15


def _lorenz_step(
    particles: np.ndarray,
    sigma: float,
    rho: float,
    beta: float,
    dt: float,
    substeps: int,
) -> np.ndarray:
    """Advance all particles along the Lorenz attractor using vectorized Euler integration.

    Args:
        particles: (N, 3) array of particle positions [x, y, z].
        sigma, rho, beta: Lorenz parameters.
        dt: Time step per substep.
        substeps: Number of Euler steps to take.

    Returns:
        Updated (N, 3) array, clamped to [-100, 100].
    """
    p = particles.copy()
    for _ in range(substeps):
        x, y, z = p[:, 0], p[:, 1], p[:, 2]
        dx = sigma * (y - x)
        dy = x * (rho - z) - y
        dz = x * y - beta * z
        p += np.column_stack([dx, dy, dz]) * dt
    return np.clip(p, -100.0, 100.0)


def _project(particles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project 3-D Lorenz particle positions to normalized 2-D grid coordinates.

    Uses the x-axis for horizontal and z-axis for vertical.
    Typical Lorenz attractor range: x in [-25, 25], z in [0, 55].

    Args:
        particles: (N, 3) array of particle positions.

    Returns:
        (grid_x, grid_y): each (N,) float64 array, clamped to [0, 1].
    """
    x = particles[:, 0]
    z = particles[:, 2]
    grid_x = np.clip((x + 25.0) / 50.0, 0.0, 1.0)
    grid_y = np.clip(z / 55.0, 0.0, 1.0)
    return grid_x, grid_y


class StrangeAttractor:
    """Music-reactive Lorenz attractor with per-LED trail rendering.

    12 particles orbit the attractor; audio energy modulates the attractor
    parameters, causing the orbits to stretch and contract with the music.
    """

    name = "Strange Attractor"

    def __init__(self, seed: int | None = None) -> None:
        self._rng = np.random.default_rng(seed)

        # Particle state: (12, 3)
        self._particles = np.column_stack([
            self._rng.uniform(-5.0, 5.0, _NUM_PARTICLES),
            self._rng.uniform(-5.0, 5.0, _NUM_PARTICLES),
            self._rng.uniform(15.0, 35.0, _NUM_PARTICLES),
        ])

        # Trail state per LED
        self._trails = np.zeros(NUM_LEDS, dtype=np.float64)
        self._trail_hue = np.zeros(NUM_LEDS, dtype=np.float64)

        # Per-particle hue: spread evenly across the color wheel
        self._particle_hues = np.linspace(0.0, 1.0, _NUM_PARTICLES, endpoint=False)

        self.params: dict[str, VisualizerParam] = {
            "sigma_bass_boost": VisualizerParam(
                value=8.0, default=8.0, min=0.0, max=20.0,
                description="Bass → Lorenz σ modulation depth (stretches the butterfly wings)",
            ),
            "rho_mids_boost": VisualizerParam(
                value=16.0, default=16.0, min=0.0, max=30.0,
                description="Mids → Lorenz ρ modulation depth (drives chaos regime; classic chaos at ρ≈28)",
            ),
            "trail_decay": VisualizerParam(
                value=0.82, default=0.82, min=0.70, max=0.95,
                description="Base trail decay per frame (higher = longer comet tails)",
            ),
            "beat_kick_force": VisualizerParam(
                value=3.0, default=3.0, min=0.0, max=8.0,
                description="Beat impulse displacement on particles (0 = no kick, high = chaotic jolts)",
            ),
        }

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        """Render one frame of the Strange Attractor effect.

        Args:
            frame: Current audio analysis snapshot.

        Returns:
            List of 84 (R, G, B) tuples with values in [0, 255].
        """
        bass = frame.bass
        mids = frame.mids
        highs = frame.highs
        rms = frame.rms

        # --- Lorenz parameter modulation ---
        sigma = 8.0 + bass * self.params["sigma_bass_boost"].get()
        rho = 20.0 + mids * self.params["rho_mids_boost"].get()
        beta = 2.0 + highs * 2.0
        dt = 0.003 + highs * 0.003 + frame.spectral_flux * 0.003

        self._particles = _lorenz_step(
            self._particles, sigma, rho, beta, dt, substeps=3
        )

        # --- Beat kick (onset-scaled) ---
        if frame.is_beat:
            base_kick = self.params["beat_kick_force"].get()
            kick = base_kick + min(frame.onset_strength * base_kick, base_kick)
            self._particles += self._rng.choice([-kick, kick], size=(1, 3))
            np.clip(self._particles, -100.0, 100.0, out=self._particles)

        # --- Mid-beat hue rotation ---
        if frame.mid_beat:
            self._particle_hues = (self._particle_hues + 0.08) % 1.0

        # --- Project to 2D grid ---
        gx, gy = _project(self._particles)  # each shape (12,)

        # --- Trail deposit via Gaussian falloff ---
        # Distances: (12, 1) vs (1, 84) -> (12, 84)
        dx = gx[:, np.newaxis] - LED_X[np.newaxis, :]
        dy = gy[:, np.newaxis] - LED_Y[np.newaxis, :]
        dist2 = dx * dx + dy * dy
        deposit = np.exp(-dist2 / (_TRAIL_RADIUS ** 2))  # (12, 84)

        # Hue contribution: circular mean weighted by deposit
        # particle_hues is (12,), expand to (12, 1) for broadcasting
        hue_angles = self._particle_hues[:, np.newaxis] * (2.0 * np.pi)  # (12, 1)
        sin_w = np.sum(np.sin(hue_angles) * deposit, axis=0)  # (84,)
        cos_w = np.sum(np.cos(hue_angles) * deposit, axis=0)  # (84,)
        new_hue = (np.arctan2(sin_w, cos_w) / (2.0 * np.pi)) % 1.0  # (84,)

        # Lerp trail hue via shortest-arc delta (handles 0/1 wrap correctly)
        delta = ((new_hue - self._trail_hue + 0.5) % 1.0) - 0.5
        self._trail_hue = (self._trail_hue + 0.3 * delta) % 1.0

        # Max deposit across particles for each LED
        max_deposit = np.max(deposit, axis=0)  # (84,)
        self._trails = np.maximum(self._trails, max_deposit)

        # --- Trail decay ---
        self._trails *= self.params["trail_decay"].get() + rms * 0.12

        # --- Render to RGB ---
        colors: list[tuple[int, int, int]] = []
        for i in range(NUM_LEDS):
            v = float(self._trails[i])
            s = 0.85 + 0.15 * v
            h = float(self._trail_hue[i])
            r_f, g_f, b_f = colorsys.hsv_to_rgb(h, s, v)
            colors.append((int(r_f * 255), int(g_f * 255), int(b_f * 255)))

        return colors
