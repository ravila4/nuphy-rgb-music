"""Audio capture, FFT analysis, and beat detection for music-reactive RGB."""

import queue
import time
from collections import deque
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

# Frequency band boundaries (Hz)
BASS_LOW, BASS_HIGH = 20, 150
MID_LOW, MID_HIGH = 150, 2000
HIGH_LOW, HIGH_HIGH = 2000, 16000

NUM_SPECTRUM_BINS = 16
NUM_CHROMA_BINS = 12

# AGC peak tracker constants
PEAK_DECAY = 0.995          # normal decay per frame (~600 frames to halve)
PEAK_SILENCE_DECAY = 0.92   # fast decay during silence (~8 frames to halve)
SILENCE_FLOOR = 1e-4         # below this, signal is considered silence


@dataclass(frozen=True)
class AudioFrame:
    """Immutable snapshot of audio analysis for one frame."""

    bass: float
    mids: float
    highs: float
    dominant_freq: float
    rms: float
    is_beat: bool
    timestamp: float
    raw_rms: float = 0.0
    onset_strength: float = 0.0
    spectral_flux: float = 0.0
    mid_beat: bool = False
    high_beat: bool = False
    spectrum: tuple[float, ...] = (0.0,) * NUM_SPECTRUM_BINS
    chroma: tuple[float, ...] = (0.0,) * NUM_CHROMA_BINS
    spectral_centroid: float = 0.0   # Hz, like dominant_freq
    spectral_flatness: float = 0.0   # 0.0 (tonal) to 1.0 (noise)
    tonal_change: float = 0.0        # 0.0 (steady) to 1.0 (new tonal center)


class ExpFilter:
    """Asymmetric exponential smoothing: fast attack, slow decay."""

    def __init__(self, alpha_rise: float = 0.8, alpha_decay: float = 0.15):
        self.alpha_rise = alpha_rise
        self.alpha_decay = alpha_decay
        self.value: float = 0.0

    def update(self, new_value: float) -> float:
        alpha = self.alpha_rise if new_value > self.value else self.alpha_decay
        self.value = alpha * new_value + (1 - alpha) * self.value
        return self.value


def compute_band_energies(
    magnitudes: np.ndarray, freqs: np.ndarray
) -> tuple[float, float, float]:
    """Compute energy in bass, mid, and high frequency bands."""
    bass_mask = (freqs >= BASS_LOW) & (freqs <= BASS_HIGH)
    mid_mask = (freqs >= MID_LOW) & (freqs <= MID_HIGH)
    high_mask = (freqs >= HIGH_LOW) & (freqs <= HIGH_HIGH)

    bass = float(np.sum(magnitudes[bass_mask] ** 2))
    mids = float(np.sum(magnitudes[mid_mask] ** 2))
    highs = float(np.sum(magnitudes[high_mask] ** 2))
    return bass, mids, highs


def compute_dominant_freq(magnitudes: np.ndarray, freqs: np.ndarray) -> float:
    """Return the frequency (Hz) with the highest magnitude, or 0.0 for near-silence."""
    if np.max(magnitudes) < 1e-6:
        return 0.0
    return float(freqs[np.argmax(magnitudes)])


def compute_spectral_flux(
    magnitudes: np.ndarray, prev_magnitudes: np.ndarray
) -> float:
    """Half-wave rectified spectral flux: sum of positive magnitude changes."""
    diff = magnitudes - prev_magnitudes
    return float(np.sum(np.maximum(diff, 0.0)))


