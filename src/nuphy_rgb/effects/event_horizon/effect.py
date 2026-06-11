"""Event Horizon — the event horizon swallows events.

A cool, dormant accretion disk surrounds a fixed 2x2 singularity. Bass beats
inject warm rings at the outer edge of the disk; each ring falls inward with
gravitational acceleration — languid at the rim, fast at the horizon —
thinning and brightening tidally as it goes, shifting the local disk hue from
indigo through magenta to red. Crossing the photon ring detonates the ring
into an accretion flare: every flash on the photon ring is a bass beat
arriving ~1 second late.

Loudness (RMS) inflates the whole disk — quiet passages collapse the ring
radius and outer extent into a tight halo; loud passages sprawl it outward,
giving warm rings more real estate to traverse before being swallowed.
While the disk spins, Doppler beaming brightens the approaching side.

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

# Radial width of the smoothstep fade at the disk's outer rim. Warmth is
# full-strength everywhere inside (disk_extent - _WARM_FADE); rings spawn at
# that full-strength edge so they are visible from frame one.
_WARM_FADE = 0.8

# Per-frame decay of the accretion flare triggered by swallowed rings.
_FLARE_DECAY = 0.8

# Hue trajectory for the temperature field.
# warmth=0 -> COOL_HUE (indigo), warmth=1 -> COOL_HUE + HUE_SPAN (wraps to red).
# The span passes through violet -> magenta -> red-orange on the short path.
_COOL_HUE = 0.68
_HUE_SPAN = 0.34   # 0.68 -> 1.02 (== 0.02)
_INNER_HUE = 0.58  # photon-ring core stays hot blue


def _warm_envelope(r: np.ndarray, disk_extent: float) -> np.ndarray:
    """Mask for the warmth field: 1.0 inside the disk, smoothstep to 0 at the rim.

    Unlike the exponential disk envelope (a brightness feature), this only
    exists to keep warmth from glowing past the disk boundary — it must not
    attenuate rings while they traverse the disk.
    """
    t = np.clip((disk_extent - r) / _WARM_FADE, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _beaming_field(
    theta: np.ndarray, rotation: float, spin: float, strength: float
) -> np.ndarray:
    """Relativistic-beaming brightness asymmetry: the approaching side glows.

    A multiplier in [1 - strength*spin, 1 + strength*spin] peaking at the
    disk's leading angle. spin=0 (silence) gives a symmetric halo; strength
    is capped at 0.7 by the param range so the receding side never blacks out.
    """
    return 1.0 + strength * spin * np.cos(theta - rotation)


def _infall_velocity(
    radius: float, spawn_radius: float, base_speed: float, accel: float
) -> float:
    """Keplerian-flavored infall: speed grows as (spawn/r)^accel toward the hole.

    accel=0 recovers constant-speed infall; 0.5 matches free-fall scaling.
    """
    return base_speed * (spawn_radius / max(radius, 0.1)) ** accel


def _tidal_profile(
    radius: float, spawn_radius: float, base_width: float, tidal_min: float
) -> tuple[float, float]:
    """Tidal stretching of a falling ring: (effective width, intensity boost).

    The ring thins proportionally to its radius and brightens to conserve
    flux (width * boost == base_width), so it arrives at the horizon thin
    and hot. tidal_min floors the thinning so a ring never drops below
    visibility at LED resolution.
    """
    frac = max(radius / spawn_radius, tidal_min)
    return base_width * frac, 1.0 / frac


@dataclass
class _InfallRing:
    radius: float        # current radius in key-units
    intensity: float     # [0..1] warmth contribution
    spawn_radius: float  # radius at spawn; anchors velocity + tidal scaling


class EventHorizon:
    """Event horizon that swallows warm bass events falling through its disk."""

    name = "Event Horizon"

    def __init__(self) -> None:
        # Singularity drift (in key-units)
        self._sx_filter = ExpFilter(alpha_rise=0.3, alpha_decay=0.08)
        self._sy_filter = ExpFilter(alpha_rise=0.3, alpha_decay=0.08)

        self._phase = 0.0
        self._disk_rotation = 0.0
        self._flare = 0.0

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
                value=0.05, default=0.05, min=0.02, max=0.25,
                description="Infall speed at the spawn radius (key-units/frame)",
            ),
            "infall_accel": VisualizerParam(
                value=0.5, default=0.5, min=0.0, max=1.0,
                description="Gravitational acceleration exponent (0=constant, 0.5=Keplerian)",
            ),
            "tidal_min": VisualizerParam(
                value=0.35, default=0.35, min=0.2, max=0.8,
                description="Minimum tidal width fraction (floor for ring thinning)",
            ),
            "warmth_width": VisualizerParam(
                value=0.9, default=0.9, min=0.3, max=2.0,
                description="Radial thickness of each warm infalling ring",
            ),
            "warmth_gain": VisualizerParam(
                value=1.2, default=1.2, min=0.0, max=2.5,
                description="How strongly bass events inject warmth",
            ),
            "flare_gain": VisualizerParam(
                value=1.0, default=1.0, min=0.0, max=2.0,
                description="Photon-ring flash strength when a ring is swallowed",
            ),
            "beam_strength": VisualizerParam(
                value=0.45, default=0.45, min=0.0, max=0.7,
                description="Doppler beaming asymmetry on the spinning ring/arms",
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

        # Doppler beaming: ring + arms brighten on the approaching side while
        # the disk spins. The outer glow stays symmetric so the disk's overall
        # silhouette doesn't lurch.
        beaming = _beaming_field(
            theta, self._disk_rotation, spin, p["beam_strength"]
        )

        base_ring = ring * 0.85
        outer_glow = disk_env * 0.35
        arm_boost = disk_env * 0.7 * arm
        brightness = (base_ring + arm_boost) * beaming + outer_glow

        # === Warmth field: sum of gaussian contributions from live infall rings ===
        warmth = np.zeros(NUM_LEDS, dtype=np.float64)
        for rg in self._infall_rings:
            ww, boost = _tidal_profile(
                rg.radius, rg.spawn_radius, p["warmth_width"], p["tidal_min"]
            )
            warmth += rg.intensity * boost * np.exp(-((r - rg.radius) / ww) ** 2)
        # Warmth only lives on the disk — no stray glow in empty space.
        # Full strength inside; only the outer rim fades (NOT the exponential
        # disk envelope, which would hide rings for most of their infall).
        warmth = np.clip(warmth * _warm_envelope(r, disk_extent_eff), 0.0, 1.0)

        # === Color: cool indigo base, warmth lerps hue toward red via magenta ===
        hue = (_COOL_HUE + warmth * _HUE_SPAN) % 1.0

        # Inner core (inside photon ring) stays hot blue
        inner_mask = r < ring_radius_eff - sigma * 0.3
        hue[inner_mask] = _INNER_HUE

        saturation = np.full(NUM_LEDS, 0.95, dtype=np.float64)
        saturation[inner_mask] = 0.3 + (1.0 - ring[inner_mask]) * 0.45
        saturation = saturation - arm * 0.15

        # Warm rings get a brightness boost so the wave is visible, not just
        # tinted. Out at the rim the disk glow is near zero, so this term is
        # the only thing lighting a freshly spawned ring.
        brightness = brightness + warmth * 0.55

        # Accretion flare: swallowed rings flash the photon ring (luminance only)
        if self._flare > 0.01:
            brightness = brightness + ring * self._flare * 0.8

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
        # Advect all live rings inward with gravitational acceleration: slow
        # and languid at the rim, fast at the horizon. Bass adds extra pull so
        # loud passages feel heavier. No intensity decay — the tidal profile
        # at render time gives rings their brightness arc instead.
        base_speed = p["infall_speed"] * (1.0 + float(frame.bass) * 0.8)
        for rg in self._infall_rings:
            rg.radius -= _infall_velocity(
                rg.radius, rg.spawn_radius, base_speed, p["infall_accel"]
            ) * frame_scale

        # Partition the culls: rings that crossed the photon ring are
        # "swallowed" and feed the accretion flare; rings below visibility
        # just fade out silently.
        survivors: list[_InfallRing] = []
        swallowed = 0.0
        for rg in self._infall_rings:
            if rg.radius <= ring_radius_eff - 0.2:
                swallowed += rg.intensity
            elif rg.intensity > 0.02:
                survivors.append(rg)
        self._infall_rings = survivors

        self._flare = min(
            1.0,
            self._flare * _FLARE_DECAY**frame_scale + swallowed * p["flare_gain"],
        )

        # Spawn new rings on bass beats, and top up on sustained low-end so
        # steady bass lines still feel warm even without discrete onsets.
        bass_now = float(frame.bass)
        gain = p["warmth_gain"]
        # Spawn at the warm envelope's full-strength edge, never inside the
        # photon ring (possible when the disk has collapsed to its minimum).
        spawn_r = max(ring_radius_eff + 0.4, disk_extent_eff - _WARM_FADE)

        if frame.is_beat and bass_now > 0.15:
            intensity = min(1.0, (bass_now * 0.8 + float(frame.onset_strength) * 0.3) * gain)
            self._infall_rings.append(
                _InfallRing(radius=spawn_r, intensity=intensity, spawn_radius=spawn_r)
            )
        elif bass_now > 0.45 and len(self._infall_rings) < 2:
            self._infall_rings.append(
                _InfallRing(
                    radius=spawn_r,
                    intensity=min(1.0, bass_now * 0.5 * gain),
                    spawn_radius=spawn_r,
                )
            )

        if len(self._infall_rings) > _MAX_RINGS:
            self._infall_rings = self._infall_rings[-_MAX_RINGS:]
