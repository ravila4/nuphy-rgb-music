import numpy as np
import pytest

from nuphy_rgb.audio import (
    AudioCapture,
    AudioFrame,
    BeatDetector,
    ExpFilter,
    compute_band_energies,
    compute_dominant_freq,
)

SAMPLE_RATE = 48000
FFT_SIZE = 2048


def _make_sine_fft(freq_hz: float, amplitude: float = 1.0):
    """Generate FFT magnitudes and frequencies for a pure sine wave."""
    t = np.arange(FFT_SIZE) / SAMPLE_RATE
    signal = amplitude * np.sin(2 * np.pi * freq_hz * t)
    window = np.hanning(FFT_SIZE)
    magnitudes = np.abs(np.fft.rfft(signal * window))
    freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE)
    return magnitudes, freqs


def _make_silence_fft():
    """Generate FFT of silence."""
    magnitudes = np.zeros(FFT_SIZE // 2 + 1)
    freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE)
    return magnitudes, freqs


class TestComputeBandEnergies:
    def test_pure_bass_tone(self):
        mags, freqs = _make_sine_fft(100.0)  # 100 Hz = bass
        bass, mids, highs = compute_band_energies(mags, freqs)
        assert bass > 0.1
        assert mids < bass * 0.01
        assert highs < bass * 0.01

    def test_pure_mid_tone(self):
        mags, freqs = _make_sine_fft(1000.0)  # 1 kHz = mids
        bass, mids, highs = compute_band_energies(mags, freqs)
        assert mids > 0.1
        assert bass < mids * 0.01
        assert highs < mids * 0.01

    def test_pure_high_tone(self):
        mags, freqs = _make_sine_fft(8000.0)  # 8 kHz = highs
        bass, mids, highs = compute_band_energies(mags, freqs)
        assert highs > 0.1
        assert bass < highs * 0.01
        assert mids < highs * 0.01

    def test_silence_returns_zeros(self):
        mags, freqs = _make_silence_fft()
        bass, mids, highs = compute_band_energies(mags, freqs)
        assert bass == 0.0
        assert mids == 0.0
        assert highs == 0.0

    def test_louder_signal_gives_higher_energy(self):
        mags_quiet, freqs = _make_sine_fft(100.0, amplitude=0.5)
        mags_loud, _ = _make_sine_fft(100.0, amplitude=1.0)
        bass_quiet, _, _ = compute_band_energies(mags_quiet, freqs)
        bass_loud, _, _ = compute_band_energies(mags_loud, freqs)
        assert bass_loud > bass_quiet


class TestComputeDominantFreq:
    def test_single_tone_440hz(self):
        mags, freqs = _make_sine_fft(440.0)
        dominant = compute_dominant_freq(mags, freqs)
        # FFT bin resolution is ~23 Hz, so allow some tolerance
        assert abs(dominant - 440.0) < 30.0

    def test_single_tone_100hz(self):
        mags, freqs = _make_sine_fft(100.0)
        dominant = compute_dominant_freq(mags, freqs)
        assert abs(dominant - 100.0) < 30.0

    def test_silence_returns_zero(self):
        mags, freqs = _make_silence_fft()
        dominant = compute_dominant_freq(mags, freqs)
        assert dominant == 0.0


