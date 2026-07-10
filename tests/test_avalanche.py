"""Tests for the Avalanche effect (BTW sandpile, self-organized criticality)."""

from __future__ import annotations

import numpy as np
import pytest

from nuphy_rgb.audio import NUM_SPECTRUM_BINS
from nuphy_rgb.effects.avalanche.effect import (
    TOPPLE_THRESHOLD,
    Avalanche,
    mix_hue,
    sample_columns,
    topple_step,
    z_to_value,
)
from nuphy_rgb.effects.grid import MAX_COLS, NUM_ROWS, VALID_MASK
from tests.helpers import make_frame

FPS = 30.0


def _zeros():
    return np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)


def _spectrum(peak_bin: int, level: float = 1.0) -> tuple[float, ...]:
    s = [0.0] * NUM_SPECTRUM_BINS
    s[peak_bin] = level
    return tuple(s)


def _loud(**kwargs):
    base = dict(bass=0.9, rms=0.8, onset_strength=0.5, spectrum=_spectrum(2, 1.0))
    base.update(kwargs)
    return base


def _feed(eff, seconds, start=0.0, beat_every=None, **frame_kwargs):
    """Drive the effect for *seconds* at FPS. Returns the end time."""
    n = int(seconds * FPS)
    last_beat = -1e9
    for i in range(n):
        t = start + i / FPS
        is_beat = False
        if beat_every is not None and t - last_beat >= beat_every:
            is_beat = True
            last_beat = t
        eff.render(make_frame(timestamp=t, is_beat=is_beat, **frame_kwargs))
    return start + n / FPS


class TestZToValue:
    def test_empty_cell_is_dark(self):
        assert z_to_value(np.array([0.0]))[0] == 0.0

    def test_grain_levels(self):
        vals = z_to_value(np.array([1.0, 2.0, 3.0]))
        assert vals == pytest.approx([0.15, 0.4, 0.8])

    def test_above_critical_clamps(self):
        assert z_to_value(np.array([7.0]))[0] == pytest.approx(0.8)

    def test_fractional_interpolates(self):
        assert z_to_value(np.array([1.5]))[0] == pytest.approx(0.275)


class TestMixHue:
    def test_zero_incoming_keeps_resident(self):
        old = np.array([0.3])
        out = mix_hue(old, np.array([2.0]), np.array([0.9]), np.array([0.0]))
        assert out[0] == pytest.approx(0.3)

    def test_zero_total_weight_keeps_resident(self):
        old = np.array([0.3])
        out = mix_hue(old, np.array([0.0]), np.array([0.9]), np.array([0.0]))
        assert out[0] == pytest.approx(0.3)

    def test_equal_weights_meet_in_the_middle(self):
        out = mix_hue(np.array([0.0]), np.array([1.0]), np.array([0.25]), np.array([1.0]))
        assert out[0] == pytest.approx(0.125, abs=1e-6)

    def test_wraparound_mixes_across_zero(self):
        out = mix_hue(np.array([0.95]), np.array([1.0]), np.array([0.05]), np.array([1.0]))
        assert out[0] == pytest.approx(0.0, abs=1e-6) or out[0] == pytest.approx(1.0, abs=1e-6)


class TestSampleColumns:
    def test_zero_spectrum_yields_no_columns(self):
        rng = np.random.default_rng(1)
        assert len(sample_columns((0.0,) * NUM_SPECTRUM_BINS, 5, rng)) == 0

    def test_peaked_spectrum_hits_only_that_column(self):
        rng = np.random.default_rng(1)
        cols = sample_columns(_spectrum(7), 20, rng)
        assert len(cols) == 20
        assert all(c == 7 for c in cols)

    def test_distribution_follows_flattened_spectrum(self):
        # sampling is proportional to sqrt(spectrum): bass dominates highs
        # 3-4x on real music, so linear weighting starves the treble columns
        rng = np.random.default_rng(1)
        s = [0.0] * NUM_SPECTRUM_BINS
        s[0], s[8] = 3.0, 1.0
        cols = sample_columns(tuple(s), 4000, rng)
        frac_low = np.mean(np.asarray(cols) == 0)
        assert 0.58 < frac_low < 0.68  # expect sqrt(3)/(sqrt(3)+1) ~ 0.634

    def test_zero_count_is_empty(self):
        rng = np.random.default_rng(1)
        assert len(sample_columns(_spectrum(7), 0, rng)) == 0


