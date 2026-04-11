"""Event Horizon — the event horizon swallows events.

A cool, dormant accretion disk surrounds a fixed 2x2 singularity. Bass beats
inject warm rings at the outer edge of the disk; each ring falls inward over
several frames, shifting the local disk hue from indigo through magenta to red
as it advects, and is extinguished the instant it crosses the photon ring.

Loudness (RMS) inflates the whole disk — quiet passages collapse the ring
radius and outer extent into a tight halo; loud passages sprawl it outward,
giving warm rings more real estate to traverse before being swallowed.

Colors are structural: indigo base everywhere, amber/red only where a warm
ring currently lives, hot blue at the photon ring core. Music modulates
motion, brightness, and the temperature field — but never the base palette.
"""

from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass

import numpy as np

from nuphy_rgb.plugin_api import (
    MAX_COLS,
    NUM_LEDS,
    NUM_ROWS,
    LED_X,
    LED_Y,
    AudioFrame,
    ExpFilter,
    VisualizerParam,
)

_KEY_X = LED_X * (MAX_COLS - 1)          # 0..15
_KEY_Y = LED_Y * (NUM_ROWS - 1)          # 0..5

_DEFAULT_DT = 1.0 / 30.0
_MAX_RINGS = 6

# Hue trajectory for the temperature field.
# warmth=0 -> COOL_HUE (indigo), warmth=1 -> COOL_HUE + HUE_SPAN (wraps to red).
# The span passes through violet -> magenta -> red-orange on the short path.
_COOL_HUE = 0.68
_HUE_SPAN = 0.34   # 0.68 -> 1.02 (== 0.02)
_INNER_HUE = 0.58  # photon-ring core stays hot blue


@dataclass
class _InfallRing:
    radius: float      # current radius in key-units
    intensity: float   # [0..1] warmth contribution


