"""Tests for the Event Horizon visualizer effect."""

import pytest

from nuphy_rgb.effects.event_horizon import EventHorizon

from nuphy_rgb.audio import AudioFrame

from helpers import make_frame

NUM_LEDS = 84


def _render_n(viz: EventHorizon, frame: AudioFrame, n: int) -> list:
    """Render n frames, return the last result."""
    result = None
    for _ in range(n):
        result = viz.render(frame)
    return result


# ---------------------------------------------------------------------------
# Basic structural tests
# ---------------------------------------------------------------------------


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
        assert hasattr(viz, "name")
        assert isinstance(viz.name, str)
        assert len(viz.name) > 0


# ---------------------------------------------------------------------------
# Silence / darkness
# ---------------------------------------------------------------------------


class TestSilence:
    def test_silence_is_mostly_dark(self):
        """With rms=0 the global brightness scale should suppress most output."""
        viz = EventHorizon()
        # Feed many silent frames to let the brightness filter converge
        silent = make_frame(rms=0.0, dominant_freq=0.0)
        colors = _render_n(viz, silent, 30)
        total_brightness = sum(r + g + b for r, g, b in colors)
        # With rms=0, each LED's brightness contribution is capped by the
        # global_brightness floor (0.05 * max_ring_contribution).
        # Total should be well below half of max possible (84 * 3 * 255 / 2).
        assert total_brightness < (NUM_LEDS * 3 * 255 * 0.15)


# ---------------------------------------------------------------------------
# Beat / collapse
# ---------------------------------------------------------------------------


class TestCollapse:
    def test_beat_triggers_collapse(self):
        viz = EventHorizon()
        assert viz._collapse_frames == 0
        viz.render(make_frame(is_beat=True))
        # After a beat frame the collapse counter should be set (then ticked
        # down by 1 within the same render call, so 12-1 = 11 remaining).
        assert viz._collapse_frames >= 10

    def test_collapse_fades_over_frames(self):
        """collapse_intensity should decrease each frame after the beat."""
        viz = EventHorizon()
        viz.render(make_frame(is_beat=True))
        first_intensity = viz._collapse_intensity

        # Render several non-beat frames
        for _ in range(5):
            viz.render(make_frame())

        assert viz._collapse_intensity < first_intensity

    def test_collapse_eventually_ends(self):
        viz = EventHorizon()
        viz.render(make_frame(is_beat=True))

        for _ in range(30):
            viz.render(make_frame())

        # After enough frames the collapse should be fully spent
        assert viz._collapse_frames == 0
        assert viz._collapse_intensity < 0.01


# ---------------------------------------------------------------------------
# Particles
# ---------------------------------------------------------------------------


class TestParticles:
    def test_particles_spawn_on_beat(self):
        viz = EventHorizon(seed=0)
        assert len(viz._particles) == 0
        viz.render(make_frame(is_beat=True))
        assert len(viz._particles) >= 2

    def test_particles_die_over_time(self):
        viz = EventHorizon(seed=1)
        viz.render(make_frame(is_beat=True))
        initial_count = len(viz._particles)
        assert initial_count > 0

        # Render many frames without new beats
        for _ in range(30):
            viz.render(make_frame(is_beat=False))

        assert len(viz._particles) < initial_count

    def test_particles_max_cap(self):
        """Repeated beats should not exceed the 12-particle cap."""
        viz = EventHorizon(seed=2)
        for _ in range(10):
            viz.render(make_frame(is_beat=True))
        assert len(viz._particles) <= 12


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestNewAudioFields:
    def test_onset_strength_scales_collapse(self):
        """Higher onset_strength should produce stronger collapse intensity."""
        viz_low = EventHorizon(seed=42)
        viz_high = EventHorizon(seed=42)

        viz_low.render(make_frame(is_beat=True, onset_strength=0.0))
        viz_high.render(make_frame(is_beat=True, onset_strength=1.0))

        assert viz_high._collapse_intensity > viz_low._collapse_intensity
        # Default (onset=0) should match old behavior: exactly 1.0
        assert viz_low._collapse_intensity == 1.0

    def test_high_beat_sets_spiral_frames(self):
        """high_beat=True should set _spiral_frames to 3."""
        viz = EventHorizon(seed=42)
        viz.render(make_frame(high_beat=True))
        assert viz._spiral_frames > 0

    def test_spiral_frames_decay(self):
        """_spiral_frames should decrement each non-high-beat frame."""
        viz = EventHorizon(seed=42)
        viz.render(make_frame(high_beat=True))
        initial = viz._spiral_frames

        viz.render(make_frame())
        assert viz._spiral_frames == initial - 1

        viz.render(make_frame())
        viz.render(make_frame())
        assert viz._spiral_frames == 0

    def test_spectral_flux_turbulence_affects_particles(self):
        """Particles with high spectral_flux should scatter more than with zero flux."""
        viz_calm = EventHorizon(seed=42)
        viz_turb = EventHorizon(seed=42)

        # Spawn particles with a beat
        viz_calm.render(make_frame(is_beat=True, rms=0.5))
        viz_turb.render(make_frame(is_beat=True, rms=0.5))

        # Run several frames with different flux
        for _ in range(10):
            viz_calm.render(make_frame(rms=0.5, spectral_flux=0.0))
            viz_turb.render(make_frame(rms=0.5, spectral_flux=1.0))

        # Turbulent particles should be at different positions
        calm_pos = [(p.x, p.y) for p in viz_calm._particles]
        turb_pos = [(p.x, p.y) for p in viz_turb._particles]
        assert calm_pos != turb_pos, "Turbulence should scatter particles"


