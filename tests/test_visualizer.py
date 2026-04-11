
from nuphy_rgb.visualizer import freq_to_hue

from helpers import make_frame

NUM_LEDS = 84


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


