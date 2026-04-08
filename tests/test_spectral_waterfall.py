"""Tests for the SpectralWaterfall visualizer effect."""

import numpy as np

from nuphy_rgb.audio import AudioFrame, NUM_SPECTRUM_BINS
from nuphy_rgb.effects.spectral_waterfall import SpectralWaterfall
from nuphy_rgb.effects.grid import NUM_ROWS

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


def _loud_spectrum() -> tuple[float, ...]:
    """Spectrum with energy across all bins."""
    return tuple(0.5 for _ in range(NUM_SPECTRUM_BINS))


def _bass_heavy_spectrum() -> tuple[float, ...]:
    """Spectrum with energy concentrated in low bins."""
    return tuple(0.8 if i < 4 else 0.02 for i in range(NUM_SPECTRUM_BINS))


class TestBasicContract:
    def test_returns_84_tuples(self):
        viz = SpectralWaterfall()
        frame = _make_frame(rms=0.5, spectrum=_loud_spectrum())
        colors = viz.render(frame)
        assert len(colors) == NUM_LEDS
        assert all(len(c) == 3 for c in colors)

    def test_rgb_values_in_range(self):
        viz = SpectralWaterfall()
        for i in range(10):
            colors = viz.render(_make_frame(
                rms=0.8, spectrum=_loud_spectrum(), timestamp=i * 0.033,
            ))
        for r, g, b in colors:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_has_name_attribute(self):
        viz = SpectralWaterfall()
        assert isinstance(viz.name, str)
        assert len(viz.name) > 0


class TestSilence:
    def test_silence_is_dark(self):
        viz = SpectralWaterfall()
        for i in range(10):
            colors = viz.render(_make_frame(rms=0.0, timestamp=i * 0.033))
        total = sum(r + g + b for r, g, b in colors)
        assert total == 0


class TestAmplitudeModulation:
    def test_loud_is_brighter_than_quiet(self):
        """Overall brightness should scale with raw_rms."""
        viz_quiet = SpectralWaterfall()
        viz_loud = SpectralWaterfall()
        spec = _loud_spectrum()

        for i in range(10):
            viz_quiet.render(_make_frame(
                rms=0.3, raw_rms=0.1, spectrum=spec, timestamp=i * 0.033,
            ))
            viz_loud.render(_make_frame(
                rms=0.8, raw_rms=0.5, spectrum=spec, timestamp=i * 0.033,
            ))

        colors_quiet = viz_quiet.render(_make_frame(
            rms=0.3, raw_rms=0.1, spectrum=spec, timestamp=0.4,
        ))
        colors_loud = viz_loud.render(_make_frame(
            rms=0.8, raw_rms=0.5, spectrum=spec, timestamp=0.4,
        ))

        brightness_quiet = sum(max(r, g, b) for r, g, b in colors_quiet)
        brightness_loud = sum(max(r, g, b) for r, g, b in colors_loud)
        assert brightness_loud > brightness_quiet * 2

    def test_amplitude_uses_squared_curve(self):
        """Squared curve: half-volume should be ~quarter brightness, not half."""
        viz_half = SpectralWaterfall()
        viz_full = SpectralWaterfall()
        spec = _loud_spectrum()

        for i in range(10):
            viz_half.render(_make_frame(
                rms=0.5, raw_rms=0.15, spectrum=spec, timestamp=i * 0.033,
            ))
            viz_full.render(_make_frame(
                rms=0.9, raw_rms=0.3, spectrum=spec, timestamp=i * 0.033,
            ))

        colors_half = viz_half.render(_make_frame(
            rms=0.5, raw_rms=0.15, spectrum=spec, timestamp=0.4,
        ))
        colors_full = viz_full.render(_make_frame(
            rms=0.9, raw_rms=0.3, spectrum=spec, timestamp=0.4,
        ))

        b_half = sum(max(r, g, b) for r, g, b in colors_half)
        b_full = sum(max(r, g, b) for r, g, b in colors_full)
        # With squared curve, ratio should be closer to 4:1 than 2:1
        assert b_full > b_half * 3


