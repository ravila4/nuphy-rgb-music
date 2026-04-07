"""Tests for the Cathedral of Spores reaction-diffusion visualizer."""

import numpy as np

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.cathedral_of_spores import CathedralOfSpores, _laplacian
from nuphy_rgb.effects.grid import MAX_COLS, NUM_LEDS, NUM_ROWS, gradient_mag

NUM_LEDS_EXPECTED = 84


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame(**kwargs) -> AudioFrame:
    defaults = dict(
        bass=0.0, mids=0.0, highs=0.0,
        dominant_freq=0.0, rms=0.0, is_beat=False, timestamp=1.0,
    )
    defaults.update(kwargs)
    return AudioFrame(**defaults)


def _silence_frame(t: float = 1.0) -> AudioFrame:
    return _make_frame(timestamp=t)


def _loud_frame(t: float = 1.0) -> AudioFrame:
    return _make_frame(
        bass=1.0, mids=1.0, highs=1.0,
        dominant_freq=440.0, rms=1.0, is_beat=False, timestamp=t,
    )


# ---------------------------------------------------------------------------
# Basic interface
# ---------------------------------------------------------------------------

class TestBasicInterface:
    def test_returns_84_tuples(self):
        viz = CathedralOfSpores()
        colors = viz.render(_silence_frame())
        assert len(colors) == NUM_LEDS_EXPECTED
        assert all(len(c) == 3 for c in colors)

    def test_rgb_values_in_range(self):
        viz = CathedralOfSpores()
        frame = _make_frame(bass=0.5, mids=0.3, highs=0.2, rms=0.6,
                            dominant_freq=440.0, timestamp=1.0)
        # Warm up a few frames
        for i in range(10):
            viz.render(_make_frame(bass=0.5, rms=0.5, timestamp=1.0 + i * 0.016))
        colors = viz.render(frame)
        for r, g, b in colors:
            assert 0 <= r <= 255, f"R out of range: {r}"
            assert 0 <= g <= 255, f"G out of range: {g}"
            assert 0 <= b <= 255, f"B out of range: {b}"

    def test_has_name_attribute(self):
        viz = CathedralOfSpores()
        assert hasattr(viz, "name")
        assert isinstance(viz.name, str)
        assert len(viz.name) > 0


# ---------------------------------------------------------------------------
# Silence behaviour
# ---------------------------------------------------------------------------

class TestSilence:
    def test_silence_does_not_crash(self):
        viz = CathedralOfSpores()
        for i in range(100):
            frame = _silence_frame(t=1.0 + i * 0.016)
            colors = viz.render(frame)
            assert len(colors) == NUM_LEDS_EXPECTED

    def test_silence_is_dark(self):
        """Silence should be darker than loud audio with beats.

        In a Gray-Scott system, silence keeps B near zero. The growth signal
        (a - b*0.7) stays low when no colonies are being seeded (low B), even
        though A drifts upward via the feed term.  We compare silence against a
        loud beat-driven run: silence must be strictly dimmer.
        """
        # Run silence -- no beats, no audio energy
        viz_silent = CathedralOfSpores()
        for i in range(50):
            viz_silent.render(_silence_frame(t=1.0 + i * 0.016))
        colors_silent = viz_silent.render(_silence_frame(t=1.0 + 50 * 0.016))
        brightness_silent = sum(max(r, g, b) for r, g, b in colors_silent)

        # Run loud audio with beats to activate colonies
        viz_loud = CathedralOfSpores()
        for i in range(50):
            t = 1.0 + i * 0.016
            viz_loud.render(
                _make_frame(bass=1.0, mids=1.0, highs=1.0, rms=1.0,
                            dominant_freq=440.0, is_beat=(i % 8 == 0), timestamp=t)
            )
        colors_loud = viz_loud.render(
            _make_frame(bass=1.0, mids=1.0, highs=1.0, rms=1.0,
                        dominant_freq=440.0, is_beat=True, timestamp=1.0 + 50 * 0.016)
        )
        brightness_loud = sum(max(r, g, b) for r, g, b in colors_loud)

        assert brightness_silent < brightness_loud, (
            f"Silence ({brightness_silent}) should be dimmer than loud+beat ({brightness_loud})"
        )