class TestDeterminism:
    def test_deterministic_output(self):
        """Two instances with the same seed produce identical output."""
        frames = [
            make_frame(rms=0.5, bass=0.3, mids=0.2, dominant_freq=220.0),
            make_frame(rms=0.7, bass=0.8, mids=0.1, is_beat=True),
            make_frame(rms=0.6, bass=0.2, mids=0.4, dominant_freq=880.0),
        ]

        viz_a = EventHorizon(seed=42)
        viz_b = EventHorizon(seed=42)

        for f in frames:
            out_a = viz_a.render(f)
            out_b = viz_b.render(f)
            assert out_a == out_b, "Outputs diverged for frame"

    def test_different_seeds_differ(self):
        """Different seeds should (almost certainly) produce different output."""
        frame = make_frame(rms=0.5, is_beat=True)
        viz_a = EventHorizon(seed=42)
        viz_b = EventHorizon(seed=99)
        # Render several frames so particle RNG has a chance to diverge
        for _ in range(3):
            out_a = viz_a.render(frame)
            out_b = viz_b.render(frame)
        # At least one LED should differ
        assert out_a != out_b


# ---------------------------------------------------------------------------
# Ring structure
# ---------------------------------------------------------------------------


class TestRingStructure:
    def test_ring_structure(self):
        """LEDs at medium distance from the singularity are brighter than far-edge ones.

        We run several warm-up frames to let the brightness filter rise, then
        compare average brightness of 'mid-ring' LEDs vs 'outer' LEDs.
        """
        viz = EventHorizon(seed=7)
        warm = make_frame(rms=0.8, bass=0.3, mids=0.2, dominant_freq=440.0)
        # Warm up so global_brightness filter converges
        for _ in range(20):
            viz.render(warm)
        colors = viz.render(warm)

        from nuphy_rgb.effects.grid import LED_X, LED_Y
        import math

        # Singularity is roughly at centre after many frames
        sx, sy = 0.5, 0.5

        mid_ring_brightness: list[float] = []
        far_edge_brightness: list[float] = []

        for i, (r, g, b) in enumerate(colors):
            dist = math.hypot(LED_X[i] - sx, LED_Y[i] - sy) / 0.6
            lum = (r + g + b) / (3 * 255)
            if 0.20 <= dist <= 0.40:
                mid_ring_brightness.append(lum)
            elif dist > 0.70:
                far_edge_brightness.append(lum)

        if mid_ring_brightness and far_edge_brightness:
            avg_ring = sum(mid_ring_brightness) / len(mid_ring_brightness)
            avg_far = sum(far_edge_brightness) / len(far_edge_brightness)
            assert avg_ring > avg_far, (
                f"Ring avg {avg_ring:.3f} should exceed far-edge avg {avg_far:.3f}"
            )
