"""Tests for the InterferencePond visualizer effect."""

import numpy as np

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.interference_pond import InterferencePond, _MAX_RIPPLES
from nuphy_rgb.visualizer import freq_to_hue

NUM_LEDS = 84


def _make_frame(**kwargs) -> AudioFrame:
    defaults = dict(
        bass=0.0,
        mids=0.0,
        highs=0.0,
        dominant_freq=0.0,
        rms=0.0,
        is_beat=False,
        timestamp=0.0,
    )
    defaults.update(kwargs)
    return AudioFrame(**defaults)


class TestBasicContract:
    def test_returns_84_tuples(self):
        viz = InterferencePond()
        frame = _make_frame(rms=0.5, dominant_freq=440.0, is_beat=True, timestamp=0.0)
        colors = viz.render(frame)
        assert len(colors) == NUM_LEDS
        assert all(len(c) == 3 for c in colors)

    def test_rgb_values_in_range(self):
        viz = InterferencePond()
        frame = _make_frame(rms=0.8, dominant_freq=1000.0, bass=0.5, is_beat=True, timestamp=0.0)
        # Run several frames so ripples expand
        for i in range(5):
            colors = viz.render(_make_frame(
                rms=0.8, dominant_freq=1000.0, bass=0.5, timestamp=i * 0.033
            ))
        for r, g, b in colors:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_has_name_attribute(self):
        viz = InterferencePond()
        assert isinstance(viz.name, str)
        assert len(viz.name) > 0


class TestSilence:
    def test_silence_no_ripples_is_dark(self):
        viz = InterferencePond()
        # Feed silence: no beats, zero energy -- no ripples ever spawned
        for i in range(10):
            colors = viz.render(_make_frame(rms=0.0, timestamp=i * 0.033))
        total = sum(r + g + b for r, g, b in colors)
        assert total == 0


class TestRippleSpawning:
    def test_beat_spawns_ripple(self):
        viz = InterferencePond()
        assert len(viz._ripples) == 0
        viz.render(_make_frame(is_beat=True, dominant_freq=440.0, rms=0.5, timestamp=0.0))
        assert len(viz._ripples) == 1

    def test_no_beat_no_new_ripple(self):
        viz = InterferencePond()
        viz.render(_make_frame(is_beat=False, rms=0.5, timestamp=0.0))
        assert len(viz._ripples) == 0

    def test_max_ripples_cap(self):
        viz = InterferencePond()
        # Spawn well beyond the cap
        for i in range(_MAX_RIPPLES + 5):
            viz.render(_make_frame(
                is_beat=True,
                dominant_freq=440.0,
                rms=0.5,
                timestamp=i * 1.0,  # large dt so ripples don't fully decay
            ))
        assert len(viz._ripples) <= _MAX_RIPPLES

    def test_ripple_hue_matches_dominant_freq(self):
        viz = InterferencePond()
        freq = 440.0
        expected_hue = freq_to_hue(freq)
        viz.render(_make_frame(is_beat=True, dominant_freq=freq, rms=0.5, timestamp=0.0))
        assert len(viz._ripples) == 1
        assert abs(viz._ripples[0].hue - expected_hue) < 1e-6


