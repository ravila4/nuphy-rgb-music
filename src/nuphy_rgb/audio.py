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
    spectral_centroid: float = 0.0


class ExpFilter:
    """Asymmetric exponential smoothing filter.

    Fast attack (alpha_rise) for responsive transients,
    slow decay (alpha_decay) for smooth falloff.
    """

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
    """Compute energy in bass, mid, and high frequency bands.

    Returns (bass, mids, highs) as raw energy values (sum of squared magnitudes).
    """
    bass_mask = (freqs >= BASS_LOW) & (freqs <= BASS_HIGH)
    mid_mask = (freqs >= MID_LOW) & (freqs <= MID_HIGH)
    high_mask = (freqs >= HIGH_LOW) & (freqs <= HIGH_HIGH)

    bass = float(np.sum(magnitudes[bass_mask] ** 2))
    mids = float(np.sum(magnitudes[mid_mask] ** 2))
    highs = float(np.sum(magnitudes[high_mask] ** 2))
    return bass, mids, highs


def compute_dominant_freq(magnitudes: np.ndarray, freqs: np.ndarray) -> float:
    """Return the frequency (Hz) with the highest magnitude.

    Returns 0.0 for near-silence (avoids noise-floor flicker).
    """
    if np.max(magnitudes) < 1e-6:
        return 0.0
    return float(freqs[np.argmax(magnitudes)])


def compute_spectral_flux(
    magnitudes: np.ndarray, prev_magnitudes: np.ndarray
) -> float:
    """Half-wave rectified spectral flux: sum of positive magnitude changes.

    Only increases count — decreasing bins are ignored. This captures
    the onset of new spectral energy (new notes, percussive hits).
    """
    diff = magnitudes - prev_magnitudes
    return float(np.sum(np.maximum(diff, 0.0)))


def compute_spectrum_bins(
    magnitudes: np.ndarray,
    freqs: np.ndarray,
    num_bins: int = NUM_SPECTRUM_BINS,
    min_freq: float = 20.0,
    max_freq: float = 16000.0,
) -> list[float]:
    """Bin FFT magnitudes into log-spaced frequency bands.

    Returns a list of `num_bins` floats — mean squared magnitude per band.
    Frequencies outside [min_freq, max_freq] are excluded.
    """
    log_edges = np.logspace(
        np.log10(min_freq), np.log10(max_freq), num_bins + 1
    )
    result: list[float] = []
    for i in range(num_bins):
        mask = (freqs >= log_edges[i]) & (freqs < log_edges[i + 1])
        if np.any(mask):
            result.append(float(np.mean(magnitudes[mask] ** 2)))
        else:
            result.append(0.0)
    return result


def compute_spectral_centroid(magnitudes: np.ndarray, freqs: np.ndarray) -> float:
    """Weighted average frequency — the 'center of mass' of the spectrum.

    Returns 0.0 on silence.
    """
    total = np.sum(magnitudes)
    if total < 1e-10:
        return 0.0
    return float(np.sum(magnitudes * freqs) / total)


def compute_onset_strength(rms: float, prev_rms: float) -> float:
    """Onset strength as positive RMS delta. Zero on steady or declining signal."""
    delta = rms - prev_rms
    return max(delta, 0.0)


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
        if len(self._history) < self._history.maxlen:
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
    """Captures audio from a sounddevice input and produces AudioFrames.

    The PortAudio callback only copies buffers into a queue (no FFT, no allocation).
    Call process_latest() from the main loop to do all DSP work.
    """

    def __init__(
        self,
        device_index: int | None = None,
        sample_rate: int = SAMPLE_RATE,
        block_size: int = BLOCK_SIZE,
        fft_size: int = FFT_SIZE,
    ):
        self._device_index = device_index
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._fft_size = fft_size
        self._queue: queue.SimpleQueue[np.ndarray] = queue.SimpleQueue()
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
        self._stream: sd.InputStream | None = None

    def _callback(
        self, indata: np.ndarray, frames: int, time_info: object, status: object
    ) -> None:
        self._queue.put_nowait(indata[:, 0].copy())

    def start(self) -> None:
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
        self._peak_energy = max(max_energy, self._peak_energy * 0.995)
        scale = 1.0 / (self._peak_energy + 1e-10)

        bass = self._bass_filter.update(raw_bass * scale)
        mids = self._mid_filter.update(raw_mids * scale)
        highs = self._high_filter.update(raw_highs * scale)

        dominant_freq = compute_dominant_freq(magnitudes, self._freqs)
        spectral_centroid = compute_spectral_centroid(magnitudes, self._freqs)
        raw_rms = float(np.sqrt(np.mean(chunk**2)))
        self._peak_rms = max(raw_rms, self._peak_rms * 0.995)
        rms = self._rms_filter.update(raw_rms / (self._peak_rms + 1e-10))
        is_beat = self._beat_detector.update(raw_bass)
        mid_beat = self._mid_beat_detector.update(raw_mids)
        high_beat = self._high_beat_detector.update(raw_highs)

        # Spectral flux (AGC-normalized like band energies)
        if self._prev_magnitudes is not None:
            raw_flux = compute_spectral_flux(magnitudes, self._prev_magnitudes)
            self._peak_flux = max(raw_flux, self._peak_flux * 0.995)
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
            self._peak_onset = max(raw_onset, self._peak_onset * 0.995)
            onset_strength = raw_onset / (self._peak_onset + 1e-10)
        self._prev_rms = raw_rms

        # Spectrum bins (same AGC scale as band energies)
        raw_bins = compute_spectrum_bins(magnitudes, self._freqs)
        spectrum = tuple(b * scale for b in raw_bins)

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
            spectral_centroid=spectral_centroid,
        )
