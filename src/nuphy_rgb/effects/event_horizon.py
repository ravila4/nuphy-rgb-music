"""Event Horizon visualizer — wandering black-hole singularity with accretion disk.

The singularity wanders in a Lissajous-like path smoothed by ExpFilters.
On beats, a gravitational collapse flash fires and particles stream inward
from the outer edge of the disk.
"""

import colorsys
import math
from dataclasses import dataclass, field

import numpy as np

from nuphy_rgb.audio import AudioFrame, ExpFilter
from nuphy_rgb.effects.grid import LED_X, LED_Y, NUM_LEDS
from nuphy_rgb.visualizer import freq_to_hue

# ---------------------------------------------------------------------------
# Internal state helpers
# ---------------------------------------------------------------------------

_MAX_PARTICLES = 12


@dataclass
class _Particle:
    x: float
    y: float
    life: int   # frames remaining
    hue: float


# ---------------------------------------------------------------------------
# Visualizer
# ---------------------------------------------------------------------------


class EventHorizon:
    """Wandering black-hole singularity with accretion disk.

    Parameters
    ----------
    num_leds:
        Number of LEDs (default 84).
    seed:
        RNG seed for deterministic output in tests.
    """

    name = "Event Horizon"

    def __init__(self, num_leds: int = NUM_LEDS, seed: int = 42) -> None:
        self._num_leds = num_leds
        self._rng = np.random.default_rng(seed)

        # Singularity position filters
        self._sx_filter = ExpFilter(alpha_rise=0.3, alpha_decay=0.08)
        self._sy_filter = ExpFilter(alpha_rise=0.3, alpha_decay=0.08)

        # Phase accumulator for the Lissajous path
        self._phase: float = 0.0

        # Accretion disk rotation angle (radians)
        self._disk_rotation: float = 0.0

        # Gravitational collapse state
        self._collapse_frames: int = 0
        self._collapse_intensity: float = 0.0

        # Spiral arm boost on high-beat (3-frame counter)
        self._spiral_frames: int = 0

        # Particles
        self._particles: list[_Particle] = []

        # Overall brightness smoothing (squared RMS)
        self._brightness_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)

        # Pre-cache LED positions as numpy arrays (sliced to num_leds)
        self._led_x = LED_X[:num_leds]
        self._led_y = LED_Y[:num_leds]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        """Render one frame from an AudioFrame, returning ``num_leds`` RGB tuples."""

        # ---- 1. Advance singularity position --------------------------------
        base_rate = 0.018
        speed = 0.04
        self._phase += base_rate + frame.mids * speed

        raw_x = 0.5 + 0.4 * math.sin(self._phase)
        raw_y = 0.5 + 0.35 * math.cos(self._phase * 0.618)
        sx = self._sx_filter.update(raw_x)
        sy = self._sy_filter.update(raw_y)

        # ---- 2. Advance disk rotation ---------------------------------------
        base_rot = 0.05
        rotation_factor = 0.3
        self._disk_rotation += base_rot + frame.bass * rotation_factor

        # ---- 3. Collapse trigger / decay ------------------------------------
        if frame.is_beat:
            self._collapse_frames = 12
            self._collapse_intensity = 1.0 + min(frame.onset_strength * 0.5, 0.5)
        else:
            if self._collapse_frames > 0:
                self._collapse_frames -= 1
            self._collapse_intensity *= 0.75

        collapsing = self._collapse_intensity > 0.01

        # ---- 4. High-beat spiral arm boost -----------------------------------
        if frame.high_beat:
            self._spiral_frames = 3
        elif self._spiral_frames > 0:
            self._spiral_frames -= 1

        # ---- 5. Particles ---------------------------------------------------
        if frame.is_beat:
            self._spawn_particles(sx, sy, frame.dominant_freq)
        self._update_particles(sx, sy, frame.spectral_flux)

        # ---- 6. Per-LED vectorised computation ------------------------------
        dx = self._led_x - sx
        dy = self._led_y - sy
        dist = np.hypot(dx, dy)           # raw distance
        norm_dist = dist / 0.6            # normalise; 0.6 ~ half diagonal
        angle = np.arctan2(dy, dx)        # [-pi, pi]

        # ---- 7. Normal-mode brightness --------------------------------------
        # Glowing ring at norm_dist ~ 0.3
        ring_b = np.exp(-((norm_dist - 0.3) ** 2) * 30.0)
        # Spiral arm modulation (extra arms on high-beat)
        spiral_arms = 2.0 + 4.0 * (self._spiral_frames > 0)
        spiral = 0.5 + 0.5 * np.sin(
            spiral_arms * angle - self._disk_rotation + norm_dist * 6.0
        )
        brightness = ring_b * spiral
        # Void centre: LEDs very close to singularity are dark
        brightness = np.where(norm_dist < 0.08, 0.0, brightness)

        # ---- 8. Distance-based hue -----------------------------------------
        effective_freq = max(frame.dominant_freq, 80.0)
        freq_shift = freq_to_hue(effective_freq, min_freq=80.0, max_freq=4000.0)
        # violet inner (<0.25), blue-white ring, amber outer
        inner_mask = norm_dist < 0.25
        ring_mask = (norm_dist >= 0.25) & (norm_dist < 0.55)
        outer_mask = norm_dist >= 0.55

        hue = np.zeros(self._num_leds, dtype=np.float64)
        hue[inner_mask] = (0.75 + freq_shift * 0.1) % 1.0   # violet-ish
        hue[ring_mask] = (0.58 + freq_shift * 0.15) % 1.0   # blue-white
        hue[outer_mask] = (0.08 + freq_shift * 0.2) % 1.0   # amber-ish

        saturation = np.ones(self._num_leds, dtype=np.float64)
        # Blue-white ring: lower saturation for whitish glow
        saturation[ring_mask] = 0.4 + ring_b[ring_mask] * 0.3

        # ---- 9. Collapse override -------------------------------------------
        if collapsing:
            ci = self._collapse_intensity
            collapse_b = np.exp(-norm_dist * 4.0) * ci
            brightness = brightness * (1.0 - ci) + collapse_b * ci
            hue = hue * (1.0 - ci) + 0.0 * ci   # shift toward red (hue=0)
            saturation = saturation * (1.0 - ci) + 1.0 * ci

        # ---- 10. Particle overlay -------------------------------------------
        for p in self._particles:
            pdx = self._led_x - p.x
            pdy = self._led_y - p.y
            pdist = np.hypot(pdx, pdy)
            particle_b = np.exp(-(pdist ** 2) * 80.0) * (p.life / 20.0)
            brightness = brightness + particle_b
            # Blend hue toward particle hue proportional to contribution
            blend = np.clip(particle_b * 5.0, 0.0, 1.0)
            hue = hue * (1.0 - blend) + p.hue * blend

        # ---- 11. Global brightness scale ------------------------------------
        global_brightness = self._brightness_filter.update(frame.rms ** 2)
        # Keep a baseline so the effect is visible even in silence
        global_brightness = max(global_brightness, 0.05)
        brightness = np.clip(brightness * global_brightness, 0.0, 1.0)
        saturation = np.clip(saturation, 0.0, 1.0)
        hue = np.clip(hue, 0.0, 1.0)

        # ---- 12. HSV -> RGB -------------------------------------------------
        result: list[tuple[int, int, int]] = []
        for i in range(self._num_leds):
            r_f, g_f, b_f = colorsys.hsv_to_rgb(
                float(hue[i]), float(saturation[i]), float(brightness[i])
            )
            result.append((int(r_f * 255), int(g_f * 255), int(b_f * 255)))
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _spawn_particles(self, sx: float, sy: float, dominant_freq: float) -> None:
        """Spawn 2-3 particles at the outer edge of the accretion disk."""
        n = int(self._rng.integers(2, 4))  # 2 or 3
        for _ in range(n):
            if len(self._particles) >= _MAX_PARTICLES:
                break
            # Random angle, spawn at radius ~0.35 (outer edge of disk)
            angle = float(self._rng.uniform(0.0, 2 * math.pi))
            radius = float(self._rng.uniform(0.25, 0.45))
            px = sx + radius * math.cos(angle)
            py = sy + radius * math.sin(angle)
            p_hue = (freq_to_hue(dominant_freq, 80.0, 4000.0) + 0.05) % 1.0
            life = int(self._rng.integers(15, 25))
            self._particles.append(_Particle(x=px, y=py, life=life, hue=p_hue))

    def _update_particles(
        self, sx: float, sy: float, spectral_flux: float
    ) -> None:
        """Pull each particle toward (sx, sy) and decrement life."""
        pull = 0.04
        turbulence = spectral_flux * 0.03
        live: list[_Particle] = []
        for p in self._particles:
            p.life -= 1
            if p.life <= 0:
                continue
            # Pull toward singularity
            p.x += (sx - p.x) * pull
            p.y += (sy - p.y) * pull
            # Spectral-flux turbulence
            if turbulence > 0:
                p.x += float(self._rng.uniform(-turbulence, turbulence))
                p.y += float(self._rng.uniform(-turbulence, turbulence))
            live.append(p)
        self._particles = live
