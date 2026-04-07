"""Tests for the StrangeAttractor visualizer effect."""

import time

import numpy as np
import pytest

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.strange_attractor import StrangeAttractor, _lorenz_step, _project

NUM_LEDS = 84


def _make_frame(**kwargs) -> AudioFrame:
    defaults = dict(
        bass=0.0, mids=0.0, highs=0.0,
        dominant_freq=0.0, rms=0.0, is_beat=False, timestamp=0.0,
    )
    defaults.update(kwargs)
    return AudioFrame(**defaults)


def _loud_frame(**kwargs) -> AudioFrame:
    defaults = dict(
        bass=0.8, mids=0.7, highs=0.5,
        dominant_freq=440.0, rms=0.9, is_beat=False, timestamp=0.0,
    )
    defaults.update(kwargs)
    return AudioFrame(**defaults)


# ---------------------------------------------------------------------------
# Basic interface
# ---------------------------------------------------------------------------

class TestInterface:
    def test_returns_84_tuples(self):
        viz = StrangeAttractor(seed=0)
        colors = viz.render(_make_frame())
        assert len(colors) == NUM_LEDS
        assert all(len(c) == 3 for c in colors)

    def test_rgb_values_in_range(self):
        viz = StrangeAttractor(seed=0)
        for _ in range(10):
            colors = viz.render(_loud_frame())
        for r, g, b in colors:
            assert 0 <= r <= 255, f"r={r} out of range"
            assert 0 <= g <= 255, f"g={g} out of range"
            assert 0 <= b <= 255, f"b={b} out of range"

    def test_has_name_attribute(self):
        viz = StrangeAttractor()
        assert isinstance(viz.name, str)
        assert len(viz.name) > 0


# ---------------------------------------------------------------------------
# Module-level functions
# ---------------------------------------------------------------------------

class TestLorenzStep:
    def test_lorenz_step_moves_particles(self):
        particles = np.zeros((12, 3))
        particles[:, 2] = 25.0  # z=25, typical mid-attractor
        particles[:, 0] = np.linspace(-5, 5, 12)
        particles[:, 1] = np.linspace(-5, 5, 12)

        after = _lorenz_step(particles, sigma=10.0, rho=28.0, beta=2.667, dt=0.003, substeps=3)
        assert not np.allclose(particles, after), "Particles should move after lorenz step"

    def test_lorenz_step_stays_bounded(self):
        """10000 steps under extreme audio (all bands = 1.0) must stay in [-100, 100]."""
        rng = np.random.default_rng(42)
        particles = np.column_stack([
            rng.uniform(-5, 5, 12),
            rng.uniform(-5, 5, 12),
            rng.uniform(15, 35, 12),
        ])
        sigma = 8.0 + 1.0 * 8.0   # max bass
        rho = 20.0 + 1.0 * 16.0   # max mids
        beta = 2.0 + 1.0 * 2.0    # max highs
        dt = 0.003 + 1.0 * 0.004  # max dt

        for _ in range(10000):
            particles = _lorenz_step(particles, sigma, rho, beta, dt, substeps=3)

        assert np.all(particles >= -100.0)
        assert np.all(particles <= 100.0)


class TestProject:
    def test_project_center(self):
        """Particle at (0, *, 27.5) should project near (0.5, 0.5)."""
        particles = np.array([[0.0, 0.0, 27.5]])
        gx, gy = _project(particles)
        assert abs(gx[0] - 0.5) < 0.05, f"gx={gx[0]:.4f} expected ~0.5"
        assert abs(gy[0] - 0.5) < 0.05, f"gy={gy[0]:.4f} expected ~0.5"

    def test_project_clamps(self):
        """Out-of-range particles must be clamped to [0, 1]."""
        particles = np.array([
            [-1000.0, 0.0, -1000.0],
            [1000.0, 0.0, 1000.0],
        ])
        gx, gy = _project(particles)
        assert np.all(gx >= 0.0) and np.all(gx <= 1.0)
        assert np.all(gy >= 0.0) and np.all(gy <= 1.0)


# ---------------------------------------------------------------------------
# Audio response
# ---------------------------------------------------------------------------

