"""Tests for the Fireflies effect (Kuramoto oscillators)."""

from __future__ import annotations

import colorsys

import numpy as np
import pytest

from nuphy_rgb.effects.fireflies.effect import (
    Fireflies,
    columns_due,
    fold_rate,
    smoothstep,
)
from nuphy_rgb.effects.grid import MAX_COLS, NUM_ROWS
from tests.helpers import make_frame

FPS = 30.0


def _feed(eff, seconds, start=0.0, beat_period=0.0, beat_every=None, **frame_kwargs):
    """Drive the effect for *seconds* at FPS. Returns the end time."""
    n = int(seconds * FPS)
    last_beat = -1e9
    for i in range(n):
        t = start + i / FPS
        is_beat = False
        if beat_every is not None and t - last_beat >= beat_every:
            is_beat = True
            last_beat = t
        eff.render(
            make_frame(
                timestamp=t,
                is_beat=is_beat,
                beat_period=beat_period,
                **frame_kwargs,
            )
        )
    return start + n / FPS


def _loud(**kwargs):
    return dict(bass=0.9, rms=0.8, dominant_freq=220.0, **kwargs)


class TestFoldRate:
    def test_in_range_untouched(self):
        assert fold_rate(1.3, 0.8, 2.2) == pytest.approx(1.3)

    def test_fast_rate_folds_down(self):
        # 170 BPM = 2.833 Hz -> flash every 2nd beat
        assert fold_rate(2.833, 0.8, 2.2) == pytest.approx(1.4165)

    def test_slow_rate_folds_up(self):
        assert fold_rate(0.5, 0.8, 2.2) == pytest.approx(1.0)

    def test_very_fast_folds_twice(self):
        assert fold_rate(5.0, 0.8, 2.2) == pytest.approx(1.25)

    def test_zero_returns_zero(self):
        assert fold_rate(0.0, 0.8, 2.2) == 0.0


class TestSmoothstep:
    def test_below_lo_is_zero(self):
        assert smoothstep(0.1, 0.35, 0.7) == 0.0

    def test_above_hi_is_one(self):
        assert smoothstep(0.9, 0.35, 0.7) == 1.0

    def test_midpoint_is_half(self):
        assert smoothstep(0.525, 0.35, 0.7) == pytest.approx(0.5)

    def test_monotonic(self):
        xs = np.linspace(0.0, 1.0, 50)
        ys = [smoothstep(x, 0.35, 0.7) for x in xs]
        assert all(b >= a for a, b in zip(ys, ys[1:]))


class TestColumnsDue:
    def test_first_column_due_at_sweep_start(self):
        assert columns_due(1.0, 0.03, 0.99, 1.0) == [0]

    def test_columns_arrive_in_order(self):
        # window covers columns 2 and 3 (t = 1.06, 1.09)
        assert columns_due(1.0, 0.03, 1.05, 1.10) == [2, 3]

    def test_zero_delay_kicks_all_at_once(self):
        assert columns_due(1.0, 0.0, 0.99, 1.0) == list(range(MAX_COLS))

    def test_nothing_before_sweep_start(self):
        assert columns_due(1.0, 0.03, 0.5, 0.9) == []

    def test_nothing_after_sweep_finished(self):
        assert columns_due(1.0, 0.03, 2.0, 2.1) == []


class TestNeighborCoupling:
    def test_columns_do_not_wrap(self):
        eff = Fireflies()
        phase = np.zeros((NUM_ROWS, MAX_COLS))
        phase[:, -1] = np.pi / 2  # wild phase on the far right edge
        coupling = eff._neighbor_coupling(phase)
        # col 0 only sees rows above/below (same phase) and col 1 (same
        # phase) -- the col 15 outlier must not leak around the edge.
        assert np.allclose(coupling[:, 0], 0.0)

    def test_rows_wrap(self):
        eff = Fireflies()
        phase = np.zeros((NUM_ROWS, MAX_COLS))
        phase[0, :] = np.pi / 2
        coupling = eff._neighbor_coupling(phase)
        # row 5 must feel row 0 through the row wrap
        assert np.all(coupling[NUM_ROWS - 1, :] > 0.0)

    def test_uniform_field_has_zero_coupling(self):
        eff = Fireflies()
        phase = np.full((NUM_ROWS, MAX_COLS), 1.234)
        assert np.allclose(eff._neighbor_coupling(phase), 0.0)


