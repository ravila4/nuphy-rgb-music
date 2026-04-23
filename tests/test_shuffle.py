"""Tests for ShuffleManager auto-switching effects on tonal transitions."""

import pytest

from nuphy_rgb.shuffle import ShuffleManager
from nuphy_rgb.state import DaemonState
from tests.helpers import make_frame


@pytest.fixture
def state() -> DaemonState:
    """Four effects, last one named Blackout (to be excluded from shuffle)."""
    names = ["A", "B", "C", "Blackout"]
    ds = DaemonState(num_effects=len(names), effect_names=names)
    ds.set_shuffle(True)
    return ds


def test_disabled_never_switches():
    state = DaemonState(num_effects=4, effect_names=["A", "B", "C", "Blackout"])
    # shuffle_enabled defaults to False
    assert state.shuffle_enabled is False
    shuffle = ShuffleManager()
    for i in range(50):
        frame = make_frame(tonal_change=1.0, timestamp=i * (1 / 30))
        shuffle.update(frame, state)
    assert state.key.index == 0


def test_below_threshold_no_switch(state):
    shuffle = ShuffleManager(threshold=0.3)
    for i in range(50):
        frame = make_frame(tonal_change=0.1, timestamp=i * (1 / 30))
        assert shuffle.update(frame, state) is False
    assert state.key.index == 0


def test_above_threshold_with_hysteresis_switches(state):
    shuffle = ShuffleManager(threshold=0.3, hysteresis_frames=3, min_dwell_s=0.0)
    # First two frames above threshold — not enough for hysteresis
    assert shuffle.update(make_frame(tonal_change=0.5, timestamp=0.0), state) is False
    assert shuffle.update(make_frame(tonal_change=0.5, timestamp=0.03), state) is False
    # Third frame triggers
    assert shuffle.update(make_frame(tonal_change=0.5, timestamp=0.06), state) is True
    assert state.key.index == 1  # moved from A to B


def test_hysteresis_resets_on_dip(state):
    shuffle = ShuffleManager(threshold=0.3, hysteresis_frames=3, min_dwell_s=0.0)
    shuffle.update(make_frame(tonal_change=0.5, timestamp=0.0), state)
    shuffle.update(make_frame(tonal_change=0.5, timestamp=0.03), state)
    # Dip below threshold resets the counter
    shuffle.update(make_frame(tonal_change=0.1, timestamp=0.06), state)
    # Two more above — still not enough for hysteresis=3
    assert shuffle.update(make_frame(tonal_change=0.5, timestamp=0.09), state) is False
    assert shuffle.update(make_frame(tonal_change=0.5, timestamp=0.12), state) is False
    assert state.key.index == 0


def test_dwell_prevents_rapid_switches(state):
    shuffle = ShuffleManager(threshold=0.3, hysteresis_frames=1, min_dwell_s=10.0)
    # First trigger
    assert shuffle.update(make_frame(tonal_change=0.5, timestamp=0.0), state) is True
    assert state.key.index == 1
    # Another spike 5s later — dwell not satisfied
    assert shuffle.update(make_frame(tonal_change=0.5, timestamp=5.0), state) is False
    assert state.key.index == 1
    # After dwell expires
    assert shuffle.update(make_frame(tonal_change=0.5, timestamp=11.0), state) is True
    assert state.key.index == 2


def test_skips_excluded_effect(state):
    """If the next index is Blackout, the manager must skip it."""
    shuffle = ShuffleManager(threshold=0.3, hysteresis_frames=1, min_dwell_s=0.0)
    state.key.set(2)  # on "C" — next would be Blackout
    shuffle.update(make_frame(tonal_change=0.5, timestamp=0.0), state)
    # Skipped Blackout (index 3), wrapped to A (index 0)
    assert state.key.index == 0


def test_wraps_around(state):
    """From the last eligible effect, wraps to the first."""
    shuffle = ShuffleManager(threshold=0.3, hysteresis_frames=1, min_dwell_s=0.0)
    state.key.set(2)  # "C" — last non-excluded
    shuffle.update(make_frame(tonal_change=0.5, timestamp=0.0), state)
    assert state.key.index == 0


def test_all_excluded_no_switch():
    """Degenerate: if every effect is excluded, update returns False."""
    state = DaemonState(num_effects=2, effect_names=["A", "Blackout"])
    state.set_shuffle(True)
    shuffle = ShuffleManager(
        threshold=0.3,
        hysteresis_frames=1,
        min_dwell_s=0.0,
        excluded_names=("A", "Blackout"),
    )
    assert shuffle.update(make_frame(tonal_change=0.5), state) is False


def test_changed_flag_set_on_switch(state):
    """state.key.poll_changed() must fire so main loop picks up the switch."""
    shuffle = ShuffleManager(threshold=0.3, hysteresis_frames=1, min_dwell_s=0.0)
    shuffle.update(make_frame(tonal_change=0.5, timestamp=0.0), state)
    assert state.key.poll_changed() == 1
