"""Tests for the Pianoroll visualizer effect."""

from helpers import make_frame

from nuphy_rgb.effects.pianoroll import Pianoroll
from nuphy_rgb.effects.pianoroll.effect import (
    DEFAULT_WINDOW_BASE,
    SCROLL_EVERY_N_FRAMES,
)

NUM_LEDS = 84


def _voiced(midi: float, prob: float = 0.9, **kw):
    return make_frame(pitch_midi=midi, voiced_prob=prob, **kw)


class TestBasicContract:
    def test_returns_84_tuples(self):
        viz = Pianoroll()
        colors = viz.render(_voiced(60.0))
        assert len(colors) == NUM_LEDS
        assert all(len(c) == 3 for c in colors)

    def test_rgb_in_range(self):
        viz = Pianoroll()
        for i in range(20):
            colors = viz.render(_voiced(60.0 + i, timestamp=i * 0.033))
        for r, g, b in colors:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_has_name(self):
        assert isinstance(Pianoroll().name, str)


class TestSilence:
    def test_unvoiced_stays_dark(self):
        viz = Pianoroll()
        for i in range(10):
            colors = viz.render(make_frame(timestamp=i * 0.033))
        assert sum(r + g + b for r, g, b in colors) == 0

    def test_low_voicing_does_not_stamp(self):
        viz = Pianoroll()
        for i in range(10):
            colors = viz.render(_voiced(60.0, prob=0.1, timestamp=i * 0.033))
        # Below NEW_NOTE_THRESHOLD: nothing should light up.
        assert sum(r + g + b for r, g, b in colors) == 0


class TestVoicing:
    def test_voiced_note_produces_light(self):
        viz = Pianoroll()
        for i in range(5):
            colors = viz.render(_voiced(60.0, timestamp=i * 0.033))
        assert sum(max(r, g, b) for r, g, b in colors) > 0

    def test_different_pitches_different_output(self):
        viz_c = Pianoroll()
        viz_g = Pianoroll()
        for i in range(5):
            viz_c.render(_voiced(60.0, timestamp=i * 0.033))
            viz_g.render(_voiced(67.0, timestamp=i * 0.033))
        colors_c = viz_c.render(_voiced(60.0, timestamp=0.2))
        colors_g = viz_g.render(_voiced(67.0, timestamp=0.2))
        assert colors_c != colors_g

    def test_silence_after_note_fades(self):
        viz = Pianoroll()
        for i in range(3):
            viz.render(_voiced(60.0, timestamp=i * 0.033))
        lit = viz.render(_voiced(60.0, timestamp=0.1))
        lit_sum = sum(r + g + b for r, g, b in lit)
        # Run many silent frames; brightness must decay substantially.
        for i in range(60):
            viz.render(make_frame(timestamp=0.1 + i * 0.033))
        faded = viz.render(make_frame(timestamp=3.0))
        faded_sum = sum(r + g + b for r, g, b in faded)
        assert faded_sum < lit_sum * 0.1


class TestWindow:
    def test_octave_shift_keeps_note_in_range(self):
        viz = Pianoroll()
        # Feed a note way above the default window (C3..D#4 == 48..63).
        high = DEFAULT_WINDOW_BASE + 30  # MIDI 78
        for i in range(SCROLL_EVERY_N_FRAMES * 2):
            viz.render(_voiced(float(high), timestamp=i * 0.033))
        # Window should have shifted so the note is displayable — meaning
        # *some* cell is lit. Before the fix, a clipped col would also
        # light up, so we additionally assert the window_base moved.
        assert viz._window_base != DEFAULT_WINDOW_BASE
        assert viz._window_base <= high < viz._window_base + 16
