from nuphy_rgb.sidelights.visualizer import SIDE_LED_COUNT

from helpers import make_frame


class TestVUMeter:
    def test_returns_12_tuples(self):
        from nuphy_rgb.sidelights.vu_meter import VUMeter

        viz = VUMeter()
        colors = viz.render(make_frame(bass=0.5))
        assert len(colors) == SIDE_LED_COUNT
        assert all(len(c) == 3 for c in colors)

    def test_rgb_values_in_range(self):
        from nuphy_rgb.sidelights.vu_meter import VUMeter

        viz = VUMeter()
        colors = viz.render(make_frame(bass=0.8))
        for r, g, b in colors:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_silence_is_dark(self):
        from nuphy_rgb.sidelights.vu_meter import VUMeter

        viz = VUMeter()
        colors = viz.render(make_frame(bass=0.0))
        assert all(c == (0, 0, 0) for c in colors)

    def test_loud_fills_bars(self):
        from nuphy_rgb.sidelights.vu_meter import VUMeter

        viz = VUMeter()
        # Warm up the ExpFilter
        for _ in range(30):
            viz.render(make_frame(bass=1.0))
        colors = viz.render(make_frame(bass=1.0))
        # All 12 LEDs should be lit
        assert all(max(r, g, b) > 0 for r, g, b in colors)

    def test_symmetric_output(self):
        from nuphy_rgb.sidelights.vu_meter import VUMeter

        viz = VUMeter()
        for _ in range(20):
            viz.render(make_frame(bass=0.5))
        colors = viz.render(make_frame(bass=0.5))
        # Left bar (indices 0-5 bottom-to-top) should mirror
        # right bar (indices 11-6 bottom-to-top)
        for i in range(6):
            left_color = colors[i]          # left[0..5]
            right_color = colors[11 - i]    # right[11..6]
            assert left_color == right_color, (
                f"Position {i}: left={left_color} != right={right_color}"
            )

    def test_partial_fill(self):
        from nuphy_rgb.sidelights.vu_meter import VUMeter

        viz = VUMeter()
        # Feed moderate bass to get partial fill
        for _ in range(30):
            viz.render(make_frame(bass=0.4))
        colors = viz.render(make_frame(bass=0.4))
        # Some LEDs lit, some dark
        lit = sum(1 for c in colors if max(c) > 0)
        dark = SIDE_LED_COUNT - lit
        assert lit > 0, "Should have some lit LEDs"
        assert dark > 0, "Should have some dark LEDs"

    def test_has_name(self):
        from nuphy_rgb.sidelights.vu_meter import VUMeter

        assert VUMeter().name == "VU Meter"
