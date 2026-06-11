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


class TestFlare:
    def test_swallow_adds_flare(self):
        """A ring crossing the photon ring dumps its intensity into the flare."""
        from nuphy_rgb.effects.event_horizon.effect import _InfallRing

        viz = EventHorizon()
        viz.render(make_frame())
        viz._infall_rings.append(
            _InfallRing(radius=1.0, intensity=0.8, spawn_radius=4.0)
        )
        viz.render(make_frame())
        assert len(viz._infall_rings) == 0, "ring should have been swallowed"
        assert viz._flare > 0.3

    def test_fadeout_does_not_flare(self):
        """Rings culled for low intensity (not swallowed) must not flash."""
        from nuphy_rgb.effects.event_horizon.effect import _InfallRing

        viz = EventHorizon()
        viz.render(make_frame())
        viz._infall_rings.append(
            _InfallRing(radius=3.5, intensity=0.01, spawn_radius=4.0)
        )
        viz.render(make_frame())
        assert len(viz._infall_rings) == 0, "weak ring should have been culled"
        assert viz._flare == 0.0

    def test_flare_decays(self):
        """Flare decay is framerate-independent, so simulated time must advance."""
        viz = EventHorizon()
        viz.render(make_frame(timestamp=0.0))
        viz._flare = 1.0
        for i in range(30):
            viz.render(make_frame(timestamp=(i + 1) * 0.033))
        assert viz._flare < 0.05

    def test_beat_does_not_flash_immediately(self):
        """The flash happens at swallow time, ~1s after the beat — not on it."""
        viz = EventHorizon()
        viz.render(make_frame(is_beat=True, bass=0.6, onset_strength=1.0))
        assert viz._flare == 0.0
        assert not hasattr(viz, "_collapse_intensity")

    def test_flare_brightens_photon_ring(self):
        viz_flare = EventHorizon()
        viz_base = EventHorizon()
        warm = make_frame(rms=0.5, raw_rms=0.3)
        for _ in range(20):
            viz_flare.render(warm)
            viz_base.render(warm)
        viz_flare._flare = 1.0
        out_flare = viz_flare.render(warm)
        out_base = viz_base.render(warm)
        lum_flare = sum(sum(c) for c in out_flare)
        lum_base = sum(sum(c) for c in out_base)
        assert lum_flare > lum_base + NUM_LEDS * 3 * 255 * 0.01


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


class TestWarmthVisibility:
    def test_warm_envelope_full_strength_inside(self):
        import numpy as np

        from nuphy_rgb.effects.event_horizon.effect import _warm_envelope

        env = _warm_envelope(np.array([0.0, 2.0, 4.0]), disk_extent=5.0)
        assert np.allclose(env, 1.0)

    def test_warm_envelope_zero_outside(self):
        import numpy as np

        from nuphy_rgb.effects.event_horizon.effect import _warm_envelope

        env = _warm_envelope(np.array([5.0, 6.5]), disk_extent=5.0)
        assert np.allclose(env, 0.0)

    def test_warm_envelope_fades_at_rim(self):
        import numpy as np

        from nuphy_rgb.effects.event_horizon.effect import _warm_envelope

        env = _warm_envelope(np.array([4.7]), disk_extent=5.0)
        assert 0.0 < env[0] < 1.0

    def test_fresh_ring_visible_at_spawn_radius(self):
        """A just-spawned infall ring must light its LEDs immediately.

        Regression: warmth used to be masked by the exponential disk
        envelope, leaving rings invisible for the outer third of their
        journey (diag baseline 2026-06-11).
        """
        viz_beat = EventHorizon()
        viz_base = EventHorizon()
        for i in range(30):
            f = make_frame(rms=0.8, raw_rms=0.4, bass=0.3, timestamp=i / 30)
            viz_beat.render(f)
            viz_base.render(f)

        beat = viz_beat.render(make_frame(
            rms=0.8, raw_rms=0.4, bass=0.6, onset_strength=0.8,
            is_beat=True, timestamp=31 / 30,
        ))
        base = viz_base.render(make_frame(
            rms=0.8, raw_rms=0.4, bass=0.6, onset_strength=0.8,
            is_beat=False, timestamp=31 / 30,
        ))
        assert viz_beat._infall_rings, "beat should have spawned a ring"
        spawn_radius = viz_beat._infall_rings[-1].radius

        from nuphy_rgb.plugin_api import MAX_COLS, NUM_ROWS, LED_X, LED_Y

        key_x = LED_X * (MAX_COLS - 1)
        key_y = LED_Y * (NUM_ROWS - 1)
        sx, sy = viz_beat._sx_filter.value, viz_beat._sy_filter.value

        deltas: list[float] = []
        for i in range(NUM_LEDS):
            dist = math.hypot(key_x[i] - sx, key_y[i] - sy)
            if abs(dist - spawn_radius) < 0.5:
                lum_beat = sum(beat[i]) / (3 * 255)
                lum_base = sum(base[i]) / (3 * 255)
                deltas.append(lum_beat - lum_base)

        assert deltas, "no LEDs found near the spawn radius"
        avg_delta = sum(deltas) / len(deltas)
        # Calibration (2026-06-11): envelope-masked (broken) measures 0.026,
        # decoupled (fixed) measures 0.079. Threshold sits between with margin.
        assert avg_delta > 0.05, (
            f"freshly spawned ring should brighten its LEDs, delta={avg_delta:.3f}"
        )


