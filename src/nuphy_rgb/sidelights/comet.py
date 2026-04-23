"""Comet: beat-spawned pulses rise along the sidelight, leaving decaying trails.

First sidelight with temporal memory. Each beat launches a short-lived
"comet" at the bottom of the 6-LED strip; the comet rises at a speed that
scales with bass energy, dims exponentially, and fades off the top. Its
color is frozen at spawn from ``freq_to_hue(dominant_freq)`` so a fleet of
comets in flight reads as a chromatic history of recent beats.

Audio mapping:
    is_beat       -> spawn new pulse at bottom, brightness=1.0
    bass          -> rise speed (additive, smoothed via ExpFilter)
    dominant_freq -> hue frozen at spawn
    raw_rms       -> output gate (silence fades strip to black)

Hard cap of 12 live pulses per side; no NumPy needed at this scale.
"""

from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass

from nuphy_rgb.audio import AudioFrame, ExpFilter
from nuphy_rgb.hid_utils import SIDE_LED_COUNT
from nuphy_rgb.sidelights.visualizer import (
    LEDS_PER_SIDE,
    LEFT_BOTTOM_UP,
    RIGHT_BOTTOM_UP,
)
from nuphy_rgb.visualizer import freq_to_hue
from nuphy_rgb.visualizer_params import VisualizerParam

_DEFAULT_DT = 1.0 / 30.0
_MAX_DT = 0.25
_MAX_PULSES = 12
_MIN_BRIGHTNESS = 0.01
_SPAWN_POSITION = -0.3


@dataclass
class _Pulse:
    position: float  # 0 = bottom LED, LEDS_PER_SIDE = off-top
    hue: float       # [0, 1]
    brightness: float  # [0, 1]


class Comet:
    """Feedback-trail sidelight: beats spawn rising Gaussian pulses."""

    name = "Comet"

    def __init__(self) -> None:
        self._pulses: list[_Pulse] = []
        self._last_t: float | None = None
        self._speed_filter = ExpFilter(alpha_rise=0.5, alpha_decay=0.1)
        self.params: dict[str, VisualizerParam] = {
            "base_speed": VisualizerParam(
                value=1.5, default=1.5, min=0.2, max=6.0,
                description="Baseline rise speed (LEDs/sec) at zero bass",
            ),
            "bass_speed": VisualizerParam(
                value=5.0, default=5.0, min=0.0, max=12.0,
                description="Additional rise speed per unit of bass",
            ),
            "trail_sigma": VisualizerParam(
                value=0.9, default=0.9, min=0.3, max=2.5,
                description="Gaussian pulse width in LEDs",
            ),
            "decay_tau": VisualizerParam(
                value=0.6, default=0.6, min=0.1, max=3.0,
                description="Brightness e-fold time in seconds",
            ),
            "brightness": VisualizerParam(
                value=0.9, default=0.9, min=0.0, max=1.0,
                description="Master output multiplier",
            ),
            "silence_gate": VisualizerParam(
                value=0.02, default=0.02, min=0.001, max=0.2,
                description="raw_rms level at which output reaches full strength",
            ),
        }

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._advance_clock(frame.timestamp)
        speed = self._speed_filter.update(
            self.params["base_speed"].get()
            + self.params["bass_speed"].get() * frame.bass
        )
        decay = math.exp(-dt / max(self.params["decay_tau"].get(), 1e-3))

        self._advance_pulses(speed, dt, decay)
        if frame.is_beat:
            self._spawn_pulse(frame.dominant_freq)

        side_rgb = self._render_side()
        gate_level = self._silence_level(frame.raw_rms)
        bright = self.params["brightness"].get() * gate_level

        colors: list[tuple[int, int, int]] = [(0, 0, 0)] * SIDE_LED_COUNT
        for i in range(LEDS_PER_SIDE):
            r, g, b = side_rgb[i]
            scaled = (
                min(255, max(0, int(r * 255 * bright))),
                min(255, max(0, int(g * 255 * bright))),
                min(255, max(0, int(b * 255 * bright))),
            )
            colors[LEFT_BOTTOM_UP[i]] = scaled
            colors[RIGHT_BOTTOM_UP[i]] = scaled
        return colors

    def _advance_clock(self, now: float) -> float:
        if self._last_t is None:
            self._last_t = now
            return _DEFAULT_DT
        dt = now - self._last_t
        self._last_t = now
        if dt <= 0.0:
            return _DEFAULT_DT
        return min(dt, _MAX_DT)

    def _advance_pulses(self, speed: float, dt: float, decay: float) -> None:
        survivors: list[_Pulse] = []
        ceiling = LEDS_PER_SIDE + 1.5
        for p in self._pulses:
            p.position += speed * dt
            p.brightness *= decay
            if p.brightness > _MIN_BRIGHTNESS and p.position < ceiling:
                survivors.append(p)
        self._pulses = survivors

    def _spawn_pulse(self, dominant_freq: float) -> None:
        if len(self._pulses) >= _MAX_PULSES:
            return
        self._pulses.append(
            _Pulse(
                position=_SPAWN_POSITION,
                hue=freq_to_hue(dominant_freq),
                brightness=1.0,
            )
        )

    def _render_side(self) -> list[tuple[float, float, float]]:
        sigma = self.params["trail_sigma"].get()
        two_sigma_sq = 2.0 * sigma * sigma
        rgb: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)] * LEDS_PER_SIDE
        for p in self._pulses:
            pr, pg, pb = colorsys.hsv_to_rgb(p.hue, 1.0, p.brightness)
            for i in range(LEDS_PER_SIDE):
                d = i - p.position
                w = math.exp(-(d * d) / two_sigma_sq)
                if w < 0.01:
                    continue
                cr, cg, cb = rgb[i]
                rgb[i] = (cr + pr * w, cg + pg * w, cb + pb * w)
        return rgb

    def _silence_level(self, raw_rms: float) -> float:
        gate = self.params["silence_gate"].get()
        if gate <= 0.0:
            return 1.0
        return min(1.0, max(0.0, raw_rms / gate))