class TestToppleStep:
    def test_stable_pile_unchanged(self):
        z = _zeros()
        z[2, 5] = TOPPLE_THRESHOLD - 1
        hue = _zeros()
        z2, _, toppled = topple_step(z, hue, gravity_bias=0.0)
        assert np.array_equal(z2, z)
        assert not toppled.any()

    def test_isotropic_topple_conserves_interior_grains(self):
        z = _zeros()
        z[2, 5] = TOPPLE_THRESHOLD
        z2, _, toppled = topple_step(z, _zeros(), gravity_bias=0.0)
        assert toppled[2, 5]
        assert z2[2, 5] == 0.0
        for r, c in [(1, 5), (3, 5), (2, 4), (2, 6)]:
            assert z2[r, c] == pytest.approx(1.0)
        assert z2.sum() == pytest.approx(4.0)

    def test_full_gravity_sends_double_down_none_up(self):
        z = _zeros()
        z[2, 5] = TOPPLE_THRESHOLD
        z2, _, _ = topple_step(z, _zeros(), gravity_bias=1.0)
        assert z2[3, 5] == pytest.approx(2.0)
        assert z2[1, 5] == pytest.approx(0.0)
        assert z2[2, 4] == pytest.approx(1.0)
        assert z2[2, 6] == pytest.approx(1.0)

    def test_half_gravity_splits_vertical_shares(self):
        z = _zeros()
        z[2, 5] = TOPPLE_THRESHOLD
        z2, _, _ = topple_step(z, _zeros(), gravity_bias=0.5)
        assert z2[3, 5] == pytest.approx(1.5)
        assert z2[1, 5] == pytest.approx(0.5)

    def test_corner_topple_loses_offgrid_grains(self):
        z = _zeros()
        z[0, 0] = TOPPLE_THRESHOLD
        z2, _, _ = topple_step(z, _zeros(), gravity_bias=0.0)
        # up and left shares fall off the grid
        assert z2.sum() == pytest.approx(2.0)
        assert z2[1, 0] == pytest.approx(1.0)
        assert z2[0, 1] == pytest.approx(1.0)

    def test_grains_into_row_gaps_are_lost(self):
        # (4, 12) is valid (row 4 has 14 cols) but (5, 12) is not (row 5 has 10)
        assert VALID_MASK[4, 12] and not VALID_MASK[5, 12]
        z = _zeros()
        z[4, 12] = TOPPLE_THRESHOLD
        z2, _, _ = topple_step(z, _zeros(), gravity_bias=1.0)
        # both down-grains vanish into the gap; only left/right survive
        assert z2.sum() == pytest.approx(2.0)
        assert z2[4, 11] == pytest.approx(1.0)
        assert z2[4, 13] == pytest.approx(1.0)

    def test_cascade_propagates_one_sweep_per_call(self):
        z = _zeros()
        z[2, 5] = TOPPLE_THRESHOLD
        z[2, 6] = TOPPLE_THRESHOLD - 1
        z2, _, toppled1 = topple_step(z, _zeros(), gravity_bias=0.0)
        # neighbor reaches threshold but must not topple within the same sweep
        assert toppled1[2, 5] and not toppled1[2, 6]
        assert z2[2, 6] == pytest.approx(TOPPLE_THRESHOLD)
        z3, _, toppled2 = topple_step(z2, _zeros(), gravity_bias=0.0)
        assert toppled2[2, 6]
        assert z3[2, 6] == 0.0

    def test_simultaneous_topples_both_fire(self):
        z = _zeros()
        z[2, 5] = TOPPLE_THRESHOLD
        z[2, 8] = TOPPLE_THRESHOLD
        _, _, toppled = topple_step(z, _zeros(), gravity_bias=0.0)
        assert toppled[2, 5] and toppled[2, 8]

    def test_fresh_weight_pulls_hue_toward_incoming(self):
        # resident 2 grains of red (0.0) receive sand from a toppling
        # neighbor of hue 0.25; heavier fresh weight = stronger recolor
        def mixed_hue(fresh_weight):
            z = _zeros()
            z[2, 5] = TOPPLE_THRESHOLD
            z[2, 6] = 2.0
            hue = _zeros()
            hue[2, 5] = 0.25
            _, hue2, _ = topple_step(z, hue, gravity_bias=0.0, fresh_weight=fresh_weight)
            return hue2[2, 6]

        assert mixed_hue(6.0) > mixed_hue(1.0)

    def test_hue_travels_with_the_sand(self):
        z = _zeros()
        z[2, 5] = TOPPLE_THRESHOLD
        hue = _zeros()
        hue[2, 5] = 0.6
        _, hue2, _ = topple_step(z, hue, gravity_bias=0.0)
        for r, c in [(1, 5), (3, 5), (2, 4), (2, 6)]:
            assert hue2[r, c] == pytest.approx(0.6, abs=1e-6)


