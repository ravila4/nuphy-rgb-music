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
        raw_rms = float(np.sqrt(np.mean(chunk**2)))
        self._peak_rms = max(raw_rms, self._peak_rms * 0.995)
        rms = self._rms_filter.update(raw_rms / (self._peak_rms + 1e-10))
        is_beat = self._beat_detector.update(raw_bass)

        return AudioFrame(
            bass=bass,
            mids=mids,
            highs=highs,
            dominant_freq=dominant_freq,
            rms=rms,
            is_beat=is_beat,
            timestamp=time.monotonic(),
        )