class EventHorizon:
    """Event horizon that swallows warm bass events falling through its disk."""

    name = "Event Horizon"

    def __init__(self) -> None:
        # Singularity drift (in key-units)
        self._sx_filter = ExpFilter(alpha_rise=0.3, alpha_decay=0.08)
        self._sy_filter = ExpFilter(alpha_rise=0.3, alpha_decay=0.08)

        self._phase = 0.0
        self._disk_rotation = 0.0
        self._collapse_intensity = 0.0

        self._brightness_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)
        self._spin_energy = ExpFilter(alpha_rise=0.4, alpha_decay=0.04)
        # Slow envelope — the disk inflates with sustained loudness, not per-beat noise.
        self._breath_energy = ExpFilter(alpha_rise=0.15, alpha_decay=0.03)

        self._infall_rings: list[_InfallRing] = []
        self._last_ts: float | None = None

        self.params: dict[str, VisualizerParam] = {
            "hole_half_w": VisualizerParam(
                value=1.0, default=1.0, min=0.5, max=2.0,
                description="Horizontal half-width of the event horizon (key-units)",
            ),
            "hole_half_h": VisualizerParam(
                value=1.0, default=1.0, min=0.5, max=2.0,
                description="Vertical half-height of the event horizon (key-units)",
            ),
            "ring_radius": VisualizerParam(
                value=2.3, default=2.3, min=1.5, max=4.0,
                description="Photon-ring base radius (key-units)",
            ),
            "ring_width": VisualizerParam(
                value=0.9, default=0.9, min=0.3, max=2.0,
                description="Gaussian sigma of the photon ring (key-units)",
            ),
            "disk_extent": VisualizerParam(
                value=5.0, default=5.0, min=3.0, max=7.0,
                description="Base outer radius of the disk fall-off (key-units)",
            ),
            "disk_breath": VisualizerParam(
                value=0.55, default=0.55, min=0.0, max=0.9,
                description="How much loudness inflates the accretion disk",
            ),
            "drift_speed": VisualizerParam(
                value=1.0, default=1.0, min=0.2, max=3.0,
                description="Singularity drift speed multiplier",
            ),
            "rotation_speed": VisualizerParam(
                value=0.12, default=0.12, min=0.0, max=0.4,
                description="Base disk rotation (rad/frame)",
            ),
            "num_arms": VisualizerParam(
                value=3.0, default=3.0, min=2.0, max=5.0,
                description="Number of spiral arms (integer, 2-5)",
            ),
            "arm_sharpness": VisualizerParam(
                value=8.0, default=8.0, min=2.0, max=16.0,
                description="Angular narrowness of spiral arms",
            ),
            "spiral_pitch": VisualizerParam(
                value=0.6, default=0.6, min=0.0, max=1.5,
                description="How much arm angle winds with radius",
            ),
            "infall_speed": VisualizerParam(
                value=0.08, default=0.08, min=0.02, max=0.25,
                description="How fast warm rings fall inward (key-units/frame)",
            ),
            "warmth_width": VisualizerParam(
                value=0.9, default=0.9, min=0.3, max=2.0,
                description="Radial thickness of each warm infalling ring",
            ),
            "warmth_gain": VisualizerParam(
                value=1.2, default=1.2, min=0.0, max=2.5,
                description="How strongly bass events inject warmth",
            ),
            "brightness_gain": VisualizerParam(
                value=1.0, default=1.0, min=0.4, max=2.5,
                description="Global brightness scale",
            ),
        }

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        p = {k: v.value for k, v in self.params.items()}

        if self._last_ts is None:
            dt = _DEFAULT_DT
        else:
            dt = max(1e-3, min(0.1, frame.timestamp - self._last_ts))
        self._last_ts = frame.timestamp
        frame_scale = dt / _DEFAULT_DT

        # === Singularity drift ===
        self._phase += (0.018 + frame.mids * 0.04) * p["drift_speed"] * frame_scale
        cx = (MAX_COLS - 1) * 0.5
        cy = (NUM_ROWS - 1) * 0.5
        amp_x = (MAX_COLS - 1) * 0.32
        amp_y = (NUM_ROWS - 1) * 0.30
        raw_x = cx + amp_x * math.sin(self._phase)
        raw_y = cy + amp_y * math.cos(self._phase * 0.618)
        sx = self._sx_filter.update(raw_x)
        sy = self._sy_filter.update(raw_y)

        # === Loudness -> accretion disk breathes ===
        breath = self._breath_energy.update(min(1.0, frame.raw_rms * 3.0))
        disk_scale = 1.0 + p["disk_breath"] * (2.0 * breath - 1.0)
        # Ring must stay outside the void or the whole disk disappears into the hole.
        min_ring = max(p["hole_half_w"], p["hole_half_h"]) + 0.4
        ring_radius_eff = max(min_ring, p["ring_radius"] * disk_scale)
        disk_extent_eff = max(ring_radius_eff + 0.5, p["disk_extent"] * disk_scale)

        # === Disk rotation gated by audio energy ===
        spin = self._spin_energy.update(min(1.0, frame.raw_rms * 4.0))
        self._disk_rotation += (
            p["rotation_speed"] * spin + frame.bass * 0.35
        ) * frame_scale

        # === Infall ring field: bass events fall inward and are swallowed ===
        self._update_infall_rings(
            frame, frame_scale, ring_radius_eff, disk_extent_eff, p
        )

        # === Collapse flash (luminance pulse on beat) ===
        if frame.is_beat:
            self._collapse_intensity = min(1.0, 0.9 + frame.onset_strength * 0.4)
        else:
            self._collapse_intensity *= 0.78
        collapsing = self._collapse_intensity > 0.01

        arms = float(max(2, min(5, int(round(p["num_arms"])))))

        # === Per-LED field in key-units ===
        dx = _KEY_X - sx
        dy = _KEY_Y - sy
        r = np.hypot(dx, dy)
        theta = np.arctan2(dy, dx)

        # Event horizon: fixed 2x2 void (does NOT breathe)
        hole_w = p["hole_half_w"]
        hole_h = p["hole_half_h"]
        void_mask = (np.abs(dx) < hole_w) & (np.abs(dy) < hole_h)

        # Photon ring (Gaussian annulus, follows breathing radius)
        sigma = p["ring_width"]
        ring = np.exp(-(((r - ring_radius_eff) / sigma) ** 2))

        # Disk fall-off envelope (soft outer cutoff)
        disk_env = np.exp(
            -np.clip(r - ring_radius_eff, 0.0, None)
            / max(0.1, disk_extent_eff - ring_radius_eff) * 2.5
        )
        disk_env = np.where(r > disk_extent_eff, 0.0, disk_env)

        # Spiral arms — brightness feature only, no color
        arm_phase = arms * (theta - self._disk_rotation) - p["spiral_pitch"] * r
        arm = np.clip(np.cos(arm_phase), 0.0, 1.0) ** p["arm_sharpness"]

        base_ring = ring * 0.85
        outer_glow = disk_env * 0.35
        arm_boost = disk_env * 0.7 * arm
        brightness = base_ring + outer_glow + arm_boost

        # === Warmth field: sum of gaussian contributions from live infall rings ===
        warmth = np.zeros(NUM_LEDS, dtype=np.float64)
        ww = p["warmth_width"]
        for rg in self._infall_rings:
            warmth += rg.intensity * np.exp(-((r - rg.radius) / ww) ** 2)
        # Warmth only lives on the disk — no stray glow in empty space
        warmth = np.clip(warmth * disk_env, 0.0, 1.0)

        # === Color: cool indigo base, warmth lerps hue toward red via magenta ===
        hue = (_COOL_HUE + warmth * _HUE_SPAN) % 1.0

        # Inner core (inside photon ring) stays hot blue
        inner_mask = r < ring_radius_eff - sigma * 0.3
        hue[inner_mask] = _INNER_HUE

        saturation = np.full(NUM_LEDS, 0.95, dtype=np.float64)
        saturation[inner_mask] = 0.3 + (1.0 - ring[inner_mask]) * 0.45
        saturation = saturation - arm * 0.15

        # Warm rings get a brightness boost so the wave is visible, not just tinted
        brightness = brightness + warmth * 0.4

        # Collapse pulse (luminance only)
        if collapsing:
            ci = self._collapse_intensity
            pulse = ring * ci * 0.8 + disk_env * ci * 0.3
            brightness = brightness + pulse

        # Void always swallows — apply last
        brightness = np.where(void_mask, 0.0, brightness)

        # Global brightness + silence gate
        global_b = self._brightness_filter.update(0.30 + frame.rms * 0.75)
        brightness = np.clip(brightness * global_b * p["brightness_gain"], 0.0, 1.0)
        saturation = np.clip(saturation, 0.0, 1.0)
        hue = hue % 1.0

        result: list[tuple[int, int, int]] = []
        for i in range(NUM_LEDS):
            rf, gf, bf = colorsys.hsv_to_rgb(
                float(hue[i]), float(saturation[i]), float(brightness[i])
            )
            result.append((int(rf * 255), int(gf * 255), int(bf * 255)))
        return result

    def _update_infall_rings(
        self,
        frame: AudioFrame,
        frame_scale: float,
        ring_radius_eff: float,
        disk_extent_eff: float,
        p: dict[str, float],
    ) -> None:
        # Advect all live rings inward. Bass accelerates infall slightly so loud
        # passages feel heavier / faster.
        infall = p["infall_speed"] * (1.0 + float(frame.bass) * 0.8)
        decay = 0.97 ** frame_scale
        for rg in self._infall_rings:
            rg.radius -= infall * frame_scale
            rg.intensity *= decay

        # Extinguish anything that has crossed the photon ring ("swallowed"),
        # or has faded below visibility threshold.
        self._infall_rings = [
            rg for rg in self._infall_rings
            if rg.radius > ring_radius_eff - 0.2 and rg.intensity > 0.02
        ]

        # Spawn new rings on bass beats, and top up on sustained low-end so
        # steady bass lines still feel warm even without discrete onsets.
        bass_now = float(frame.bass)
        gain = p["warmth_gain"]
        spawn_r = disk_extent_eff * 0.95

        if frame.is_beat and bass_now > 0.15:
            intensity = min(1.0, (bass_now * 0.8 + float(frame.onset_strength) * 0.3) * gain)
            self._infall_rings.append(_InfallRing(radius=spawn_r, intensity=intensity))
        elif bass_now > 0.45 and len(self._infall_rings) < 2:
            self._infall_rings.append(
                _InfallRing(radius=spawn_r, intensity=min(1.0, bass_now * 0.5 * gain))
            )

        if len(self._infall_rings) > _MAX_RINGS:
            self._infall_rings = self._infall_rings[-_MAX_RINGS:]