class TestProtocol:
    def test_name_and_render_shape(self):
        eff = Avalanche()
        assert isinstance(eff.name, str)
        leds = eff.render(make_frame(timestamp=0.0, **_loud()))
        assert len(leds) == 84
        assert all(0 <= v <= 255 for led in leds for v in led)

    def test_initial_silence_is_dark(self):
        eff = Avalanche()
        leds = eff.render(make_frame(timestamp=0.0))
        assert sum(sum(led) for led in leds) == 0

    def test_deterministic_across_instances(self):
        a, b = Avalanche(), Avalanche()
        _feed(a, 2.0, beat_every=0.5, **_loud())
        _feed(b, 2.0, beat_every=0.5, **_loud())
        frame = make_frame(timestamp=2.01, **_loud())
        assert a.render(frame) == b.render(frame)


class TestDynamics:
    def test_loud_music_deposits_sand(self):
        eff = Avalanche()
        _feed(eff, 2.0, **_loud())
        assert eff._z.sum() > 0

    def test_sand_lands_where_the_spectrum_says(self):
        eff = Avalanche()
        _feed(eff, 1.0, **_loud(spectrum=_spectrum(11)))
        col_sums = eff._z.sum(axis=0)
        total = col_sums.sum()
        assert total > 0
        # the pile peaks at the deposit column; avalanches may spread it,
        # but the far field must stay essentially empty
        assert 10 <= int(np.argmax(col_sums)) <= 12
        assert col_sums[:5].sum() < 0.05 * total

    def test_beat_drops_a_clump(self):
        # The clump may topple within the same frame, so assert on the total
        # grain mass and its locality, not the deposit cell itself.
        eff = Avalanche()
        eff.render(make_frame(timestamp=0.0, is_beat=True, rms=0.8, spectrum=_spectrum(7)))
        assert eff._z.sum() >= TOPPLE_THRESHOLD
        lit_cols = np.nonzero(eff._z.sum(axis=0))[0]
        assert len(lit_cols) > 0
        assert all(6 <= c <= 8 for c in lit_cols)

    def test_beatless_frame_deposits_less(self):
        eff = Avalanche()
        eff.render(make_frame(timestamp=0.0, is_beat=False, rms=0.8, spectrum=_spectrum(7)))
        assert eff._z.sum() < TOPPLE_THRESHOLD

    def test_no_rain_without_spectrum(self):
        eff = Avalanche()
        _feed(eff, 1.0, rms=0.8, onset_strength=0.5)  # loud but spectrally empty
        assert eff._z.sum() == 0

    def test_sustained_loud_music_triggers_avalanches(self):
        eff = Avalanche()
        _feed(eff, 8.0, beat_every=0.5, **_loud())
        assert eff._topple_count > 0

    def test_silence_decays_to_black(self):
        eff = Avalanche()
        _feed(eff, 2.0, beat_every=0.5, **_loud())
        _feed(eff, 4.0, start=2.0)
        leds = eff.render(make_frame(timestamp=6.01))
        assert sum(sum(led) for led in leds) == 0

    def test_silence_evaporates_grains(self):
        eff = Avalanche()
        _feed(eff, 2.0, beat_every=0.5, **_loud())
        before = eff._z.sum()
        assert before > 0
        _feed(eff, 10.0, start=2.0)
        assert eff._z.sum() < before