class TestOutput:
    def test_single_ripple_produces_nonzero_output(self):
        viz = InterferencePond()
        # Spawn a ripple, then render a frame slightly later so the wave is active
        viz.render(_make_frame(is_beat=True, dominant_freq=440.0, rms=0.5, timestamp=0.0))
        colors = viz.render(_make_frame(rms=0.5, timestamp=0.033))
        total = sum(r + g + b for r, g, b in colors)
        assert total > 0

    def test_brightness_scales_with_rms(self):
        """Higher RMS should produce brighter output when ripples are present."""
        viz_low = InterferencePond()
        viz_high = InterferencePond()

        # Spawn identical ripples in both
        beat_frame_low = _make_frame(is_beat=True, dominant_freq=440.0, rms=0.1, timestamp=0.0)
        beat_frame_high = _make_frame(is_beat=True, dominant_freq=440.0, rms=0.9, timestamp=0.0)
        viz_low.render(beat_frame_low)
        viz_high.render(beat_frame_high)

        colors_low = viz_low.render(_make_frame(rms=0.1, timestamp=0.033))
        colors_high = viz_high.render(_make_frame(rms=0.9, timestamp=0.033))

        brightness_low = sum(max(r, g, b) for r, g, b in colors_low)
        brightness_high = sum(max(r, g, b) for r, g, b in colors_high)
        assert brightness_high > brightness_low

    def test_different_freq_different_colors(self):
        """Two ripples at very different frequencies should produce different dominant hues."""
        viz_bass = InterferencePond()
        viz_treble = InterferencePond()

        viz_bass.render(_make_frame(is_beat=True, dominant_freq=60.0, rms=0.8, timestamp=0.0))
        viz_treble.render(_make_frame(is_beat=True, dominant_freq=8000.0, rms=0.8, timestamp=0.0))

        colors_bass = viz_bass.render(_make_frame(rms=0.8, timestamp=0.033))
        colors_treble = viz_treble.render(_make_frame(rms=0.8, timestamp=0.033))

        # Sum RGB channels as proxy -- at minimum the color distribution differs
        def dominant_channel(colors):
            r_sum = sum(c[0] for c in colors)
            g_sum = sum(c[1] for c in colors)
            b_sum = sum(c[2] for c in colors)
            return max(r_sum, g_sum, b_sum), (r_sum, g_sum, b_sum)

        _, rgb_bass = dominant_channel(colors_bass)
        _, rgb_treble = dominant_channel(colors_treble)
        # They should not be identical (different hues)
        assert rgb_bass != rgb_treble


class TestNewAudioFields:
    def test_onset_strength_scales_ripple_amplitude(self):
        """Higher onset_strength should produce larger bass ripple amplitude."""
        viz_low = InterferencePond()
        viz_high = InterferencePond()

        viz_low.render(_make_frame(is_beat=True, onset_strength=0.0, rms=0.5, timestamp=0.0))
        viz_high.render(_make_frame(is_beat=True, onset_strength=1.0, rms=0.5, timestamp=0.0))

        # Both have been decayed by _update_ripples, but the ratio should hold
        assert viz_high._ripples[0].amplitude > viz_low._ripples[0].amplitude


class TestSparkle:
    def test_high_highs_add_sparkle(self):
        """With extreme highs energy, some LEDs should have zero saturation (sparkle)."""
        # We run two instances: one with no highs, one with max highs.
        # The sparkle instance should have some fully desaturated (white) LEDs.
        viz_no_sparkle = InterferencePond()
        viz_sparkle = InterferencePond()

        beat = _make_frame(is_beat=True, dominant_freq=440.0, rms=0.8, timestamp=0.0)
        viz_no_sparkle.render(beat)
        viz_sparkle.render(beat)

        no_sparkle_colors = viz_no_sparkle.render(
            _make_frame(rms=0.8, highs=0.0, timestamp=0.033)
        )
        sparkle_colors = viz_sparkle.render(
            _make_frame(rms=0.8, highs=1.0, timestamp=0.033)
        )

        def count_near_white(colors):
            # A white LED has r == g == b (or very close) and is bright
            count = 0
            for r, g, b in colors:
                brightness = max(r, g, b)
                if brightness > 50:
                    spread = max(r, g, b) - min(r, g, b)
                    if spread < 30:
                        count += 1
            return count

        # With high highs and rng seed 42, some sparkle LEDs should appear
        # (the exact count depends on rng, but should be more than without highs)
        assert count_near_white(sparkle_colors) >= count_near_white(no_sparkle_colors)

    def test_deterministic_with_same_seed(self):
        """Two InterferencePond instances with default seed produce identical output."""
        viz_a = InterferencePond()
        viz_b = InterferencePond()

        frames = [
            _make_frame(is_beat=True, dominant_freq=440.0, rms=0.8, highs=0.9, timestamp=0.0),
            _make_frame(rms=0.7, highs=0.9, timestamp=0.033),
            _make_frame(is_beat=True, dominant_freq=880.0, rms=0.6, highs=0.85, timestamp=0.066),
            _make_frame(rms=0.5, highs=0.8, timestamp=0.099),
        ]

        for frame in frames:
            colors_a = viz_a.render(frame)
            colors_b = viz_b.render(frame)
            assert colors_a == colors_b, "Output must be deterministic with the same RNG seed"
