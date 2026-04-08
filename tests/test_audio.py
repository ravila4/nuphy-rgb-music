import numpy as np
import pytest

from nuphy_rgb.audio import (
    AudioCapture,
    AudioFrame,
    BeatDetector,
    ExpFilter,
    compute_band_energies,
    compute_dominant_freq,
    compute_onset_strength,
    compute_spectral_centroid,
    compute_spectral_flux,
    compute_spectrum_bins,
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


class TestComputeSpectralFlux:
    def test_zero_on_identical_spectra(self):
        mags = np.ones(100)
        assert compute_spectral_flux(mags, mags) == 0.0

    def test_positive_on_increasing_spectrum(self):
        prev = np.zeros(100)
        curr = np.ones(100)
        flux = compute_spectral_flux(curr, prev)
        assert flux > 0.0

    def test_zero_on_decreasing_spectrum(self):
        """Only positive changes count (half-wave rectification)."""
        prev = np.ones(100)
        curr = np.zeros(100)
        assert compute_spectral_flux(curr, prev) == 0.0

    def test_partial_increase(self):
        """Only bins that increased contribute."""
        prev = np.array([1.0, 1.0, 0.0, 0.0])
        curr = np.array([0.0, 0.0, 1.0, 1.0])
        flux = compute_spectral_flux(curr, prev)
        # Two bins increased by 1.0 each, two decreased — only increases count
        assert flux > 0.0

    def test_returns_float(self):
        mags = np.ones(50)
        assert isinstance(compute_spectral_flux(mags, mags), float)


class TestComputeOnsetStrength:
    def test_zero_on_steady_rms(self):
        assert compute_onset_strength(0.5, 0.5) == 0.0

    def test_positive_on_rms_jump(self):
        strength = compute_onset_strength(0.8, 0.2)
        assert strength > 0.0

    def test_zero_on_rms_decrease(self):
        assert compute_onset_strength(0.2, 0.8) == 0.0

    def test_larger_jump_gives_higher_strength(self):
        small = compute_onset_strength(0.3, 0.2)
        large = compute_onset_strength(0.9, 0.2)
        assert large > small

    def test_returns_float(self):
        assert isinstance(compute_onset_strength(0.5, 0.3), float)


class TestMultiBandBeatDetector:
    """BeatDetector already works for bass — verify it works independently for mids/highs."""

    def test_mid_beat_on_mid_spike(self):
        bd = BeatDetector(history_len=10, threshold=1.5)
        for _ in range(10):
            bd.update(1.0)
        assert bd.update(5.0) is True

    def test_independent_detectors_dont_interfere(self):
        bass_bd = BeatDetector(history_len=10, threshold=1.5)
        mid_bd = BeatDetector(history_len=10, threshold=1.5)
        # Fill both with steady energy
        for _ in range(10):
            bass_bd.update(1.0)
            mid_bd.update(1.0)
        # Spike bass only
        assert bass_bd.update(5.0) is True
        assert mid_bd.update(1.0) is False  # mids stayed steady

    def test_high_beat_with_different_refractory(self):
        bd = BeatDetector(history_len=10, threshold=1.5, refractory_frames=2)
        for _ in range(10):
            bd.update(1.0)
        assert bd.update(5.0) is True
        bd.update(1.0)
        bd.update(1.0)
        # After shorter refractory, should fire again
        assert bd.update(5.0) is True


class TestComputeSpectrumBins:
    def test_returns_requested_number_of_bins(self):
        mags, freqs = _make_sine_fft(440.0)
        bins = compute_spectrum_bins(mags, freqs, num_bins=16)
        assert len(bins) == 16

    def test_returns_floats(self):
        mags, freqs = _make_sine_fft(440.0)
        bins = compute_spectrum_bins(mags, freqs, num_bins=16)
        assert all(isinstance(b, float) for b in bins)

    def test_silence_returns_all_zeros(self):
        mags, freqs = _make_silence_fft()
        bins = compute_spectrum_bins(mags, freqs, num_bins=16)
        assert all(b == 0.0 for b in bins)

    def test_bass_tone_concentrates_in_low_bins(self):
        mags, freqs = _make_sine_fft(80.0)
        bins = compute_spectrum_bins(mags, freqs, num_bins=16)
        # Energy should be in the lower bins
        low_energy = sum(bins[:4])
        high_energy = sum(bins[12:])
        assert low_energy > high_energy * 10

    def test_high_tone_concentrates_in_high_bins(self):
        mags, freqs = _make_sine_fft(8000.0)
        bins = compute_spectrum_bins(mags, freqs, num_bins=16)
        low_energy = sum(bins[:4])
        high_energy = sum(bins[12:])
        assert high_energy > low_energy * 10

    def test_all_values_non_negative(self):
        mags, freqs = _make_sine_fft(440.0)
        bins = compute_spectrum_bins(mags, freqs, num_bins=16)
        assert all(b >= 0.0 for b in bins)

    def test_different_bin_counts(self):
        mags, freqs = _make_sine_fft(440.0)
        for n in (8, 16, 32):
            bins = compute_spectrum_bins(mags, freqs, num_bins=n)
            assert len(bins) == n


class TestComputeSpectralCentroid:
    def test_bass_tone_has_low_centroid(self):
        mags, freqs = _make_sine_fft(80.0)
        centroid = compute_spectral_centroid(mags, freqs)
        assert centroid < 200.0

    def test_high_tone_has_high_centroid(self):
        mags, freqs = _make_sine_fft(8000.0)
        centroid = compute_spectral_centroid(mags, freqs)
        assert centroid > 4000.0

    def test_silence_returns_zero(self):
        mags, freqs = _make_silence_fft()
        centroid = compute_spectral_centroid(mags, freqs)
        assert centroid == 0.0

    def test_returns_float(self):
        mags, freqs = _make_sine_fft(440.0)
        assert isinstance(compute_spectral_centroid(mags, freqs), float)

    def test_higher_tone_gives_higher_centroid(self):
        mags_low, freqs = _make_sine_fft(200.0)
        mags_high, _ = _make_sine_fft(4000.0)
        assert compute_spectral_centroid(mags_high, freqs) > compute_spectral_centroid(mags_low, freqs)


class TestAudioFrame:
    def test_is_frozen(self):
        frame = AudioFrame(
            bass=0.5, mids=0.3, highs=0.1,
            dominant_freq=100.0, rms=0.4, is_beat=False, timestamp=0.0,
            onset_strength=0.0, spectral_flux=0.0, mid_beat=False, high_beat=False,
            spectrum=(0.0,) * 16,
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
        # New fields exist and are typed correctly
        assert isinstance(frame.onset_strength, float)
        assert isinstance(frame.spectral_flux, float)
        assert isinstance(frame.mid_beat, bool)
        assert isinstance(frame.high_beat, bool)
        # Spectrum bins
        assert isinstance(frame.spectrum, tuple)
        assert len(frame.spectrum) == 16
        assert all(isinstance(v, float) for v in frame.spectrum)

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

    def test_spectral_flux_nonzero_on_spectrum_change(self):
        cap = self._make_capture()
        t = np.arange(1024) / SAMPLE_RATE
        # First frame: silence to fill ring buffer
        silence = np.zeros(1024, dtype=np.float32)
        cap._queue.put_nowait(silence)
        cap.process_latest()  # establishes prev_magnitudes
        # Second frame: loud sine — spectrum changes dramatically
        loud = np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
        cap._queue.put_nowait(loud)
        frame = cap.process_latest()
        assert frame is not None
        assert frame.spectral_flux > 0.0

    def test_onset_strength_on_sudden_loudness(self):
        cap = self._make_capture()
        t = np.arange(1024) / SAMPLE_RATE
        silence = np.zeros(1024, dtype=np.float32)
        loud = (0.8 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        # Frame 1: silence
        cap._queue.put_nowait(silence)
        cap.process_latest()
        # Frame 2: first onset — cold start suppressed
        cap._queue.put_nowait(loud)
        cap.process_latest()
        # Frame 3: silence (RMS drops)
        cap._queue.put_nowait(silence)
        cap.process_latest()
        # Frame 4: second onset — AGC established, should be positive
        cap._queue.put_nowait(loud)
        frame = cap.process_latest()
        assert frame is not None
        assert frame.onset_strength > 0.0

    def test_onset_strength_is_agc_normalized(self):
        """onset_strength should be AGC-normalized to [0, 1] range."""
        cap = self._make_capture()
        t = np.arange(1024) / SAMPLE_RATE
        # Frame 1: silence
        silence = np.zeros(1024, dtype=np.float32)
        cap._queue.put_nowait(silence)
        cap.process_latest()
        # Frame 2: first onset — cold start, should be suppressed to 0.0
        loud = (0.8 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        cap._queue.put_nowait(loud)
        frame = cap.process_latest()
        assert frame is not None
        assert frame.onset_strength == 0.0, "First onset should be suppressed (cold start)"
        # Frame 3: silence again (RMS drops — onset is 0)
        cap._queue.put_nowait(silence)
        cap.process_latest()
        # Frame 4: second loud onset — AGC peak is established, should normalize
        cap._queue.put_nowait(loud)
        frame2 = cap.process_latest()
        assert frame2 is not None
        assert 0.0 < frame2.onset_strength <= 1.0

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
