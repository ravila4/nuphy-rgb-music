from nuphy_rgb.sidelights.visualizer import SIDE_LED_COUNT

from helpers import make_frame


class TestBeatPulse:
    def test_returns_12_tuples(self):
        from nuphy_rgb.sidelights.beat_pulse import BeatPulse

        viz = BeatPulse()
        colors = viz.render(make_frame())
        assert len(colors) == SIDE_LED_COUNT
        assert all(len(c) == 3 for c in colors)

    def test_rgb_values_in_range(self):
        from nuphy_rgb.sidelights.beat_pulse import BeatPulse

        viz = BeatPulse()
        viz.render(make_frame(is_beat=True))
        colors = viz.render(make_frame())
        for r, g, b in colors:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_silence_is_dark(self):
        from nuphy_rgb.sidelights.beat_pulse import BeatPulse

        viz = BeatPulse()
        colors = viz.render(make_frame())
        assert all(c == (0, 0, 0) for c in colors)

    def test_beat_triggers_flash(self):
        from nuphy_rgb.sidelights.beat_pulse import BeatPulse

        viz = BeatPulse()
        colors = viz.render(make_frame(is_beat=True))
        # All LEDs should be bright
        assert all(max(r, g, b) > 200 for r, g, b in colors)

    def test_flash_decays(self):
        from nuphy_rgb.sidelights.beat_pulse import BeatPulse

        viz = BeatPulse()
        flash = viz.render(make_frame(is_beat=True))
        flash_brightness = max(flash[0])

        # Several frames later, should be dimmer
        for _ in range(5):
            colors = viz.render(make_frame())
        decayed_brightness = max(colors[0])

        assert decayed_brightness < flash_brightness
        assert decayed_brightness > 0  # not fully dark yet after 5 frames

    def test_all_leds_same_color(self):
        from nuphy_rgb.sidelights.beat_pulse import BeatPulse

        viz = BeatPulse()
        colors = viz.render(make_frame(is_beat=True))
        assert all(c == colors[0] for c in colors)

    def test_has_name(self):
        from nuphy_rgb.sidelights.beat_pulse import BeatPulse

        assert BeatPulse().name == "Beat Pulse"