class TestBeatDetector:
    def test_triggers_on_energy_spike(self):
        bd = BeatDetector(history_len=10, threshold=1.5)
        # Fill history with low energy
        for _ in range(10):
            bd.update(1.0)
        # Spike should trigger beat
        assert bd.update(5.0) is True

    def test_no_beat_on_steady_energy(self):
        bd = BeatDetector(history_len=10, threshold=1.5)
        results = []
        for _ in range(20):
            results.append(bd.update(1.0))
        # After warmup, no beats on steady signal
        assert not any(results[10:])

    def test_refractory_period_prevents_burst(self):
        bd = BeatDetector(history_len=10, threshold=1.5, refractory_frames=5)
        # Fill with low energy
        for _ in range(10):
            bd.update(1.0)
        # First spike triggers
        assert bd.update(5.0) is True
        # Immediate second spike within refractory period does not trigger
        assert bd.update(5.0) is False

    def test_beat_fires_again_after_refractory(self):
        bd = BeatDetector(history_len=10, threshold=1.5, refractory_frames=3)
        for _ in range(10):
            bd.update(1.0)
        assert bd.update(5.0) is True
        # Wait through refractory + let history settle
        for _ in range(5):
            bd.update(1.0)
        assert bd.update(5.0) is True

    def test_no_beat_during_warmup(self):
        bd = BeatDetector(history_len=10, threshold=1.5)
        # Even a spike during warmup (empty history) shouldn't cause issues
        result = bd.update(10.0)
        # First frame has no meaningful average, so no beat
        assert result is False


class TestExpFilter:
    def test_tracks_rising_signal_fast(self):
        filt = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)
        filt.update(0.0)
        val = filt.update(1.0)
        assert val > 0.7  # Should jump close to 1.0

    def test_tracks_falling_signal_slowly(self):
        filt = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)
        filt.update(1.0)
        filt.update(1.0)  # stabilize at 1.0
        val = filt.update(0.0)
        assert val > 0.7  # Should still be high (slow decay)

    def test_converges_to_steady_value(self):
        filt = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)
        for _ in range(100):
            filt.update(0.5)
        assert abs(filt.value - 0.5) < 0.01


class TestAudioFrame:
    def test_is_frozen(self):
        frame = AudioFrame(
            bass=0.5, mids=0.3, highs=0.1,
            dominant_freq=100.0, rms=0.4, is_beat=False, timestamp=0.0,
        )
        with pytest.raises(AttributeError):
            frame.bass = 0.9


class TestAudioCapture:
    def _make_capture(self):
        """Create an AudioCapture without starting the stream."""
        return AudioCapture(device_index=0, sample_rate=SAMPLE_RATE)

    def test_process_latest_returns_none_when_empty(self):
        cap = self._make_capture()
        assert cap.process_latest() is None

    def test_process_latest_returns_frame_for_enqueued_audio(self):
        cap = self._make_capture()
        # Enqueue a 100Hz sine block (fits in ring buffer)
        t = np.arange(1024) / SAMPLE_RATE
        chunk = np.sin(2 * np.pi * 100.0 * t).astype(np.float32)
        cap._queue.put_nowait(chunk)
        # Need two chunks to fill 2048-sample ring buffer
        cap._queue.put_nowait(chunk)
        frame = cap.process_latest()
        assert frame is not None
        assert isinstance(frame, AudioFrame)
        assert frame.bass > 0
        assert frame.rms > 0

    def test_process_latest_keeps_only_latest(self):
        cap = self._make_capture()
        t = np.arange(1024) / SAMPLE_RATE
        # Enqueue silence then a loud sine
        silence = np.zeros(1024, dtype=np.float32)
        loud = np.sin(2 * np.pi * 100.0 * t).astype(np.float32)
        cap._queue.put_nowait(silence)
        cap._queue.put_nowait(silence)
        cap._queue.put_nowait(loud)
        frame = cap.process_latest()
        assert frame is not None
        # The ring buffer should contain the loud signal in its latest half
        assert frame.rms > 0

    def test_ring_buffer_accumulates(self):
        cap = self._make_capture()
        t = np.arange(1024) / SAMPLE_RATE
        chunk = np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
        # First chunk only fills half the ring buffer
        cap._queue.put_nowait(chunk)
        frame = cap.process_latest()
        assert frame is not None
        # Second chunk fills the rest
        cap._queue.put_nowait(chunk)
        frame2 = cap.process_latest()
        assert frame2 is not None
        # Both should detect 440Hz
        assert abs(frame2.dominant_freq - 440.0) < 30.0
