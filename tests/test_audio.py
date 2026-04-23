import numpy as np
import pytest

from nuphy_rgb.audio import (
    NUM_CHROMA_BINS,
    AudioCapture,
    AudioFrame,
    BeatDetector,
    ExpFilter,
    TonalChangeDetector,
    build_chroma_filterbank,
    build_spectrum_bin_edges,
    compute_band_energies,
    compute_chroma,
    compute_dominant_freq,
    compute_onset_strength,
    compute_spectral_centroid,
    compute_spectral_flatness,
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


class TestComputeSpectralCentroid:
    def test_single_tone_returns_that_frequency(self):
        mags, freqs = _make_sine_fft(440.0)
        centroid = compute_spectral_centroid(mags, freqs)
        # FFT bin resolution ~23 Hz; centroid is a weighted mean so tolerance is wider
        assert abs(centroid - 440.0) < 50.0

    def test_silence_returns_zero(self):
        mags, freqs = _make_silence_fft()
        assert compute_spectral_centroid(mags, freqs) == 0.0

    def test_higher_tone_gives_higher_centroid(self):
        mags_low, freqs = _make_sine_fft(200.0)
        mags_high, _ = _make_sine_fft(4000.0)
        assert compute_spectral_centroid(mags_high, freqs) > compute_spectral_centroid(
            mags_low, freqs
        )

    def test_returns_float(self):
        mags, freqs = _make_sine_fft(440.0)
        assert isinstance(compute_spectral_centroid(mags, freqs), float)


class TestComputeSpectralFlatness:
    def test_pure_tone_near_zero(self):
        mags, _freqs = _make_sine_fft(440.0)
        flatness = compute_spectral_flatness(mags)
        assert flatness < 0.1

    def test_flat_spectrum_near_one(self):
        mags = np.ones(FFT_SIZE // 2 + 1)
        flatness = compute_spectral_flatness(mags)
        assert flatness > 0.9

    def test_silence_returns_zero(self):
        mags, _freqs = _make_silence_fft()
        assert compute_spectral_flatness(mags) == 0.0

    def test_bounded_zero_to_one(self):
        for freq in (100.0, 440.0, 4000.0):
            mags, _ = _make_sine_fft(freq)
            flatness = compute_spectral_flatness(mags)
            assert 0.0 <= flatness <= 1.0

    def test_returns_float(self):
        mags, _ = _make_sine_fft(440.0)
        assert isinstance(compute_spectral_flatness(mags), float)

    def test_quiet_pure_tone_still_tonal(self):
        """Quiet narrow-band signal must not be misclassified as noise.

        Regression: an absolute-valued epsilon in the log floor would drag
        a quiet tone's geometric mean above its arithmetic mean, clamping
        flatness to 1.0 (max noise). Eps must be tied to the power scale.
        """
        n_bins = FFT_SIZE // 2 + 1
        for peak_mag in (1e-3, 1e-4, 1e-5):
            mags = np.zeros(n_bins)
            mags[100] = peak_mag
            flatness = compute_spectral_flatness(mags)
            assert flatness < 0.2, (
                f"peak={peak_mag:.0e} should read tonal, got flatness={flatness}"
            )


class TestTonalChangeDetector:
    """Detector fires on harmonic section changes, stays quiet within a key."""

    C_MAJOR = (1.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0)  # C, E, G
    E_MAJOR = (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.5)  # E, G#, B

    def test_first_frame_returns_zero(self):
        det = TonalChangeDetector()
        assert det.update(self.C_MAJOR, is_silent=False) == 0.0

    def test_steady_chroma_stays_low(self):
        det = TonalChangeDetector()
        distances = []
        for _ in range(100):
            distances.append(det.update(self.C_MAJOR, is_silent=False))
        # After warmup, feeding the same chroma should keep distance near 0
        assert max(distances[20:]) < 0.05

    def test_key_shift_spikes(self):
        det = TonalChangeDetector()
        # Establish C major as the long-term reference (>600 frames = >20s)
        for _ in range(900):
            det.update(self.C_MAJOR, is_silent=False)
        # Switch to E major — give the fast EMA time to saturate on the
        # new chroma while the slow EMA is still anchored on C major.
        # At fast=2s/slow=20s defaults, fast saturates in ~4-5s (~150 frames).
        peak = 0.0
        for _ in range(200):
            peak = max(peak, det.update(self.E_MAJOR, is_silent=False))
        assert peak > 0.2, f"key shift should spike, got peak={peak}"

    def test_returns_float_in_zero_one(self):
        det = TonalChangeDetector()
        for chroma in (self.C_MAJOR, self.E_MAJOR, (0.1,) * 12):
            d = det.update(chroma, is_silent=False)
            assert isinstance(d, float)
            assert 0.0 <= d <= 1.0

    def test_silence_does_not_update_reference(self):
        """Silence shouldn't decay the reference EMA toward zero.

        If it did, the next non-silent frame would produce a spurious spike
        because fast EMA and zero-ish slow EMA would have large cos distance.
        """
        det = TonalChangeDetector()
        # Establish a reference on C major
        for _ in range(300):
            det.update(self.C_MAJOR, is_silent=False)
        # Many silent frames
        for _ in range(200):
            assert det.update((0.0,) * 12, is_silent=True) == 0.0
        # First non-silent C major frame after silence — should still be low
        d = det.update(self.C_MAJOR, is_silent=False)
        assert d < 0.05, f"silence should not spoil reference, got d={d}"


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

    def test_precomputed_bin_indices_match(self):
        mags, freqs = _make_sine_fft(440.0)
        baseline = compute_spectrum_bins(mags, freqs, num_bins=16)
        bin_idx, _ = build_spectrum_bin_edges(freqs, num_bins=16)
        fast = compute_spectrum_bins(mags, freqs, num_bins=16, bin_indices=bin_idx)
        assert baseline == fast


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


class TestPeakDecayInSilence:
    """AGC peak trackers must decay to near-zero during sustained silence."""

    def test_peak_energy_decays_in_silence(self):
        cap = AudioCapture(device_index=0, sample_rate=SAMPLE_RATE)
        t = np.arange(1024) / SAMPLE_RATE
        loud = (0.8 * np.sin(2 * np.pi * 100.0 * t)).astype(np.float32)
        silence = np.zeros(1024, dtype=np.float32)

        # Pump loud frames to raise peak
        for _ in range(20):
            cap._queue.put_nowait(loud)
            cap.process_latest()
        peak_after_loud = cap._peak_energy
        assert peak_after_loud > 0.0

        # Pump silence frames — peak should decay substantially
        for _ in range(60):
            cap._queue.put_nowait(silence)
            cap.process_latest()

        assert cap._peak_energy < peak_after_loud * 0.1, (
            f"Peak energy should decay in silence: was {peak_after_loud}, "
            f"now {cap._peak_energy}"
        )

    def test_peak_rms_decays_in_silence(self):
        cap = AudioCapture(device_index=0, sample_rate=SAMPLE_RATE)
        t = np.arange(1024) / SAMPLE_RATE
        loud = (0.8 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        silence = np.zeros(1024, dtype=np.float32)

        for _ in range(20):
            cap._queue.put_nowait(loud)
            cap.process_latest()
        peak_after_loud = cap._peak_rms

        for _ in range(60):
            cap._queue.put_nowait(silence)
            cap.process_latest()

        assert cap._peak_rms < peak_after_loud * 0.1

    def test_cold_start_does_not_pin_peaks(self):
        """First frame of audio shouldn't permanently inflate peak trackers."""
        cap = AudioCapture(device_index=0, sample_rate=SAMPLE_RATE)
        t = np.arange(1024) / SAMPLE_RATE
        # One very loud frame followed by quiet music
        blast = (1.0 * np.sin(2 * np.pi * 100.0 * t)).astype(np.float32)
        quiet = (0.05 * np.sin(2 * np.pi * 100.0 * t)).astype(np.float32)

        cap._queue.put_nowait(blast)
        cap.process_latest()
        peak_after_blast = cap._peak_energy

        # Feed quiet music for a while
        for _ in range(100):
            cap._queue.put_nowait(quiet)
            cap.process_latest()

        # Peak should have adapted down substantially from blast level
        assert cap._peak_energy < peak_after_blast * 0.1, (
            f"Peak should adapt down from blast: was {peak_after_blast}, "
            f"now {cap._peak_energy}"
        )
        # Normalized bass should be responding, not crushed
        cap._queue.put_nowait(quiet)
        frame = cap.process_latest()
        assert frame is not None
        assert frame.bass > 0.01, "Bass should not be crushed after peak adapts"


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

    @staticmethod
    def _make_contiguous_chunks(
        freq_hz: float, num_chunks: int, chunk_size: int = 1024
    ) -> list[np.ndarray]:
        """Generate contiguous audio chunks of a pure sine wave.

        Unlike reusing the same chunk, these are sequential samples
        with no phase discontinuity at chunk boundaries.
        """
        t = np.arange(num_chunks * chunk_size) / SAMPLE_RATE
        signal = np.sin(2 * np.pi * freq_hz * t).astype(np.float32)
        return [signal[i * chunk_size:(i + 1) * chunk_size] for i in range(num_chunks)]

    def test_chroma_field_exists(self):
        cap = self._make_capture()
        chunks = self._make_contiguous_chunks(440.0, 2)
        for chunk in chunks:
            cap._queue.put_nowait(chunk)
            cap.process_latest()
        frame = cap.process_latest()
        # process_latest returns None when queue is empty — use last frame
        cap._queue.put_nowait(chunks[0])
        frame = cap.process_latest()
        assert frame is not None
        assert isinstance(frame.chroma, tuple)
        assert len(frame.chroma) == NUM_CHROMA_BINS
        assert all(isinstance(v, float) for v in frame.chroma)

    def test_chroma_is_agc_normalized(self):
        """Chroma values should be AGC-normalized to [0, 1] range."""
        cap = self._make_capture()
        chunks = self._make_contiguous_chunks(440.0, 21)
        for chunk in chunks:
            cap._queue.put_nowait(chunk)
            cap.process_latest()
        frame = cap.process_latest()
        # Last process_latest drained the queue, feed one more
        cap._queue.put_nowait(chunks[0])
        frame = cap.process_latest()
        assert frame is not None
        assert all(0.0 <= c <= 1.01 for c in frame.chroma)
        assert max(frame.chroma) > 0.9
        # A440 should dominate the A bin (index 9)
        assert frame.chroma.index(max(frame.chroma)) == 9

    def test_spectral_centroid_in_frame(self):
        cap = self._make_capture()
        # Feed enough chunks to stabilize AGC, then get a clean frame
        chunks = self._make_contiguous_chunks(440.0, 5)
        for chunk in chunks[:-1]:
            cap._queue.put_nowait(chunk)
            cap.process_latest()
        # Feed final chunk to get a clean frame from stable audio
        cap._queue.put_nowait(chunks[-1])
        frame = cap.process_latest()
        assert frame is not None
        assert isinstance(frame.spectral_centroid, float)
        # Hz-plausible range for a 440 Hz input — catches accidental
        # normalization regressions that would fold centroid to 0-1.
        assert 300.0 < frame.spectral_centroid < 600.0

    def test_spectral_flatness_in_frame(self):
        cap = self._make_capture()
        chunks = self._make_contiguous_chunks(440.0, 3)
        for chunk in chunks:
            cap._queue.put_nowait(chunk)
            cap.process_latest()
        cap._queue.put_nowait(chunks[0])
        frame = cap.process_latest()
        assert frame is not None
        assert isinstance(frame.spectral_flatness, float)
        assert 0.0 <= frame.spectral_flatness <= 1.0


class TestBuildChromaFilterbank:
    def test_shape(self):
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE)
        fb = build_chroma_filterbank(freqs)
        assert fb.shape == (12, len(freqs))

    def test_rows_sum_to_one(self):
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE)
        fb = build_chroma_filterbank(freqs)
        row_sums = fb.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-10)

    def test_all_non_negative(self):
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE)
        fb = build_chroma_filterbank(freqs)
        assert np.all(fb >= 0.0)

    def test_peak_at_correct_bins(self):
        """Each chroma row should peak near its pitch class frequency."""
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE)
        # Single octave so each row has one clear Gaussian
        fb = build_chroma_filterbank(freqs, min_octave=5, max_octave=5)
        for chroma_idx in range(12):
            midi = 12 * 6 + chroma_idx  # octave 5: C5=72, C#5=73, ...
            expected_freq = 440.0 * 2 ** ((midi - 69) / 12.0)
            peak_bin = np.argmax(fb[chroma_idx])
            actual_freq = freqs[peak_bin]
            assert abs(actual_freq - expected_freq) < 30.0, (
                f"Chroma {chroma_idx}: expected ~{expected_freq:.0f} Hz, "
                f"got {actual_freq:.0f} Hz"
            )

    def test_different_octave_ranges(self):
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE)
        fb_narrow = build_chroma_filterbank(freqs, min_octave=4, max_octave=5)
        fb_wide = build_chroma_filterbank(freqs, min_octave=2, max_octave=7)
        assert fb_narrow.shape == fb_wide.shape
        assert np.count_nonzero(fb_wide > 1e-10) >= np.count_nonzero(fb_narrow > 1e-10)