# ---------------------------------------------------------------------------
# Beat seeding
# ---------------------------------------------------------------------------

class TestBeatSeeding:
    def test_beat_seeds_colony(self):
        """Brightness should increase after a beat compared to no beat."""
        def avg_brightness(colors):
            return sum(max(r, g, b) for r, g, b in colors) / len(colors)

        # Run two identical instances to the same state
        viz_beat = CathedralOfSpores()
        viz_no_beat = CathedralOfSpores()

        # Stabilise both with silence
        for i in range(20):
            t = 1.0 + i * 0.016
            f = _silence_frame(t=t)
            viz_beat.render(f)
            viz_no_beat.render(f)

        t_next = 1.0 + 20 * 0.016
        colors_beat = viz_beat.render(
            _make_frame(bass=0.5, rms=0.5, is_beat=True,
                        dominant_freq=200.0, timestamp=t_next)
        )
        colors_no_beat = viz_no_beat.render(
            _make_frame(bass=0.5, rms=0.5, is_beat=False,
                        dominant_freq=200.0, timestamp=t_next)
        )

        bright_beat = avg_brightness(colors_beat)
        bright_no_beat = avg_brightness(colors_no_beat)
        assert bright_beat >= bright_no_beat, (
            f"Beat frame ({bright_beat:.1f}) should be >= no-beat ({bright_no_beat:.1f})"
        )


# ---------------------------------------------------------------------------
# Field boundedness
# ---------------------------------------------------------------------------

class TestFieldBounds:
    def test_fields_stay_bounded_silence(self):
        """_a and _b must remain in [0, 1] after 200 silent frames."""
        viz = CathedralOfSpores()
        for i in range(200):
            viz.render(_silence_frame(t=1.0 + i * 0.016))
        assert np.all(viz._a >= 0.0), "A field went negative"
        assert np.all(viz._a <= 1.0), "A field exceeded 1"
        assert np.all(viz._b >= 0.0), "B field went negative"
        assert np.all(viz._b <= 1.0), "B field exceeded 1"

    def test_fields_stay_bounded_extreme_audio(self):
        """_a and _b must remain in [0, 1] even with all-maxed audio."""
        viz = CathedralOfSpores()
        for i in range(200):
            t = 1.0 + i * 0.016
            viz.render(_loud_frame(t=t))
        assert np.all(viz._a >= 0.0), "A field went negative under extreme audio"
        assert np.all(viz._a <= 1.0), "A field exceeded 1 under extreme audio"
        assert np.all(viz._b >= 0.0), "B field went negative under extreme audio"
        assert np.all(viz._b <= 1.0), "B field exceeded 1 under extreme audio"


# ---------------------------------------------------------------------------
# Unit tests for private spatial helpers
# ---------------------------------------------------------------------------

class TestLaplacian:
    def test_laplacian_flat_field_is_zero(self):
        """Laplacian of a uniform field must be zero everywhere."""
        field = np.ones((NUM_ROWS, MAX_COLS), dtype=np.float32) * 0.5
        lap = _laplacian(field)
        np.testing.assert_allclose(lap, 0.0, atol=1e-6,
                                   err_msg="Laplacian of flat field should be zero")


class TestGradientMag:
    def test_gradient_mag_flat_is_zero(self):
        """Gradient magnitude of a uniform field must be zero everywhere."""
        field = np.ones((NUM_ROWS, MAX_COLS), dtype=np.float32) * 0.7
        gm = gradient_mag(field)
        np.testing.assert_allclose(gm, 0.0, atol=1e-6,
                                   err_msg="gradient_mag of flat field should be zero")
