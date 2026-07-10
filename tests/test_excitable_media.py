"""Tests for the Excitable Media effect (Greenberg-Hastings cellular automaton).

The state machine lives in pure top-level functions so the wave dynamics can be
checked in isolation; the class is exercised through the Visualizer protocol and
a handful of behavioural (silence/ignition/decay) tests.
"""

from __future__ import annotations

import numpy as np
import pytest

from nuphy_rgb.effects.excitable_media.effect import (
    _SAT_EXCITED,
    _SAT_WAKE,
    _V_CREST,
    _V_WAKE,
    ExcitableMedia,
    excited_neighbor_count,
    seed_noise,
    spawn_front,
    state_to_sat,
    state_to_value,
    step,
)
from nuphy_rgb.effects.grid import MAX_COLS, NUM_ROWS, VALID_MASK
from tests.helpers import make_frame

FPS = 30.0


def _zeros() -> np.ndarray:
    return np.zeros((NUM_ROWS, MAX_COLS), dtype=np.int32)


def _loud(**kwargs):
    base = dict(
        rms=0.8, raw_rms=0.8, bass=0.7, onset_strength=0.6,
        dominant_freq=220.0,
    )
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


class TestExcitedNeighborCount:
    def test_isolated_cell_lights_its_four_neighbors(self):
        excited = np.zeros((NUM_ROWS, MAX_COLS), dtype=bool)
        excited[2, 5] = True
        count = excited_neighbor_count(excited)
        assert count[1, 5] == 1
        assert count[3, 5] == 1
        assert count[2, 4] == 1
        assert count[2, 6] == 1
        # the cell itself has no excited neighbours
        assert count[2, 5] == 0
        # diagonals are NOT von-Neumann neighbours
        assert count[1, 4] == 0

    def test_edge_cell_has_no_offgrid_neighbors(self):
        excited = np.zeros((NUM_ROWS, MAX_COLS), dtype=bool)
        excited[0, 0] = True
        count = excited_neighbor_count(excited)
        assert count[1, 0] == 1
        assert count[0, 1] == 1
        # only two in-grid neighbours exist; nothing wraps
        assert count.sum() == 2

    def test_two_excited_neighbors_sum(self):
        excited = np.zeros((NUM_ROWS, MAX_COLS), dtype=bool)
        excited[2, 4] = True
        excited[2, 6] = True
        count = excited_neighbor_count(excited)
        assert count[2, 5] == 2


class TestStep:
    # E=1, R=3 -> N=5: state 0 rest, 1 excited, 2/3/4 refractory
    E, N = 1, 5

    def test_single_seed_expands_into_a_ring(self):
        state = _zeros()
        state[2, 5] = 1
        out = step(state, self.E, self.N, threshold=1)
        # the seed ages into refractory...
        assert out[2, 5] == 2
        # ...and its four neighbours ignite
        for r, c in [(1, 5), (3, 5), (2, 4), (2, 6)]:
            assert out[r, c] == 1

    def test_excited_ages_to_refractory(self):
        state = _zeros()
        state[2, 5] = 1
        out = step(state, self.E, self.N, threshold=1)
        assert out[2, 5] == 2

    def test_last_refractory_returns_to_rest(self):
        state = _zeros()
        state[2, 5] = self.N - 1  # 4, last refractory
        out = step(state, self.E, self.N, threshold=1)
        assert out[2, 5] == 0

    def test_refractory_cell_does_not_reignite(self):
        state = _zeros()
        state[2, 5] = 1  # excited
        state[2, 6] = 2  # refractory, adjacent to the excited cell
        out = step(state, self.E, self.N, threshold=1)
        # it keeps aging around the cycle, it does NOT reset to excited
        assert out[2, 6] == 3

    def test_below_threshold_does_not_ignite(self):
        state = _zeros()
        state[2, 5] = 1  # a single excited neighbour
        out = step(state, self.E, self.N, threshold=2)
        assert out[2, 4] == 0  # only one excited neighbour, threshold 2
        assert out[2, 5] == 2  # but the seed still ages

    def test_at_threshold_ignites(self):
        state = _zeros()
        state[2, 4] = 1
        state[2, 6] = 1  # (2,5) now has two excited neighbours
        out = step(state, self.E, self.N, threshold=2)
        assert out[2, 5] == 1

    def test_invalid_cells_stay_resting(self):
        # (4,12) is valid, (5,12) is a modifier-row gap
        assert VALID_MASK[4, 12] and not VALID_MASK[5, 12]
        state = _zeros()
        state[4, 12] = 1  # excited, adjacent to the invalid cell below
        out = step(state, self.E, self.N, threshold=1)
        assert out[5, 12] == 0


class TestStateToValue:
    E, N = 1, 5  # R=3

    def test_resting_is_black(self):
        assert state_to_value(np.array([[0]]), self.E, self.N)[0, 0] == 0.0

    def test_excited_is_crest(self):
        assert state_to_value(np.array([[1]]), self.E, self.N)[0, 0] == pytest.approx(_V_CREST)

    def test_refractory_ramps_down(self):
        vals = state_to_value(np.array([[2, 3, 4]]), self.E, self.N)[0]
        # first refractory phase is brightest, fades toward rest
        assert vals[0] == pytest.approx(_V_WAKE)          # k=1 -> 0.6
        assert vals[1] == pytest.approx(_V_WAKE * 2 / 3)  # k=2 -> 0.4
        assert vals[2] == pytest.approx(_V_WAKE * 1 / 3)  # k=3 -> 0.2
        assert vals[0] > vals[1] > vals[2] > 0.0