def build_spectrum_bin_edges(
    freqs: np.ndarray,
    num_bins: int = NUM_SPECTRUM_BINS,
    min_freq: float = 20.0,
    max_freq: float = 16000.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Pre-compute bin assignments for log-spaced spectrum bins.

    Returns (bin_indices, log_edges) where bin_indices maps each freq bin
    to a spectrum bin (0..num_bins-1), with out-of-range bins set to -1.
    """
    log_edges = np.logspace(
        np.log10(min_freq), np.log10(max_freq), num_bins + 1
    )
    # digitize returns 1..num_bins for in-range, 0 or num_bins+1 for out
    raw = np.digitize(freqs, log_edges)
    bin_indices = np.where((raw >= 1) & (raw <= num_bins), raw - 1, -1)
    return bin_indices.astype(np.intp), log_edges


def compute_spectrum_bins(
    magnitudes: np.ndarray,
    freqs: np.ndarray,
    num_bins: int = NUM_SPECTRUM_BINS,
    min_freq: float = 20.0,
    max_freq: float = 16000.0,
    bin_indices: np.ndarray | None = None,
) -> list[float]:
    """Bin FFT magnitudes into log-spaced frequency bands.

    Pass pre-computed *bin_indices* from build_spectrum_bin_edges() to
    avoid recomputing bin assignments each frame.
    """
    if bin_indices is None:
        bin_indices, _ = build_spectrum_bin_edges(
            freqs, num_bins, min_freq, max_freq
        )
    power = magnitudes ** 2
    valid = bin_indices >= 0
    counts = np.bincount(bin_indices[valid], minlength=num_bins)
    sums = np.bincount(bin_indices[valid], weights=power[valid], minlength=num_bins)
    safe_counts = np.where(counts > 0, counts, 1)
    return np.where(counts > 0, sums / safe_counts, 0.0).tolist()


def build_chroma_filterbank(
    freqs: np.ndarray,
    min_octave: int = 2,
    max_octave: int = 7,
) -> np.ndarray:
    """Build a 12 x len(freqs) Gaussian filterbank for chroma extraction.

    Each row = one pitch class (C, C#, D, ..., B), with Gaussians summed
    across octaves. Uses constant-Q sigma (half-semitone) with a floor
    of 1.0 bin widths for low-frequency robustness.

    freqs must be a linearly-spaced rfftfreq array starting at 0.
    """
    n_bins = len(freqs)
    filterbank = np.zeros((NUM_CHROMA_BINS, n_bins), dtype=np.float64)
    freq_resolution = float(freqs[1] - freqs[0])
    bin_indices = np.arange(n_bins)

    for chroma_idx in range(NUM_CHROMA_BINS):
        for octave in range(min_octave, max_octave + 1):
            midi = 12 * (octave + 1) + chroma_idx
            center_hz = 440.0 * 2.0 ** ((midi - 69) / 12.0)

            sigma_hz = center_hz * (2.0 ** (1.0 / 24.0) - 1.0)
            sigma_bins = max(sigma_hz / freq_resolution, 1.0)

            center_bin = center_hz / freq_resolution
            gaussian = np.exp(-0.5 * ((bin_indices - center_bin) / sigma_bins) ** 2)
            filterbank[chroma_idx] += gaussian

    row_sums = filterbank.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    filterbank /= row_sums

    return filterbank


def compute_chroma(
    magnitudes: np.ndarray,
    filterbank: np.ndarray,
) -> list[float]:
    """Compute 12-bin chromagram from FFT magnitudes.

    Accepts raw FFT magnitudes; squaring to power spectrum is applied
    internally. Do not pre-square the input.

    Returns pitch-class energy (C, C#, D, ..., B) as weighted sum
    of power spectrum through the Gaussian filterbank.
    """
    power = magnitudes ** 2
    chroma = filterbank @ power
    return chroma.tolist()


def compute_onset_strength(rms: float, prev_rms: float) -> float:
    """Onset strength as positive RMS delta. Zero on steady or declining signal."""
    delta = rms - prev_rms
    return max(delta, 0.0)


def compute_spectral_centroid(magnitudes: np.ndarray, freqs: np.ndarray) -> float:
    """Weighted mean frequency by magnitude. Returns Hz, or 0.0 for silence."""
    total = float(np.sum(magnitudes))
    if total < 1e-10:
        return 0.0
    return float(np.sum(freqs * magnitudes) / total)


def compute_spectral_flatness(magnitudes: np.ndarray) -> float:
    """Geometric/arithmetic mean ratio of power spectrum. 0=tonal, 1=noise."""
    power = magnitudes ** 2
    arithmetic_mean = float(np.mean(power))
    if arithmetic_mean < 1e-20:
        return 0.0
    # eps tied to the arithmetic-mean guard (power scale), not an arbitrary
    # floor — a coarse floor misclassifies quiet pure tones as maximally noisy.
    log_mean = float(np.mean(np.log(power + 1e-20)))
    geometric_mean = float(np.exp(log_mean))
    return min(geometric_mean / arithmetic_mean, 1.0)


class TonalChangeDetector:
    """Cosine distance between fast and slow chroma EMAs.

    Fires on harmonic section changes (verse→chorus, key shifts) while
    staying low for per-chord variation within a single key. Silence does
    not update the EMAs — otherwise references would decay to zero and
    produce spurious spikes on resume.
    """

    def __init__(
        self,
        fast_window_s: float = 2.0,
        slow_window_s: float = 20.0,
        fps: int = 30,
    ):
        dt = 1.0 / fps
        self._alpha_fast = dt / (fast_window_s + dt)
        self._alpha_slow = dt / (slow_window_s + dt)
        self._fast: np.ndarray | None = None
        self._slow: np.ndarray | None = None

    def update(self, chroma: tuple[float, ...], is_silent: bool) -> float:
        """Feed one chroma frame. Returns cosine distance in [0, 1]."""
        if is_silent:
            return 0.0
        c = np.asarray(chroma, dtype=np.float64)
        if self._fast is None:
            self._fast = c.copy()
            self._slow = c.copy()
            return 0.0
        self._fast = self._alpha_fast * c + (1 - self._alpha_fast) * self._fast
        self._slow = self._alpha_slow * c + (1 - self._alpha_slow) * self._slow
        nf = float(np.linalg.norm(self._fast))
        ns = float(np.linalg.norm(self._slow))
        if nf < 1e-6 or ns < 1e-6:
            return 0.0
        similarity = float(np.dot(self._fast, self._slow) / (nf * ns))
        return max(0.0, 1.0 - similarity)


class BeatDetector:
    """Energy-threshold beat detector with refractory period."""

    def __init__(
        self,
        history_len: int = 96,
        threshold: float = 1.5,
        refractory_frames: int = 14,
    ):
        self._history: deque[float] = deque(maxlen=history_len)
        self._threshold = threshold
        self._refractory = refractory_frames
        self._cooldown = 0

    def update(self, bass_energy: float) -> bool:
        """Feed bass energy for this frame. Returns True on beat onset."""
        if self._history.maxlen is not None and len(self._history) < self._history.maxlen:
            self._history.append(bass_energy)
            return False

        avg = sum(self._history) / len(self._history)
        is_beat = (
            self._cooldown == 0
            and avg > 0
            and bass_energy > avg * self._threshold
        )

        self._history.append(bass_energy)

        if is_beat:
            self._cooldown = self._refractory
        elif self._cooldown > 0:
            self._cooldown -= 1
        return is_beat


SAMPLE_RATE = 48000
BLOCK_SIZE = 1024
FFT_SIZE = 2048


class AudioCapture:
    """Captures audio from a sounddevice input and produces AudioFrames."""

    def __init__(
        self,
        device_index: int | None = None,
        sample_rate: int = SAMPLE_RATE,
        block_size: int = BLOCK_SIZE,
        fft_size: int = FFT_SIZE,
        external_queue: queue.SimpleQueue[np.ndarray] | None = None,
    ):
        self._device_index = device_index
        self._external = external_queue is not None
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._fft_size = fft_size
        self._queue: queue.SimpleQueue[np.ndarray] = (
            external_queue if external_queue is not None else queue.SimpleQueue()
        )
        self._ring = np.zeros(fft_size, dtype=np.float32)
        self._window = np.hanning(fft_size).astype(np.float32)
        self._freqs = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
        self._beat_detector = BeatDetector()
        self._mid_beat_detector = BeatDetector()
        self._high_beat_detector = BeatDetector()
        self._prev_magnitudes: np.ndarray | None = None
        self._prev_rms: float = 0.0
        self._peak_flux: float = 0.0
        self._peak_onset: float = 0.0
        self._bass_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)
        self._mid_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)
        self._high_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)
        self._peak_energy: float = 0.0
        self._rms_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)
        self._peak_rms: float = 0.0
        self._spectrum_bin_indices, _ = build_spectrum_bin_edges(self._freqs)
        self._chroma_filterbank = build_chroma_filterbank(self._freqs)
        self._peak_chroma: float = 0.0
        self._chroma_filters = [
            ExpFilter(alpha_rise=0.6, alpha_decay=0.1) for _ in range(NUM_CHROMA_BINS)
        ]
        self._flatness_filter = ExpFilter(alpha_rise=0.8, alpha_decay=0.15)
        self._tonal_detector = TonalChangeDetector()
        self._stream: sd.InputStream | None = None

    @staticmethod
    def _update_peak(current_peak: float, raw_value: float) -> float:
        """Decay a peak tracker, with fast decay when signal is well below peak."""
        if raw_value < SILENCE_FLOOR or raw_value < current_peak * 0.05:
            decay = PEAK_SILENCE_DECAY
        else:
            decay = PEAK_DECAY
        return max(raw_value, current_peak * decay)

    def _callback(
        self, indata: np.ndarray, frames: int, time_info: object, status: object
    ) -> None:
        self._queue.put_nowait(indata[:, 0].copy())

    def start(self) -> None:
        if self._external:
            return  # queue already being fed by an external source
        self._stream = sd.InputStream(
            device=self._device_index,
            samplerate=self._sample_rate,
            blocksize=self._block_size,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._external:
            return  # external source manages its own lifecycle
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def process_latest(self) -> AudioFrame | None:
        """Drain the queue and process the latest chunk.

        Only the most recent audio chunk is rolled into the ring buffer.
        Intermediate chunks are intentionally discarded to minimize latency --
        we always want the freshest audio, not a complete history.
        """
        chunk = None
        try:
            while True:
                chunk = self._queue.get_nowait()
        except queue.Empty:
            pass

        if chunk is None:
            return None

        # Roll new samples into ring buffer
        n = len(chunk)
        self._ring = np.roll(self._ring, -n)
        self._ring[-n:] = chunk

        # FFT with Hann window
        windowed = self._ring * self._window
        magnitudes = np.abs(np.fft.rfft(windowed))

        # Band energies
        raw_bass, raw_mids, raw_highs = compute_band_energies(
            magnitudes, self._freqs
        )

        # Running-peak AGC normalization
        max_energy = max(raw_bass, raw_mids, raw_highs)
        self._peak_energy = self._update_peak(self._peak_energy, max_energy)
        scale = 1.0 / (self._peak_energy + 1e-10)

        bass = self._bass_filter.update(raw_bass * scale)
        mids = self._mid_filter.update(raw_mids * scale)
        highs = self._high_filter.update(raw_highs * scale)

        dominant_freq = compute_dominant_freq(magnitudes, self._freqs)
        raw_rms = float(np.sqrt(np.mean(chunk**2)))
        self._peak_rms = self._update_peak(self._peak_rms, raw_rms)
        rms = self._rms_filter.update(raw_rms / (self._peak_rms + 1e-10))
        is_beat = self._beat_detector.update(raw_bass)
        mid_beat = self._mid_beat_detector.update(raw_mids)
        high_beat = self._high_beat_detector.update(raw_highs)

        # Spectral flux (AGC-normalized like band energies)
        if self._prev_magnitudes is not None:
            raw_flux = compute_spectral_flux(magnitudes, self._prev_magnitudes)
            self._peak_flux = self._update_peak(self._peak_flux, raw_flux)
            spectral_flux = raw_flux / (self._peak_flux + 1e-10)
        else:
            spectral_flux = 0.0
        self._prev_magnitudes = magnitudes.copy()

        # Onset strength (positive RMS delta, AGC-normalized)
        raw_onset = compute_onset_strength(raw_rms, self._prev_rms)
        if self._peak_onset == 0.0 and raw_onset > 0.0:
            # Cold start: seed the AGC peak, suppress the first-frame spike
            self._peak_onset = raw_onset
            onset_strength = 0.0
        else:
            self._peak_onset = self._update_peak(self._peak_onset, raw_onset)
            onset_strength = raw_onset / (self._peak_onset + 1e-10)
        self._prev_rms = raw_rms

        # Spectrum bins (same AGC scale as band energies)
        raw_bins = compute_spectrum_bins(
            magnitudes, self._freqs, bin_indices=self._spectrum_bin_indices,
        )
        spectrum = tuple(b * scale for b in raw_bins)

        # Chroma (AGC + ExpFilter smoothing, like band energies)
        raw_chroma = compute_chroma(magnitudes, self._chroma_filterbank)
        max_chroma = max(raw_chroma)
        self._peak_chroma = self._update_peak(self._peak_chroma, max_chroma)
        chroma_scale = 1.0 / (self._peak_chroma + 1e-10)
        chroma = tuple(
            self._chroma_filters[i].update(raw_chroma[i] * chroma_scale)
            for i in range(NUM_CHROMA_BINS)
        )

        # Spectral centroid (raw Hz, no normalization — like dominant_freq)
        spectral_centroid = compute_spectral_centroid(magnitudes, self._freqs)

        # Spectral flatness (self-normalizing 0-1, ExpFilter smoothed)
        raw_flatness = compute_spectral_flatness(magnitudes)
        spectral_flatness = self._flatness_filter.update(raw_flatness)

        # Tonal change (cosine distance between fast/slow chroma EMAs)
        is_silent = raw_rms < SILENCE_FLOOR
        tonal_change = self._tonal_detector.update(chroma, is_silent)

        return AudioFrame(
            bass=bass,
            mids=mids,
            highs=highs,
            dominant_freq=dominant_freq,
            rms=rms,
            raw_rms=raw_rms,
            is_beat=is_beat,
            timestamp=time.monotonic(),
            onset_strength=onset_strength,
            spectral_flux=spectral_flux,
            mid_beat=mid_beat,
            high_beat=high_beat,
            spectrum=spectrum,
            chroma=chroma,
            spectral_centroid=spectral_centroid,
            spectral_flatness=spectral_flatness,
            tonal_change=tonal_change,
        )