class TestProtocol:
    def test_name_and_render_shape(self):
        eff = Fireflies()
        assert isinstance(eff.name, str)
        leds = eff.render(make_frame(timestamp=0.0, **_loud()))
        assert len(leds) == 84
        assert all(0 <= v <= 255 for led in leds for v in led)

    def test_silence_is_dark(self):
        eff = Fireflies()
        _feed(eff, 1.0)
        leds = eff.render(make_frame(timestamp=1.01))
        assert sum(sum(led) for led in leds) == 0

    def test_deterministic_across_instances(self):
        a, b = Fireflies(), Fireflies()
        _feed(a, 1.0, beat_every=0.5, beat_period=0.5, **_loud())
        _feed(b, 1.0, beat_every=0.5, beat_period=0.5, **_loud())
        frame = make_frame(timestamp=1.01, **_loud())
        assert a.render(frame) == b.render(frame)


class TestRegimes:
    def test_loud_beats_lock_the_swarm(self):
        eff = Fireflies()
        _feed(eff, 4.0, beat_every=0.5, beat_period=0.5, **_loud())
        assert eff._order > 0.85

    def test_quiet_dissolves_quickly(self):
        eff = Fireflies()
        _feed(eff, 4.0, beat_every=0.5, beat_period=0.5, **_loud())
        assert eff._order > 0.85
        _feed(eff, 1.5, start=4.0)
        assert eff._order < 0.25

    def test_drive_rate_follows_beat_period(self):
        eff = Fireflies()
        # 0.4 s beats = 2.5 Hz, folds to 1.25 Hz
        _feed(eff, 4.0, beat_every=0.4, beat_period=0.4, **_loud())
        assert eff._rate == pytest.approx(1.25, abs=0.05)

    def test_fallback_rate_without_beat_period(self):
        eff = Fireflies()
        _feed(eff, 2.0, **_loud())
        assert eff._rate == pytest.approx(eff.params["tempo"].value, abs=0.05)


class TestScramble:
    def test_section_change_scrambles_once(self):
        eff = Fireflies()
        _feed(eff, 4.0, beat_every=0.5, beat_period=0.5, **_loud())
        order_locked = eff._order
        assert order_locked > 0.85
        eff.render(make_frame(timestamp=4.01, timbral_change=0.9, **_loud()))
        first_scramble = eff._last_scramble
        assert first_scramble == pytest.approx(4.01)
        # A second trigger inside the cooldown must not re-fire
        eff.render(make_frame(timestamp=4.05, timbral_change=0.9, **_loud()))
        assert eff._last_scramble == first_scramble

    def test_scramble_drops_order(self):
        eff = Fireflies()
        _feed(eff, 4.0, beat_every=0.5, beat_period=0.5, **_loud())
        locked = eff._order
        assert locked > 0.85
        # The smoothed order dips over a few frames, then strong coupling
        # re-gathers the swarm -- assert the depth of the disruption.
        dip = locked
        for i in range(10):
            eff.render(
                make_frame(
                    timestamp=4.01 + i / FPS,
                    timbral_change=0.9 if i == 0 else 0.0,
                    **_loud(),
                )
            )
            dip = min(dip, eff._order)
        assert dip < locked - 0.25
        assert dip < 0.7


def _lit_hues(leds):
    hues = []
    for r, g, b in leds:
        if r + g + b > 30:
            h, _, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            hues.append(h)
    return hues


class TestHueScatter:
    def test_locked_swarm_is_monochrome(self):
        eff = Fireflies()
        _feed(eff, 4.0, beat_every=0.5, beat_period=0.5, **_loud())
        # A locked swarm is dark together between flashes -- scan one full
        # cycle and judge the frame where the most fireflies are lit.
        best: list[float] = []
        for i in range(int(FPS)):
            leds = eff.render(make_frame(timestamp=4.0 + (i + 1) / FPS, **_loud()))
            hues = _lit_hues(leds)
            if len(hues) > len(best):
                best = hues
        assert len(best) > 10
        assert np.std(best) < 0.03

    def test_desynced_swarm_is_scattered(self):
        eff = Fireflies()
        # loud (visible) but beatless and incoherent: force low order by
        # feeding quiet to dissolve, then sample with brightness restored
        _feed(eff, 4.0, beat_every=0.5, beat_period=0.5, **_loud())
        _feed(eff, 2.0, start=4.0, rms=0.15, bass=0.1)
        assert eff._order < 0.3
        leds = eff.render(make_frame(timestamp=6.01, rms=0.6, bass=0.2, dominant_freq=220.0))
        hues = _lit_hues(leds)
        assert len(hues) > 5
        assert np.std(hues) > 0.04