class TestInfallDynamics:
    def test_velocity_constant_when_accel_zero(self):
        from nuphy_rgb.effects.event_horizon.effect import _infall_velocity

        v_far = _infall_velocity(4.0, spawn_radius=4.5, base_speed=0.05, accel=0.0)
        v_near = _infall_velocity(1.5, spawn_radius=4.5, base_speed=0.05, accel=0.0)
        assert v_far == v_near == 0.05

    def test_velocity_equals_base_at_spawn(self):
        from nuphy_rgb.effects.event_horizon.effect import _infall_velocity

        v = _infall_velocity(4.5, spawn_radius=4.5, base_speed=0.05, accel=0.5)
        assert abs(v - 0.05) < 1e-9

    def test_velocity_increases_inward(self):
        from nuphy_rgb.effects.event_horizon.effect import _infall_velocity

        v_far = _infall_velocity(4.0, spawn_radius=4.5, base_speed=0.05, accel=0.5)
        v_near = _infall_velocity(1.5, spawn_radius=4.5, base_speed=0.05, accel=0.5)
        assert v_near > v_far

    def test_tidal_width_shrinks_inward(self):
        from nuphy_rgb.effects.event_horizon.effect import _tidal_profile

        w_spawn, _ = _tidal_profile(4.5, spawn_radius=4.5, base_width=0.9, tidal_min=0.35)
        w_near, _ = _tidal_profile(2.0, spawn_radius=4.5, base_width=0.9, tidal_min=0.35)
        assert abs(w_spawn - 0.9) < 1e-9
        assert w_near < w_spawn

    def test_tidal_width_has_floor(self):
        from nuphy_rgb.effects.event_horizon.effect import _tidal_profile

        w, _ = _tidal_profile(0.5, spawn_radius=4.5, base_width=0.9, tidal_min=0.35)
        assert abs(w - 0.9 * 0.35) < 1e-9

    def test_tidal_flux_conserved(self):
        """Peak boost compensates thinning: width * boost == base width."""
        from nuphy_rgb.effects.event_horizon.effect import _tidal_profile

        for radius in (4.5, 3.0, 2.0):
            w, boost = _tidal_profile(radius, spawn_radius=4.5, base_width=0.9, tidal_min=0.35)
            assert abs(w * boost - 0.9) < 1e-9

    def test_infall_accelerates_toward_horizon(self):
        """Per-frame radius deltas must grow as a ring falls inward."""
        viz = EventHorizon()
        viz.render(make_frame(is_beat=True, bass=0.6, timestamp=0.0))
        assert viz._infall_rings
        radii = [viz._infall_rings[0].radius]
        for i in range(12):
            viz.render(make_frame(bass=0.0, timestamp=(i + 1) * 0.033))
            if not viz._infall_rings:
                break
            radii.append(viz._infall_rings[0].radius)
        deltas = [a - b for a, b in zip(radii, radii[1:])]
        assert len(deltas) >= 6, "ring swallowed too quickly to observe"
        assert all(d2 > d1 for d1, d2 in zip(deltas, deltas[1:])), (
            f"infall speed should increase monotonically, deltas={deltas}"
        )

    def test_ring_intensity_persists_during_infall(self):
        """No per-frame decay: a falling ring keeps its spawn intensity."""
        viz = EventHorizon()
        viz.render(make_frame(is_beat=True, bass=0.6, timestamp=0.0))
        spawn_intensity = viz._infall_rings[0].intensity
        for i in range(5):
            viz.render(make_frame(bass=0.0, timestamp=(i + 1) * 0.033))
        assert viz._infall_rings, "ring should still be falling after 5 frames"
        assert viz._infall_rings[0].intensity == spawn_intensity


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


class TestBeaming:
    def test_uniform_when_no_spin(self):
        import numpy as np

        from nuphy_rgb.effects.event_horizon.effect import _beaming_field

        theta = np.linspace(-math.pi, math.pi, 16)
        field = _beaming_field(theta, rotation=1.3, spin=0.0, strength=0.7)
        assert np.allclose(field, 1.0)

    def test_bounds_at_full_spin(self):
        import numpy as np

        from nuphy_rgb.effects.event_horizon.effect import _beaming_field

        theta = np.linspace(-math.pi, math.pi, 64)
        field = _beaming_field(theta, rotation=0.0, spin=1.0, strength=0.7)
        assert field.min() >= 0.3 - 1e-9
        assert field.max() <= 1.7 + 1e-9
        assert field.min() > 0.0

    def test_approaching_side_brighter(self):
        import numpy as np

        from nuphy_rgb.effects.event_horizon.effect import _beaming_field

        rotation = 0.7
        bright = _beaming_field(np.array([rotation]), rotation, spin=1.0, strength=0.5)
        dim = _beaming_field(
            np.array([rotation + math.pi]), rotation, spin=1.0, strength=0.5
        )
        assert bright[0] > dim[0]


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
