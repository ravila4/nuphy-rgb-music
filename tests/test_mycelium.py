"""Tests for the Mycelium visualizer effect."""

import pytest

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.mycelium import Mycelium

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


def _silence() -> AudioFrame:
    return _make_frame()


def _beat_frame(**kwargs) -> AudioFrame:
    defaults = dict(is_beat=True, rms=0.8)
    defaults.update(kwargs)
    return _make_frame(**defaults)


class TestBasicContract:
    def test_returns_84_tuples(self):
        viz = Mycelium(seed=42)
        colors = viz.render(_silence())
        assert len(colors) == NUM_LEDS
        assert all(len(c) == 3 for c in colors)

    def test_rgb_values_in_range(self):
        viz = Mycelium(seed=42)
        for _ in range(10):
            viz.render(_beat_frame())
        colors = viz.render(_make_frame(rms=0.5))
        for r, g, b in colors:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_has_name_attribute(self):
        viz = Mycelium()
        assert hasattr(viz, "name")
        assert isinstance(viz.name, str)
        assert viz.name  # not empty


class TestPhosphorescenceBase:
    def test_silence_shows_phosphorescent_base(self):
        """After several silent frames, at least some LEDs should have green tint."""
        viz = Mycelium(seed=1)
        # Warm up: let the glow floor accumulate
        for _ in range(5):
            viz.render(_silence())
        colors = viz.render(_silence())
        # At least some valid LED positions should have nonzero green
        green_present = any(g > 0 for _, g, _ in colors)
        assert green_present, "Expected phosphorescent green base in silence"

    def test_silence_no_tendrils_spawned(self):
        """Silent frames without beats should not spawn tendrils."""
        viz = Mycelium(seed=2)
        for _ in range(20):
            viz.render(_silence())
        assert len(viz._tendrils) == 0


class TestBeatSpawning:
    def test_beat_spawns_tendrils(self):
        """A beat frame should result in tendrils being added."""
        viz = Mycelium(seed=3)
        viz.render(_beat_frame(bass=0.5))
        assert len(viz._tendrils) > 0

    def test_spawn_count_bounded(self):
        """Spawn count should be between 2 and 5 per beat."""
        viz = Mycelium(seed=4)
        viz.render(_beat_frame(bass=0.5))
        # First beat: tendrils spawned should be 2-5
        assert 2 <= len(viz._tendrils) <= 5

    def test_max_tendrils_cap(self):
        """Total live tendrils should never exceed max_tendrils."""
        viz = Mycelium(seed=5, max_tendrils=10)
        for _ in range(50):
            viz.render(_beat_frame(bass=1.0, rms=1.0))
        assert len(viz._tendrils) <= 10


class TestHueMapping:
    def test_bass_spawns_warm_hue(self):
        """Bass-dominant beat should produce warm (low) hue tendrils."""
        viz = Mycelium(seed=10)
        viz.render(_beat_frame(bass=1.0, mids=0.0, highs=0.0))
        assert len(viz._tendrils) > 0
        # All spawned tendrils should have hue in warm range (bass: 0.0-0.08)
        for t in viz._tendrils:
            assert t.hue < 0.09, f"Expected warm hue < 0.09, got {t.hue}"

    def test_highs_spawns_cool_hue(self):
        """Highs-dominant beat should produce cool (high) hue tendrils."""
        viz = Mycelium(seed=11)
        viz.render(_beat_frame(bass=0.0, mids=0.0, highs=1.0))
        assert len(viz._tendrils) > 0
        for t in viz._tendrils:
            assert t.hue > 0.5, f"Expected cool hue, got {t.hue}"


class TestTendrilLifecycle:
    def test_tendrils_die_after_max_age(self):
        """Tendrils should be removed once they exceed max_age."""
        viz = Mycelium(seed=20)
        # Spawn tendrils
        viz.render(_beat_frame(bass=0.5))
        initial_count = len(viz._tendrils)
        assert initial_count > 0

        # Render many frames without new beats to let them age out
        # max_age is 8-20; 30 frames is enough for all to die
        for _ in range(30):
            viz.render(_silence())

        assert len(viz._tendrils) == 0, "Expected all tendrils to have died"

    def test_energy_decays(self):
        """Tendril energy should decay each frame."""
        viz = Mycelium(seed=21)
        viz.render(_beat_frame(bass=0.5))
        assert len(viz._tendrils) > 0

        initial_energies = [t.energy for t in viz._tendrils]
        viz.render(_silence())
        current_energies = [t.energy for t in viz._tendrils]

        assert len(current_energies) > 0, "Expected surviving tendrils"
        assert all(
            e <= init for e, init in zip(current_energies, initial_energies)
        ), "Expected energy to decay"


class TestDeterminism:
    def test_deterministic_with_seed(self):
        """Same seed should produce identical output across two instances."""
        frames = [
            _beat_frame(bass=0.8),
            _silence(),
            _beat_frame(mids=0.9),
            _silence(),
            _silence(),
        ]

        viz1 = Mycelium(seed=99)
        viz2 = Mycelium(seed=99)

        for frame in frames:
            out1 = viz1.render(frame)
            out2 = viz2.render(frame)
            assert out1 == out2, "Non-deterministic output with same seed"


class TestOccupiedTracking:
    def test_occupied_cleared_on_death(self):
        """Positions held by dead tendrils should be released from _occupied."""
        viz = Mycelium(seed=30)
        viz.render(_beat_frame(bass=0.5))
        assert len(viz._occupied) > 0

        # Let all tendrils die
        for _ in range(30):
            viz.render(_silence())

        assert len(viz._tendrils) == 0
        assert len(viz._occupied) == 0, "Expected _occupied to be empty after all tendrils die"


class TestStability:
    def test_no_crash_on_rapid_beats(self):
        """Rapid successive beats should not raise exceptions."""
        viz = Mycelium(seed=50)
        for i in range(100):
            frame = _beat_frame(
                bass=0.5 + 0.5 * (i % 2),
                mids=0.3,
                highs=0.2,
                rms=0.9,
            )
            colors = viz.render(frame)
            assert len(colors) == NUM_LEDS
