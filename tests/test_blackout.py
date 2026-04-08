from nuphy_rgb.effects.blackout import Blackout

from helpers import make_frame


class TestBlackout:
    def test_returns_84_black_tuples(self):
        viz = Blackout()
        colors = viz.render(make_frame())
        assert len(colors) == 84
        assert all(c == (0, 0, 0) for c in colors)

    def test_ignores_audio(self):
        viz = Blackout()
        quiet = viz.render(make_frame())
        loud = viz.render(make_frame(bass=1.0, rms=1.0, is_beat=True))
        assert quiet == loud

    def test_has_name(self):
        assert Blackout().name == "Blackout"
