"""Tests for the Chromatic Keys visualizer effect."""

from helpers import make_frame

from nuphy_rgb.effects.chromatic_keys import ChromaticKeys

NUM_LEDS = 84


def _c_major() -> tuple[float, ...]:
    vals = [0.0] * 12
    vals[0] = 0.9   # C
    vals[4] = 0.7   # E
    vals[7] = 0.8   # G
    return tuple(vals)


def _single_note(idx, energy=0.9) -> tuple[float, ...]:
    vals = [0.0] * 12
    vals[idx] = energy
    return tuple(vals)


class TestBasicContract:
    def test_returns_84_tuples(self):
        viz = ChromaticKeys()
        colors = viz.render(make_frame(rms=0.5, chroma=_c_major()))
        assert len(colors) == NUM_LEDS
        assert all(len(c) == 3 for c in colors)

    def test_rgb_in_range(self):
        viz = ChromaticKeys()
        for i in range(10):
            colors = viz.render(make_frame(
                rms=0.8, raw_rms=0.5, chroma=_c_major(),
                is_beat=True, timestamp=i * 0.033,
            ))
        for r, g, b in colors:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_has_name(self):
        assert isinstance(ChromaticKeys().name, str)


class TestSilence:
    def test_silence_is_dark(self):
        viz = ChromaticKeys()
        for i in range(10):
            colors = viz.render(make_frame(rms=0.0, timestamp=i * 0.033))
        assert sum(r + g + b for r, g, b in colors) == 0


class TestChromaMapping:
    def test_active_notes_produce_light(self):
        viz = ChromaticKeys()
        for i in range(5):
            viz.render(make_frame(rms=0.7, raw_rms=0.3, chroma=_c_major(), timestamp=i * 0.033))
        colors = viz.render(make_frame(rms=0.7, raw_rms=0.3, chroma=_c_major(), timestamp=0.2))
        assert sum(max(r, g, b) for r, g, b in colors) > 0

    def test_different_notes_different_patterns(self):
        viz_c = ChromaticKeys()
        viz_a = ChromaticKeys()
        for i in range(5):
            viz_c.render(make_frame(rms=0.7, raw_rms=0.3, chroma=_single_note(0), timestamp=i * 0.033))
            viz_a.render(make_frame(rms=0.7, raw_rms=0.3, chroma=_single_note(9), timestamp=i * 0.033))
        colors_c = viz_c.render(make_frame(rms=0.7, raw_rms=0.3, chroma=_single_note(0), timestamp=0.2))
        colors_a = viz_a.render(make_frame(rms=0.7, raw_rms=0.3, chroma=_single_note(9), timestamp=0.2))
        assert colors_c != colors_a


class TestAmplitude:
    def test_loud_brighter_than_quiet(self):
        viz_q = ChromaticKeys()
        viz_l = ChromaticKeys()
        ch = _c_major()
        for i in range(10):
            viz_q.render(make_frame(rms=0.3, raw_rms=0.1, chroma=ch, timestamp=i * 0.033))
            viz_l.render(make_frame(rms=0.8, raw_rms=0.5, chroma=ch, timestamp=i * 0.033))
        cq = viz_q.render(make_frame(rms=0.3, raw_rms=0.1, chroma=ch, timestamp=0.4))
        cl = viz_l.render(make_frame(rms=0.8, raw_rms=0.5, chroma=ch, timestamp=0.4))
        assert sum(max(r, g, b) for r, g, b in cl) > sum(max(r, g, b) for r, g, b in cq)


class TestBeat:
    def test_beat_boosts(self):
        viz_no = ChromaticKeys()
        viz_yes = ChromaticKeys()
        ch = _c_major()
        for viz in (viz_no, viz_yes):
            for i in range(5):
                viz.render(make_frame(rms=0.5, raw_rms=0.3, chroma=ch, timestamp=i * 0.033))
        cn = viz_no.render(make_frame(rms=0.5, raw_rms=0.3, chroma=ch, is_beat=False, timestamp=0.2))
        cy = viz_yes.render(make_frame(rms=0.5, raw_rms=0.3, chroma=ch, is_beat=True, timestamp=0.2))
        assert sum(max(r, g, b) for r, g, b in cy) > sum(max(r, g, b) for r, g, b in cn)
