import pytest

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.color_wash import ColorWash
from nuphy_rgb.visualizer import freq_to_hue

NUM_LEDS = 84


def _make_frame(**kwargs) -> AudioFrame:
    defaults = dict(
        bass=0.0, mids=0.0, highs=0.0,
        dominant_freq=0.0, rms=0.0, is_beat=False, timestamp=0.0,
    )
    defaults.update(kwargs)
    return AudioFrame(**defaults)


class TestFreqToHue:
    def test_bass_maps_to_low_hue(self):
        hue = freq_to_hue(20.0)
        assert 0.0 <= hue <= 0.15

    def test_high_maps_to_high_hue(self):
        hue = freq_to_hue(16000.0)
        assert 0.85 <= hue <= 1.0

    def test_mid_maps_to_middle(self):
        hue = freq_to_hue(1000.0)
        assert 0.3 < hue < 0.7

    def test_clamps_below_min(self):
        hue = freq_to_hue(5.0)
        assert hue == 0.0

    def test_clamps_above_max(self):
        hue = freq_to_hue(20000.0)
        assert hue == 1.0

    def test_zero_freq_clamps(self):
        hue = freq_to_hue(0.0)
        assert hue == 0.0


class TestColorWash:
    def test_returns_84_tuples(self):
        viz = ColorWash(num_leds=NUM_LEDS)
        frame = _make_frame(rms=0.5, dominant_freq=440.0)
        colors = viz.render(frame)
        assert len(colors) == NUM_LEDS
        assert all(len(c) == 3 for c in colors)

    def test_rgb_values_in_range(self):
        viz = ColorWash(num_leds=NUM_LEDS)
        frame = _make_frame(rms=0.8, dominant_freq=1000.0, bass=0.5)
        colors = viz.render(frame)
        for r, g, b in colors:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_silence_is_dark(self):
        viz = ColorWash(num_leds=NUM_LEDS)
        frame = _make_frame(rms=0.0, dominant_freq=0.0)
        colors = viz.render(frame)
        total_brightness = sum(r + g + b for r, g, b in colors)
        assert total_brightness == 0

    def test_loud_is_bright(self):
        viz = ColorWash(num_leds=NUM_LEDS)
        # Feed several loud frames to let the ExpFilter converge
        for _ in range(20):
            viz.render(_make_frame(rms=0.9, dominant_freq=440.0))
        colors = viz.render(_make_frame(rms=0.9, dominant_freq=440.0))
        avg_brightness = sum(max(r, g, b) for r, g, b in colors) / NUM_LEDS
        assert avg_brightness > 100

    def test_beat_boosts_brightness(self):
        viz = ColorWash(num_leds=NUM_LEDS)
        # Stabilize with non-beat frames
        for _ in range(20):
            viz.render(_make_frame(rms=0.5, dominant_freq=440.0))
        no_beat = viz.render(_make_frame(rms=0.5, dominant_freq=440.0, is_beat=False))
        # Reset to same state and test with beat
        viz2 = ColorWash(num_leds=NUM_LEDS)
        for _ in range(20):
            viz2.render(_make_frame(rms=0.5, dominant_freq=440.0))
        with_beat = viz2.render(_make_frame(rms=0.5, dominant_freq=440.0, is_beat=True))

        brightness_no_beat = sum(max(r, g, b) for r, g, b in no_beat)
        brightness_beat = sum(max(r, g, b) for r, g, b in with_beat)
        assert brightness_beat > brightness_no_beat

    def test_all_leds_same_color(self):
        viz = ColorWash(num_leds=NUM_LEDS)
        frame = _make_frame(rms=0.7, dominant_freq=440.0)
        # Warm up
        for _ in range(10):
            viz.render(frame)
        colors = viz.render(frame)
        # All LEDs should be identical in a wash effect
        assert all(c == colors[0] for c in colors)
