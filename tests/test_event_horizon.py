"""Tests for the Event Horizon visualizer effect."""

from __future__ import annotations

import math

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.event_horizon import EventHorizon

from helpers import make_frame

NUM_LEDS = 84


def _render_n(viz: EventHorizon, frame: AudioFrame, n: int) -> list:
    result = None
    for _ in range(n):
        result = viz.render(frame)
    return result


class TestStructure:
    def test_returns_84_tuples(self):
        viz = EventHorizon()
        colors = viz.render(make_frame(rms=0.5))
        assert len(colors) == NUM_LEDS
        assert all(len(c) == 3 for c in colors)

    def test_rgb_values_in_range(self):
        viz = EventHorizon()
        for _ in range(5):
            colors = viz.render(make_frame(rms=0.7, bass=0.4, mids=0.3))
        for r, g, b in colors:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_has_name_attribute(self):
        viz = EventHorizon()
        assert viz.name == "Event Horizon"

    def test_has_params_dict(self):
        viz = EventHorizon()
        assert isinstance(viz.params, dict)
        assert "hole_half_w" in viz.params
        assert "num_arms" in viz.params
        assert "rotation_speed" in viz.params


class TestSilence:
    def test_silence_is_mostly_dark(self):
        viz = EventHorizon()
        silent = make_frame(rms=0.0, raw_rms=0.0, dominant_freq=0.0)
        colors = _render_n(viz, silent, 60)
        total_brightness = sum(r + g + b for r, g, b in colors)
        # The disk still shows a dim photon ring at silence so the black-hole
        # shape is recognizable. Total luminance must still be well below
        # a bright frame.
        assert total_brightness < (NUM_LEDS * 3 * 255 * 0.35)

    def test_rotation_pauses_on_silence(self):
        """Spin energy should decay to ~0 after enough silent frames."""
        viz = EventHorizon()
        # Drive rotation first
        for _ in range(20):
            viz.render(make_frame(rms=0.9, raw_rms=0.5, bass=0.6))
        # Then silence — spin energy should coast down
        for _ in range(80):
            viz.render(make_frame(rms=0.0, raw_rms=0.0))
        rotation_before = viz._disk_rotation
        viz.render(make_frame(rms=0.0, raw_rms=0.0))
        rotation_after = viz._disk_rotation
        # The disk should have effectively stopped spinning
        assert abs(rotation_after - rotation_before) < 1e-3


class TestCollapse:
    def test_beat_sets_collapse_intensity(self):
        viz = EventHorizon()
        assert viz._collapse_intensity == 0.0
        viz.render(make_frame(is_beat=True))
        assert viz._collapse_intensity > 0.8

    def test_collapse_fades_over_frames(self):
        viz = EventHorizon()
        viz.render(make_frame(is_beat=True))
        first = viz._collapse_intensity
        for _ in range(5):
            viz.render(make_frame())
        assert viz._collapse_intensity < first

    def test_collapse_eventually_ends(self):
        viz = EventHorizon()
        viz.render(make_frame(is_beat=True))
        for _ in range(30):
            viz.render(make_frame())
        assert viz._collapse_intensity < 0.01

    def test_onset_strength_scales_collapse(self):
        viz_low = EventHorizon()
        viz_high = EventHorizon()
        viz_low.render(make_frame(is_beat=True, onset_strength=0.0))
        viz_high.render(make_frame(is_beat=True, onset_strength=1.0))
        assert viz_high._collapse_intensity > viz_low._collapse_intensity


class TestInfallRings:
    def test_bass_beat_spawns_ring(self):
        viz = EventHorizon()
        assert len(viz._infall_rings) == 0
        viz.render(make_frame(is_beat=True, bass=0.6))
        assert len(viz._infall_rings) == 1

    def test_beat_without_bass_does_not_spawn(self):
        """A beat with no low-end energy should not inject warmth."""
        viz = EventHorizon()
        viz.render(make_frame(is_beat=True, bass=0.0))
        assert len(viz._infall_rings) == 0

    def test_rings_fall_inward(self):
        viz = EventHorizon()
        viz.render(make_frame(is_beat=True, bass=0.6, timestamp=0.0))
        assert viz._infall_rings
        start_radius = viz._infall_rings[0].radius
        for i in range(5):
            viz.render(make_frame(is_beat=False, bass=0.1, timestamp=(i + 1) * 0.033))
        # Ring should have advected closer to the singularity
        assert viz._infall_rings[0].radius < start_radius

    def test_rings_get_swallowed(self):
        """Rings that cross the photon ring must be culled."""
        viz = EventHorizon()
        viz.render(make_frame(is_beat=True, bass=0.6, timestamp=0.0))
        assert viz._infall_rings
        # Advance enough real time for the infall to cross the ring
        for i in range(120):
            viz.render(make_frame(is_beat=False, bass=0.0, timestamp=(i + 1) * 0.033))
        assert len(viz._infall_rings) == 0

    def test_rings_respect_max_cap(self):
        viz = EventHorizon()
        for _ in range(20):
            viz.render(make_frame(is_beat=True, bass=0.8))
        assert len(viz._infall_rings) <= 6


