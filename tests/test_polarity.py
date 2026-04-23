"""Tests for the Polarity effect."""

from __future__ import annotations

import math

import numpy as np
import pytest

from nuphy_rgb.effects.polarity.effect import Polarity, _CHARGES, _initial_ring
from tests.helpers import make_frame


def _total_brightness(leds: list[tuple[int, int, int]]) -> float:
    return float(sum(sum(t) for t in leds))


def _chroma_for_pitch(pitch_idx: int, weight: float = 1.0) -> tuple[float, ...]:
    return tuple(weight if i == pitch_idx else 0.0 for i in range(12))


# ----------------------------------------------------------------------
# Load-bearing invariants
# ----------------------------------------------------------------------


def test_charge_table_is_cosine_of_pitch_class():
    """charge[k] = cos(2 * pi * k / 12) — the core design invariant."""
    for k in range(12):
        assert _CHARGES[k] == pytest.approx(math.cos(2.0 * math.pi * k / 12.0))


def test_tritone_charges_product_is_minus_one():
    """C (k=0) and F# (k=6) must have charge product -1 (max attraction)."""
    assert _CHARGES[0] * _CHARGES[6] == pytest.approx(-1.0)


def test_drum_lock_in_is_architecturally_impossible():
    """With exactly one body per pitch class, repeated beats on the same
    pitch just re-kick the same body — no particle pile-up possible.
    Verify by spawning many C beats and observing that only body 0 (C)
    accumulates velocity.
    """
    viz = Polarity()
    viz._vel[:] = 0.0
    c_chroma = np.asarray(_chroma_for_pitch(0), dtype=np.float64)
    for _ in range(10):
        frame = make_frame(
            bass=0.6, is_beat=True, raw_rms=0.5, onset_strength=0.9,
            chroma=_chroma_for_pitch(0), timestamp=0.0,
        )
        viz._apply_beat_kicks(frame, c_chroma)
    # Only body 0 ever received impulses; body count stays at 12.
    assert viz._pos.shape == (12, 2)
    assert np.linalg.norm(viz._vel[0]) > 0
    for k in range(1, 12):
        assert np.linalg.norm(viz._vel[k]) == pytest.approx(0.0)


def test_has_exactly_twelve_bodies():
    viz = Polarity()
    assert viz._pos.shape == (12, 2)
    assert viz._vel.shape == (12, 2)


def test_initial_ring_positions_are_on_grid():
    pos = _initial_ring()
    assert pos.shape == (12, 2)
    for x, y in pos:
        assert 0 <= x <= 16
        assert 0 <= y <= 6


# ----------------------------------------------------------------------
# Output shape and range
# ----------------------------------------------------------------------


def test_name():
    assert Polarity().name == "Polarity"


def test_returns_84_tuples():
    viz = Polarity()
    frame = make_frame(
        bass=0.5, is_beat=True, raw_rms=0.3,
        onset_strength=0.8, chroma=_chroma_for_pitch(0),
        timestamp=0.0,
    )
    leds = viz.render(frame)
    assert len(leds) == 84
    for t in leds:
        assert len(t) == 3


def test_rgb_in_range():
    viz = Polarity()
    for i in range(30):
        frame = make_frame(
            bass=0.7, mids=0.4, highs=0.3,
            dominant_freq=440.0, rms=0.5, raw_rms=0.5,
            is_beat=(i % 5 == 0), mid_beat=(i % 7 == 0),
            high_beat=(i % 11 == 0),
            onset_strength=0.8,
            chroma=_chroma_for_pitch(i % 12),
            timestamp=i * (1 / 30),
        )
        leds = viz.render(frame)
        for r, g, b in leds:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255


# ----------------------------------------------------------------------
# Physics: load-bearing invariants
# ----------------------------------------------------------------------


def test_like_charges_repel():
    """Two bodies with the same charge and equal masses must accelerate apart."""
    viz = Polarity()
    # Override positions: put bodies 0 (C, charge +1) and 12 would be C again,
    # but we don't have two Cs — instead, pick two bodies whose charges are
    # both positive (k=0 and k=1 have charges +1.0 and ~+0.866; product +0.866).
    viz._pos = np.zeros((12, 2), dtype=np.float64)
    viz._vel = np.zeros((12, 2), dtype=np.float64)
    # Place body 0 at col 7, body 1 at col 9, everyone else far away.
    viz._pos[0] = [7.0, 3.0]
    viz._pos[1] = [9.0, 3.0]
    for k in range(2, 12):
        viz._pos[k] = [0.0, 0.0]  # bunch at origin; we will zero their mass

    # Make only bodies 0 and 1 massive so other charges don't perturb them.
    masses = np.zeros(12, dtype=np.float64)
    masses[0] = 1.0
    masses[1] = 1.0
    acc = viz._compute_accel(viz._pos, masses)

    # Body 0 should be pushed in -x (leftward); body 1 in +x (rightward).
    assert acc[0, 0] < 0, f"body 0 should accelerate left, got {acc[0, 0]}"
    assert acc[1, 0] > 0, f"body 1 should accelerate right, got {acc[1, 0]}"