class TestComputeChroma:
    def test_returns_12_floats(self):
        mags, freqs = _make_sine_fft(440.0)
        fb = build_chroma_filterbank(freqs)
        chroma = compute_chroma(mags, fb)
        assert len(chroma) == 12
        assert all(isinstance(c, float) for c in chroma)

    def test_a440_lights_up_a_bin(self):
        """A4 = 440 Hz should produce highest energy in bin 9 (A)."""
        mags, freqs = _make_sine_fft(440.0)
        fb = build_chroma_filterbank(freqs)
        chroma = compute_chroma(mags, fb)
        a_idx = 9  # C=0, C#=1, ..., A=9
        assert chroma[a_idx] == max(chroma), (
            f"A bin ({a_idx}) should be brightest, got argmax={chroma.index(max(chroma))}"
        )

    def test_c_tone_lights_up_c_bin(self):
        """C5 = 523.25 Hz should produce highest energy in bin 0 (C)."""
        mags, freqs = _make_sine_fft(523.25)
        fb = build_chroma_filterbank(freqs)
        chroma = compute_chroma(mags, fb)
        assert chroma[0] == max(chroma)

    def test_silence_returns_zeros(self):
        mags, freqs = _make_silence_fft()
        fb = build_chroma_filterbank(freqs)
        chroma = compute_chroma(mags, fb)
        assert all(c == 0.0 for c in chroma)

    def test_all_non_negative(self):
        mags, freqs = _make_sine_fft(440.0)
        fb = build_chroma_filterbank(freqs)
        chroma = compute_chroma(mags, fb)
        assert all(c >= 0.0 for c in chroma)

    def test_louder_signal_gives_higher_energy(self):
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE)
        fb = build_chroma_filterbank(freqs)
        mags_quiet, _ = _make_sine_fft(440.0, amplitude=0.3)
        mags_loud, _ = _make_sine_fft(440.0, amplitude=1.0)
        chroma_quiet = compute_chroma(mags_quiet, fb)
        chroma_loud = compute_chroma(mags_loud, fb)
        assert chroma_loud[9] > chroma_quiet[9]
