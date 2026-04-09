"""Tests for the chroma-based sidelight effects."""

from helpers import make_frame

from nuphy_rgb.hid_utils import SIDE_LED_COUNT
from nuphy_rgb.sidelights.chroma_bars import ChromaBars
from nuphy_rgb.sidelights.chord_glow import ChordGlow


def _c_major():
    v = [0.0] * 12
    v[0], v[4], v[7] = 0.9, 0.7, 0.8
    return tuple(v)


class TestChromaBars:
    def test_returns_12_tuples(self):
        colors = ChromaBars().render(make_frame(rms=0.5, chroma=_c_major()))
        assert len(colors) == SIDE_LED_COUNT
        assert all(len(c) == 3 for c in colors)

    def test_rgb_in_range(self):
        viz = ChromaBars()
        for i in range(10):
            colors = viz.render(make_frame(rms=0.8, raw_rms=0.5, chroma=_c_major(),
                                       is_beat=True, timestamp=i * 0.033))
        for r, g, b in colors:
            assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255

    def test_silence_is_dark(self):
        viz = ChromaBars()
        for i in range(10):
            viz.render(make_frame(timestamp=i * 0.033))
        colors = viz.render(make_frame(timestamp=0.4))
        assert sum(r + g + b for r, g, b in colors) == 0

    def test_has_name(self):
        assert isinstance(ChromaBars().name, str)

    def test_active_notes_produce_light(self):
        viz = ChromaBars()
        for i in range(10):
            viz.render(make_frame(rms=0.7, raw_rms=0.3, chroma=_c_major(), timestamp=i * 0.033))
        colors = viz.render(make_frame(rms=0.7, raw_rms=0.3, chroma=_c_major(), timestamp=0.4))
        assert sum(r + g + b for r, g, b in colors) > 0


class TestChordGlow:
    def test_returns_12_tuples(self):
        colors = ChordGlow().render(make_frame(rms=0.5, chroma=_c_major()))
        assert len(colors) == SIDE_LED_COUNT
        assert all(len(c) == 3 for c in colors)

    def test_rgb_in_range(self):
        viz = ChordGlow()
        for i in range(10):
            colors = viz.render(make_frame(rms=0.8, raw_rms=0.5, chroma=_c_major(),
                                       is_beat=True, timestamp=i * 0.033))
        for r, g, b in colors:
            assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255

    def test_silence_is_dark(self):
        viz = ChordGlow()
        for i in range(10):
            viz.render(make_frame(timestamp=i * 0.033))
        colors = viz.render(make_frame(timestamp=0.4))
        assert sum(r + g + b for r, g, b in colors) == 0

    def test_has_name(self):
        assert isinstance(ChordGlow().name, str)

    def test_all_leds_same_color(self):
        """Chord Glow should produce uniform color across all LEDs."""
        viz = ChordGlow()
        for i in range(10):
            viz.render(make_frame(rms=0.7, raw_rms=0.3, chroma=_c_major(), timestamp=i * 0.033))
        colors = viz.render(make_frame(rms=0.7, raw_rms=0.3, chroma=_c_major(), timestamp=0.4))
        assert len(set(colors)) == 1

    def test_beat_boosts(self):
        viz_no = ChordGlow()
        viz_yes = ChordGlow()
        ch = _c_major()
        for viz in (viz_no, viz_yes):
            for i in range(5):
                viz.render(make_frame(rms=0.5, raw_rms=0.3, chroma=ch, timestamp=i * 0.033))
        cn = viz_no.render(make_frame(rms=0.5, raw_rms=0.3, chroma=ch, is_beat=False, timestamp=0.2))
        cy = viz_yes.render(make_frame(rms=0.5, raw_rms=0.3, chroma=ch, is_beat=True, timestamp=0.2))
        assert sum(r + g + b for r, g, b in cy) > sum(r + g + b for r, g, b in cn)