class TestScrolling:
    def test_rows_scroll_downward(self):
        """After feeding one loud frame then silence, the bright row moves down."""
        viz = SpectralWaterfall()
        viz.render(_make_frame(rms=0.8, spectrum=_loud_spectrum(), timestamp=0.0))

        viz.render(_make_frame(rms=0.0, timestamp=0.033))

        assert viz._grid[0].max() < 0.01, "Top row should be near-zero (silence)"
        assert viz._grid[1].max() > 0.1, "Row 1 should have scrolled energy"

    def test_energy_scrolls_through_all_rows(self):
        """A single loud frame eventually reaches the bottom row."""
        viz = SpectralWaterfall()
        viz.render(_make_frame(rms=0.8, spectrum=_loud_spectrum(), timestamp=0.0))

        for i in range(1, NUM_ROWS):
            viz.render(_make_frame(rms=0.0, timestamp=i * 0.033))

        assert viz._grid[NUM_ROWS - 1].max() > 0.01


class TestDynamicRange:
    def test_quiet_bins_still_visible(self):
        """Per-bin AGC + compression should make quiet bins visible."""
        viz = SpectralWaterfall()
        for i in range(20):
            viz.render(_make_frame(
                rms=0.8, spectrum=_bass_heavy_spectrum(), timestamp=i * 0.033,
            ))
        # Right columns (treble) should not be zero — per-bin AGC lifts them
        treble_vals = list(viz._grid[0, 12:])
        assert any(v > 0.05 for v in treble_vals), (
            "Treble columns should be visible after per-bin AGC"
        )

    def test_more_columns_lit_than_raw(self):
        """With compression, more columns should be above the visibility threshold."""
        viz = SpectralWaterfall()
        for i in range(20):
            viz.render(_make_frame(
                rms=0.8, spectrum=_bass_heavy_spectrum(), timestamp=i * 0.033,
            ))
        lit_cols = int(np.sum(viz._grid[0] > 0.05))
        assert lit_cols >= 10, f"Only {lit_cols} columns lit, expected >= 10"


class TestFrequencyMapping:
    def test_left_is_bass_right_is_treble(self):
        """Column 0 should map to the lowest bin, column 15 to the highest."""
        viz = SpectralWaterfall()
        assert viz._col_to_bin[0] == 0
        assert viz._col_to_bin[15] == 15

    def test_bins_increase_left_to_right(self):
        """Bin indices should be monotonically non-decreasing across columns."""
        viz = SpectralWaterfall()
        for i in range(len(viz._col_to_bin) - 1):
            assert viz._col_to_bin[i] <= viz._col_to_bin[i + 1]

    def test_bass_heavy_lights_left_columns(self):
        """Bass-heavy spectrum should have brighter left columns."""
        viz = SpectralWaterfall()
        viz.render(_make_frame(
            rms=0.8, spectrum=_bass_heavy_spectrum(), timestamp=0.0,
        ))
        left_energy = viz._grid[0, :4].sum()
        right_energy = viz._grid[0, 12:].sum()
        assert left_energy > right_energy


class TestBeatInteraction:
    def test_beat_boosts_brightness(self):
        """A beat frame should produce brighter output than a non-beat frame."""
        loud = _loud_spectrum()
        quiet = tuple(0.1 for _ in range(NUM_SPECTRUM_BINS))

        viz_no_beat = SpectralWaterfall()
        viz_beat = SpectralWaterfall()

        for viz in (viz_no_beat, viz_beat):
            for i in range(5):
                viz.render(_make_frame(rms=0.8, spectrum=loud, timestamp=i * 0.033))

        colors_no_beat = viz_no_beat.render(_make_frame(
            rms=0.3, spectrum=quiet, is_beat=False, timestamp=0.2,
        ))
        colors_beat = viz_beat.render(_make_frame(
            rms=0.3, spectrum=quiet, is_beat=True, timestamp=0.2,
        ))

        brightness_no_beat = sum(max(r, g, b) for r, g, b in colors_no_beat)
        brightness_beat = sum(max(r, g, b) for r, g, b in colors_beat)
        assert brightness_beat > brightness_no_beat