class TestRingStructure:
    def test_ring_brighter_than_far_edge(self):
        """The photon-ring annulus should be brighter than keys far from the singularity."""
        viz = EventHorizon()
        warm = make_frame(rms=0.8, raw_rms=0.4, bass=0.3, mids=0.2, dominant_freq=440.0)
        # Warm up so brightness + singularity filters converge
        for _ in range(40):
            viz.render(warm)
        colors = viz.render(warm)

        from nuphy_rgb.plugin_api import MAX_COLS, NUM_ROWS, LED_X, LED_Y

        key_x = LED_X * (MAX_COLS - 1)
        key_y = LED_Y * (NUM_ROWS - 1)
        # The singularity orbits, but its filtered position is available
        sx, sy = viz._sx_filter.value, viz._sy_filter.value

        ring_lum: list[float] = []
        far_lum: list[float] = []
        for i, (r, g, b) in enumerate(colors):
            dist = math.hypot(key_x[i] - sx, key_y[i] - sy)
            lum = (r + g + b) / (3 * 255)
            if 1.5 <= dist <= 3.0:
                ring_lum.append(lum)
            elif dist > 5.0:
                far_lum.append(lum)

        assert ring_lum and far_lum
        avg_ring = sum(ring_lum) / len(ring_lum)
        avg_far = sum(far_lum) / len(far_lum)
        assert avg_ring > avg_far, (
            f"Ring avg {avg_ring:.3f} should exceed far-edge avg {avg_far:.3f}"
        )

    def test_event_horizon_is_dark(self):
        """LEDs inside the fixed 2x2 void rectangle must be black."""
        viz = EventHorizon()
        warm = make_frame(rms=0.8, raw_rms=0.4, bass=0.3, is_beat=True)
        for _ in range(10):
            viz.render(warm)
        colors = viz.render(warm)

        from nuphy_rgb.plugin_api import MAX_COLS, NUM_ROWS, LED_X, LED_Y

        key_x = LED_X * (MAX_COLS - 1)
        key_y = LED_Y * (NUM_ROWS - 1)
        sx, sy = viz._sx_filter.value, viz._sy_filter.value
        # Void is fixed — no breathing. Shrink slightly to avoid edge FP noise.
        hw = viz.params["hole_half_w"].value * 0.9
        hh = viz.params["hole_half_h"].value * 0.9

        for i, (r, g, b) in enumerate(colors):
            if abs(key_x[i] - sx) < hw and abs(key_y[i] - sy) < hh:
                assert (r, g, b) == (0, 0, 0), (
                    f"LED {i} inside void should be black, got ({r},{g},{b})"
                )

    def test_disk_breathes_with_loudness(self):
        """Loud frames should drive the breath envelope well above silence."""
        viz_quiet = EventHorizon()
        viz_loud = EventHorizon()
        for _ in range(80):
            viz_quiet.render(make_frame(rms=0.0, raw_rms=0.0))
            viz_loud.render(make_frame(rms=0.9, raw_rms=0.6))
        assert viz_loud._breath_energy.value > viz_quiet._breath_energy.value + 0.3


class TestDeterminism:
    def test_reproducible_across_instances(self):
        """Two fresh instances with the same input produce identical output."""
        frames = [
            make_frame(rms=0.5, bass=0.3, mids=0.2, dominant_freq=220.0),
            make_frame(rms=0.7, bass=0.8, mids=0.1, is_beat=True),
            make_frame(rms=0.6, bass=0.2, mids=0.4, dominant_freq=880.0),
        ]
        viz_a = EventHorizon()
        viz_b = EventHorizon()
        for f in frames:
            out_a = viz_a.render(f)
            out_b = viz_b.render(f)
            assert out_a == out_b