class TestAudioResponse:
    def test_silence_produces_dim_output(self):
        """After 50 silent frames, total brightness should be very low."""
        viz = StrangeAttractor(seed=0)
        silent = _make_frame()
        for _ in range(50):
            colors = viz.render(silent)
        total_silent = sum(max(r, g, b) for r, g, b in colors)
        # Silence should produce dim but not necessarily zero output
        # (attractor still moves, depositing trails at steady-state)
        # Compare against a loud run to verify silence is dimmer
        viz2 = StrangeAttractor(seed=0)
        loud = _make_frame(bass=0.8, mids=0.5, highs=0.3, rms=0.9)
        for _ in range(50):
            colors2 = viz2.render(loud)
        total_loud = sum(max(r, g, b) for r, g, b in colors2)
        assert total_silent < total_loud, (
            f"Silent ({total_silent}) should be dimmer than loud ({total_loud})"
        )

    def test_loud_produces_visible_output(self):
        """After 30 loud frames, at least some LEDs should be visibly lit."""
        viz = StrangeAttractor(seed=0)
        loud = _loud_frame()
        for _ in range(30):
            colors = viz.render(loud)
        total = sum(max(r, g, b) for r, g, b in colors)
        assert total > 0, "Expected visible output under loud audio"

    def test_beat_changes_particle_state(self):
        """A beat frame should cause different particle positions than a non-beat frame."""
        viz_beat = StrangeAttractor(seed=7)
        viz_nobeat = StrangeAttractor(seed=7)

        # Warm up identically
        for _ in range(10):
            viz_beat.render(_make_frame())
            viz_nobeat.render(_make_frame())

        particles_before = viz_beat._particles.copy()

        viz_beat.render(_make_frame(is_beat=True))
        viz_nobeat.render(_make_frame(is_beat=False))

        # After a beat, particles should differ from the no-beat path
        # (beat adds a kick offset)
        assert not np.allclose(viz_beat._particles, viz_nobeat._particles), (
            "Beat should perturb particle positions relative to no-beat"
        )


# ---------------------------------------------------------------------------
# Determinism and stability
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_deterministic_with_seed(self):
        """Same seed + same frames => identical output."""
        frames = [
            _make_frame(bass=0.3, mids=0.2, rms=0.4),
            _loud_frame(),
            _make_frame(is_beat=True),
        ]
        viz1 = StrangeAttractor(seed=123)
        viz2 = StrangeAttractor(seed=123)
        for frame in frames:
            out1 = viz1.render(frame)
            out2 = viz2.render(frame)
            assert out1 == out2, "Seeded instances must produce identical output"


class TestTrailDecay:
    def test_trails_decay_over_time(self):
        """After a loud burst then silence, trail values should decrease."""
        viz = StrangeAttractor(seed=0)

        # Energize the trails
        for _ in range(10):
            viz.render(_loud_frame())
        trail_after_loud = viz._trails.copy()

        # Let silence decay them
        for _ in range(30):
            viz.render(_make_frame())
        trail_after_silence = viz._trails.copy()

        assert np.sum(trail_after_silence) < np.sum(trail_after_loud), (
            "Trails should decay during silence"
        )


# ---------------------------------------------------------------------------
# Numerical stability
# ---------------------------------------------------------------------------

class TestNumericalStability:
    def test_no_nan_or_inf(self):
        """200 random frames should never produce NaN or Inf in trails."""
        rng = np.random.default_rng(99)
        viz = StrangeAttractor(seed=99)
        for _ in range(200):
            frame = _make_frame(
                bass=float(rng.random()),
                mids=float(rng.random()),
                highs=float(rng.random()),
                rms=float(rng.random()),
                is_beat=bool(rng.random() > 0.9),
            )
            colors = viz.render(frame)
            assert not np.any(np.isnan(viz._trails)), "NaN detected in trails"
            assert not np.any(np.isinf(viz._trails)), "Inf detected in trails"
            for r, g, b in colors:
                assert 0 <= r <= 255
                assert 0 <= g <= 255
                assert 0 <= b <= 255

    def test_extreme_audio_values(self):
        """All audio bands at maximum (1.0) for 100 frames must not crash or produce invalid RGB."""
        viz = StrangeAttractor(seed=42)
        extreme = _make_frame(bass=1.0, mids=1.0, highs=1.0, rms=1.0)
        for _ in range(100):
            colors = viz.render(extreme)
        for r, g, b in colors:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255
