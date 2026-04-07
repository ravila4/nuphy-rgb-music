"""Tests for VelvetMothSwarm visualizer effect."""

import pytest

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.velvet_moth_swarm import VelvetMothSwarm

NUM_LEDS = 84


def _make_frame(**kwargs) -> AudioFrame:
    defaults = dict(
        bass=0.0, mids=0.0, highs=0.0,
        dominant_freq=440.0, rms=0.0, is_beat=False, timestamp=0.0,
    )
    defaults.update(kwargs)
    return AudioFrame(**defaults)


class TestVelvetMothSwarm:
    def test_returns_84_tuples(self):
        viz = VelvetMothSwarm(seed=42)
        frame = _make_frame(rms=0.5)
        colors = viz.render(frame)
        assert len(colors) == NUM_LEDS
        assert all(len(c) == 3 for c in colors)

    def test_rgb_values_in_range(self):
        viz = VelvetMothSwarm(seed=42)
        for i in range(5):
            frame = _make_frame(rms=0.8, bass=0.6, timestamp=i * 0.033)
            colors = viz.render(frame)
        for r, g, b in colors:
            assert 0 <= r <= 255, f"r={r} out of range"
            assert 0 <= g <= 255, f"g={g} out of range"
            assert 0 <= b <= 255, f"b={b} out of range"

    def test_has_name_attribute(self):
        viz = VelvetMothSwarm()
        assert hasattr(viz, "name")
        assert isinstance(viz.name, str)
        assert len(viz.name) > 0

    def test_silence_has_moonlight(self):
        """Even in silence, the moonlight glow means output is not all black."""
        viz = VelvetMothSwarm(seed=7)
        # Run several silent frames to accumulate moonlight
        for i in range(10):
            frame = _make_frame(rms=0.0, bass=0.0, mids=0.0, highs=0.0,
                                dominant_freq=440.0, timestamp=i * 0.033)
            colors = viz.render(frame)
        total = sum(r + g + b for r, g, b in colors)
        assert total > 0, "Expected moonlight glow even in silence"

    def test_beat_increases_brightness(self):
        """A beat frame should produce more total brightness than a non-beat frame
        from the same initial state."""
        # No-beat branch
        viz_no = VelvetMothSwarm(seed=99)
        for i in range(5):
            viz_no.render(_make_frame(rms=0.5, bass=0.4, timestamp=i * 0.033))
        no_beat = viz_no.render(_make_frame(
            rms=0.5, bass=0.4, is_beat=False, timestamp=5 * 0.033
        ))

        # Beat branch – same seed, same frames, last frame has beat
        viz_yes = VelvetMothSwarm(seed=99)
        for i in range(5):
            viz_yes.render(_make_frame(rms=0.5, bass=0.4, timestamp=i * 0.033))
        with_beat = viz_yes.render(_make_frame(
            rms=0.5, bass=0.4, is_beat=True, timestamp=5 * 0.033
        ))

        brightness_no = sum(max(r, g, b) for r, g, b in no_beat)
        brightness_yes = sum(max(r, g, b) for r, g, b in with_beat)
        assert brightness_yes > brightness_no, (
            f"Beat brightness {brightness_yes} should exceed no-beat {brightness_no}"
        )

    def test_trail_decay(self):
        """After loud frames, subsequent silence should show decay (not stay at max)."""
        viz = VelvetMothSwarm(seed=13)
        # Feed loud frames to fill the field
        for i in range(15):
            viz.render(_make_frame(rms=0.9, bass=0.8, mids=0.5,
                                   dominant_freq=200.0, timestamp=i * 0.033))
        loud_colors = viz.render(_make_frame(
            rms=0.9, bass=0.8, timestamp=15 * 0.033
        ))

        # Now go silent for many frames
        for i in range(60):
            viz.render(_make_frame(rms=0.0, bass=0.0, mids=0.0,
                                   dominant_freq=0.0, timestamp=(16 + i) * 0.033))
        quiet_colors = viz.render(_make_frame(
            rms=0.0, bass=0.0, timestamp=76 * 0.033
        ))

        brightness_loud = sum(r + g + b for r, g, b in loud_colors)
        brightness_quiet = sum(r + g + b for r, g, b in quiet_colors)
        assert brightness_quiet < brightness_loud, (
            f"Quiet brightness {brightness_quiet} should be less than loud {brightness_loud}"
        )

    def test_deterministic_with_seed(self):
        """Same seed and same frames must produce identical output."""
        frames = [
            _make_frame(rms=0.6, bass=0.4, mids=0.3, highs=0.2,
                        dominant_freq=440.0, is_beat=(i % 8 == 0),
                        timestamp=i * 0.033)
            for i in range(10)
        ]

        viz_a = VelvetMothSwarm(seed=42)
        viz_b = VelvetMothSwarm(seed=42)

        for f in frames:
            out_a = viz_a.render(f)
            out_b = viz_b.render(f)

        assert out_a == out_b, "Same seed must yield identical output"

    def test_field_values_valid(self):
        """Output RGB values must be non-negative and <= 255 (no clipping artifacts)."""
        viz = VelvetMothSwarm(seed=5)
        for i in range(20):
            is_beat = (i % 4 == 0)
            colors = viz.render(_make_frame(
                rms=1.0, bass=1.0, mids=1.0, highs=1.0,
                dominant_freq=500.0, is_beat=is_beat,
                timestamp=i * 0.033,
            ))
        for r, g, b in colors:
            assert r >= 0 and r <= 255
            assert g >= 0 and g <= 255
            assert b >= 0 and b <= 255