def test_opposite_charges_attract():
    """C (charge +1) and F# (charge -1) must accelerate toward each other."""
    viz = Polarity()
    viz._pos = np.zeros((12, 2), dtype=np.float64)
    viz._vel = np.zeros((12, 2), dtype=np.float64)
    viz._pos[0] = [7.0, 3.0]   # C
    viz._pos[6] = [9.0, 3.0]   # F# (tritone from C)
    for k in (1, 2, 3, 4, 5, 7, 8, 9, 10, 11):
        viz._pos[k] = [0.0, 0.0]

    masses = np.zeros(12, dtype=np.float64)
    masses[0] = 1.0
    masses[6] = 1.0
    acc = viz._compute_accel(viz._pos, masses)

    assert acc[0, 0] > 0, f"C should attract toward F# (+x), got {acc[0, 0]}"
    assert acc[6, 0] < 0, f"F# should attract toward C (-x), got {acc[6, 0]}"


def test_zero_force_constant_disables_physics():
    viz = Polarity()
    viz.params["force_constant"].set(0.0)
    masses = np.ones(12, dtype=np.float64)
    acc = viz._compute_accel(viz._pos, masses)
    assert np.all(acc == 0.0)


# ----------------------------------------------------------------------
# Chroma → mass and rendering
# ----------------------------------------------------------------------


def test_silent_chroma_gives_base_mass_only():
    viz = Polarity()
    base = viz.params["base_mass"].get()
    masses = viz._compute_masses(np.zeros(12))
    assert np.all(masses == pytest.approx(base))


def test_active_chroma_increases_mass():
    viz = Polarity()
    base = viz.params["base_mass"].get()
    gain = viz.params["chroma_mass_gain"].get()
    chroma = np.zeros(12)
    chroma[0] = 1.0
    masses = viz._compute_masses(chroma)
    assert masses[0] == pytest.approx(base + gain)
    for k in range(1, 12):
        assert masses[k] == pytest.approx(base)


def test_silence_produces_black_after_decay():
    viz = Polarity()
    # Seed with a beat so the trail buffer has content.
    viz.render(make_frame(
        bass=0.8, is_beat=True, onset_strength=1.0,
        chroma=_chroma_for_pitch(0), timestamp=0.0,
    ))
    # Then feed many silent frames — raw_rms=0 sends decay_rate to decay_low
    # and threshold gates out deposits.
    for i in range(1, 200):
        leds = viz.render(make_frame(timestamp=i * (1 / 30)))
    assert _total_brightness(leds) == 0


def test_beat_produces_visible_output():
    viz = Polarity()
    frame = make_frame(
        bass=0.6, is_beat=True, raw_rms=0.5, onset_strength=0.9,
        chroma=_chroma_for_pitch(0), timestamp=0.0,
    )
    leds = viz.render(frame)
    assert _total_brightness(leds) > 0


def test_chroma_below_threshold_not_drawn():
    viz = Polarity()
    viz.params["chroma_threshold"].set(0.5)
    # All chroma weights below the threshold — nothing should deposit.
    frame = make_frame(
        bass=0.0, raw_rms=0.5,  # loud but no pitched content above threshold
        chroma=tuple([0.3] * 12),  # every body just below threshold
        timestamp=0.0,
    )
    leds = viz.render(frame)
    # Trail buffer fresh; no deposits → black output.
    assert _total_brightness(leds) == 0


# ----------------------------------------------------------------------
# Beat impulses
# ----------------------------------------------------------------------


def test_beat_kicks_playing_notes_only():
    viz = Polarity()
    viz._vel[:] = 0.0
    frame = make_frame(
        bass=0.6, is_beat=True, raw_rms=0.5, onset_strength=0.9,
        chroma=_chroma_for_pitch(0),  # only C is playing
        timestamp=0.0,
    )
    viz._apply_beat_kicks(frame, np.asarray(frame.chroma, dtype=np.float64))
    # Body 0 (C) got a kick — nonzero velocity.
    assert np.linalg.norm(viz._vel[0]) > 0
    # All other bodies have zero chroma → zero kick → zero velocity.
    for k in range(1, 12):
        assert np.linalg.norm(viz._vel[k]) == pytest.approx(0.0)


def test_no_beat_no_kick():
    viz = Polarity()
    viz._vel[:] = 0.0
    frame = make_frame(
        bass=0.5, raw_rms=0.5,  # no is_beat
        chroma=_chroma_for_pitch(0),
        timestamp=0.0,
    )
    viz._apply_beat_kicks(frame, np.asarray(frame.chroma, dtype=np.float64))
    assert np.all(viz._vel == 0.0)


# ----------------------------------------------------------------------
# Speed clamping
# ----------------------------------------------------------------------


def test_speed_clamp_enforced():
    viz = Polarity()
    viz._vel[0] = [1000.0, 0.0]  # way over max_speed
    viz._clamp_speed()
    max_speed = viz.params["max_speed"].get()
    assert np.linalg.norm(viz._vel[0]) == pytest.approx(max_speed)


# ----------------------------------------------------------------------
# Determinism
# ----------------------------------------------------------------------


def test_determinism():
    frames = [
        make_frame(
            bass=0.5, mids=0.3, highs=0.2,
            dominant_freq=330.0, rms=0.4, raw_rms=0.4,
            is_beat=(i % 8 == 0),
            mid_beat=(i % 11 == 0),
            onset_strength=0.6,
            chroma=_chroma_for_pitch(i % 12),
            timestamp=i * (1 / 30),
        )
        for i in range(30)
    ]
    a = Polarity()
    b = Polarity()
    for f in frames:
        out_a = a.render(f)
        out_b = b.render(f)
        assert out_a == out_b