class TestStateToSat:
    def test_excited_crest_is_desaturated(self):
        assert state_to_sat(np.array([[1]]), 1)[0, 0] == pytest.approx(_SAT_EXCITED)

    def test_refractory_wake_is_saturated(self):
        assert state_to_sat(np.array([[2]]), 1)[0, 0] == pytest.approx(_SAT_WAKE)


class TestSpawnFront:
    def test_full_front_is_all_excited(self):
        state = _zeros()
        spawn_front(state, r0=1, c0=8, length=4, gap_frac=0.0, n_excited=1)
        for r in range(1, 5):
            assert state[r, 8] == 1

    def test_broken_front_caps_one_end_with_refractory(self):
        state = _zeros()
        spawn_front(state, r0=1, c0=8, length=4, gap_frac=0.5, n_excited=1)
        # top half refractory (E+1=2), bottom half excited -> a free lower end
        assert state[1, 8] == 2
        assert state[2, 8] == 2
        assert state[3, 8] == 1
        assert state[4, 8] == 1

    def test_only_the_target_column_is_touched(self):
        state = _zeros()
        spawn_front(state, r0=0, c0=8, length=4, gap_frac=0.0, n_excited=1)
        assert state[:, 7].sum() == 0
        assert state[:, 9].sum() == 0

    def test_offgrid_and_invalid_cells_are_skipped(self):
        state = _zeros()
        # column 12: rows 0-4 valid, row 5 is a gap; length 8 overruns the grid
        spawn_front(state, r0=0, c0=12, length=8, gap_frac=0.0, n_excited=1)
        assert state[5, 12] == 0  # invalid gap untouched
        assert state.shape == (NUM_ROWS, MAX_COLS)  # no out-of-bounds write


class TestSeedNoise:
    def test_full_active_frac_excites_every_valid_cell(self):
        state = _zeros()
        rng = np.random.default_rng(1)
        seed_noise(state, rng, active_frac=1.0, refractory_frac=0.0, n_excited=1, n_states=5)
        assert np.all(state[VALID_MASK] == 1)
        assert np.all(state[~VALID_MASK] == 0)

    def test_zero_fracs_leave_medium_untouched(self):
        state = _zeros()
        rng = np.random.default_rng(1)
        seed_noise(state, rng, active_frac=0.0, refractory_frac=0.0, n_excited=1, n_states=5)
        assert state.sum() == 0

    def test_is_deterministic_for_a_given_rng(self):
        a, b = _zeros(), _zeros()
        seed_noise(a, np.random.default_rng(7), 0.1, 0.1, 1, 5)
        seed_noise(b, np.random.default_rng(7), 0.1, 0.1, 1, 5)
        assert np.array_equal(a, b)


class TestProtocol:
    def test_name_and_render_shape(self):
        eff = ExcitableMedia()
        leds = eff.render(make_frame(timestamp=0.0, **_loud()))
        assert isinstance(eff.name, str)
        assert len(leds) == 84
        assert all(0 <= v <= 255 for led in leds for v in led)

    def test_initial_silence_is_dark(self):
        eff = ExcitableMedia()
        leds = eff.render(make_frame(timestamp=0.0))
        assert sum(sum(led) for led in leds) == 0

    def test_deterministic_across_instances(self):
        a, b = ExcitableMedia(), ExcitableMedia()
        _feed(a, 2.0, beat_every=0.5, **_loud())
        _feed(b, 2.0, beat_every=0.5, **_loud())
        frame = make_frame(timestamp=2.01, **_loud())
        assert a.render(frame) == b.render(frame)


class TestDynamics:
    def test_music_ignites_the_medium(self):
        eff = ExcitableMedia()
        _feed(eff, 2.0, beat_every=0.5, **_loud())
        assert np.any(eff._state > 0)

    def test_no_sound_never_ignites(self):
        eff = ExcitableMedia()
        _feed(eff, 2.0)  # silent frames
        assert np.all(eff._state == 0)

    def test_lit_medium_emits_light(self):
        eff = ExcitableMedia()
        _feed(eff, 2.0, beat_every=0.5, **_loud())
        leds = eff.render(make_frame(timestamp=2.01, **_loud()))
        assert sum(sum(led) for led in leds) > 0

    def test_silence_relaxes_to_black(self):
        eff = ExcitableMedia()
        _feed(eff, 2.0, beat_every=0.5, **_loud())
        _feed(eff, 4.0, start=2.0)  # long silence
        leds = eff.render(make_frame(timestamp=6.01))
        assert sum(sum(led) for led in leds) == 0

    def test_hue_tracks_pitch(self):
        # a low-frequency medium should be warmer (lower hue) than a high one
        low = ExcitableMedia()
        high = ExcitableMedia()
        _feed(low, 3.0, beat_every=0.4, **_loud(dominant_freq=80.0))
        _feed(high, 3.0, beat_every=0.4, **_loud(dominant_freq=6000.0))
        assert high._base_hue > low._base_hue
