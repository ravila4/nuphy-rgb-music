"""Tests for the YIN pitch detector."""

import numpy as np

from nuphy_rgb.audio import YinPitchDetector, hz_to_midi


def _sine(freq_hz: float, duration_s: float = 0.042, sample_rate: int = 48000,
          amplitude: float = 0.5) -> np.ndarray:
    n = int(duration_s * sample_rate)
    t = np.arange(n) / sample_rate
    return (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


class TestHzToMidi:
    def test_a4_is_69(self):
        assert hz_to_midi(440.0) == 69.0

    def test_a5_is_81(self):
        assert hz_to_midi(880.0) == 81.0

    def test_zero_returns_zero(self):
        assert hz_to_midi(0.0) == 0.0


class TestYinPitchDetector:
    def test_detects_a4(self):
        det = YinPitchDetector()
        midi, prob = det.update(_sine(440.0))
        assert prob > 0.7
        assert abs(midi - 69.0) < 0.5

    def test_detects_c4(self):
        det = YinPitchDetector()
        midi, prob = det.update(_sine(261.63))  # C4
        assert prob > 0.7
        assert abs(midi - 60.0) < 0.5

    def test_detects_e2(self):
        # Low end of the default range — exercises large-tau path
        det = YinPitchDetector()
        midi, prob = det.update(_sine(82.41, duration_s=0.06))
        assert prob > 0.7
        assert abs(midi - 40.0) < 0.5

    def test_detects_b5(self):
        # Near the upper bound; short period, small tau
        det = YinPitchDetector()
        midi, prob = det.update(_sine(987.77))
        assert prob > 0.7
        assert abs(midi - 83.0) < 0.5

    def test_silence_unvoiced(self):
        det = YinPitchDetector()
        samples = np.zeros(2048, dtype=np.float32)
        midi, prob = det.update(samples)
        assert midi == 0.0
        assert prob == 0.0

    def test_white_noise_low_confidence(self):
        det = YinPitchDetector()
        rng = np.random.default_rng(42)
        samples = rng.standard_normal(2048).astype(np.float32) * 0.3
        midi, prob = det.update(samples)
        # Noise can produce spurious pitches; just ensure we flag it as
        # low-confidence so the effect can fade it out.
        assert prob < 0.6

    def test_short_buffer_safe(self):
        det = YinPitchDetector()
        samples = np.zeros(32, dtype=np.float32)
        midi, prob = det.update(samples)
        assert midi == 0.0
        assert prob == 0.0
