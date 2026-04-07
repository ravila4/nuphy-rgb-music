# Host Software Research - macOS

## Python Dependencies

| Component       | Library        | Install                        | Notes                              |
|-----------------|----------------|--------------------------------|------------------------------------|
| USB HID         | `hid` (pyhidapi) | `brew install hidapi && pip install hid` | ctypes-based, v1.0.9    |
| Audio capture   | `sounddevice`  | `pip install sounddevice`      | PortAudio bindings, callback-based |
| FFT             | `numpy`        | `pip install numpy`            | numpy.fft is fast enough real-time |
| Audio loopback  | BlackHole      | `brew install blackhole-2ch`   | Virtual audio loopback driver      |

### Why These Libraries

- **`hid` over `hidapi`**: Better documented, actively maintained, ctypes-based
  (no compilation needed). On macOS, `enumerate()` returns `usage_page` and
  `usage` fields (via IOHIDManager), which is how we identify the Raw HID
  interface vs keyboard/consumer interfaces.

- **`sounddevice` over `pyaudio`**: Cleaner API, easier macOS install,
  callback-based for low-latency real-time processing.

- **`numpy.fft` over `librosa`**: librosa's beat detection is designed for
  offline analysis and pulls in heavy deps (scipy, numba). For real-time,
  a rolling energy comparison on raw FFT is simpler and lower-latency.

## USB HID Communication

### Device Enumeration

```python
import hid

devices = hid.enumerate(vid=0x19F5, pid=0x3246)
# Filter for the Raw HID interface:
raw_hid_path = next(
    d['path'] for d in devices
    if d['usage_page'] == 0xFF60 and d['usage'] == 0x61
)
```

### Sending RGB Data

```python
with hid.Device(path=raw_hid_path) as h:
    # Write: first byte is report ID (0x00 for Raw HID)
    # Total write = 33 bytes (1 report ID + 32 payload)
    packet = bytes([0x00, 0x24, start_idx, num_leds]) + rgb_bytes
    packet = packet.ljust(33, b'\x00')  # pad to 33
    h.write(packet)

    # Read response (optional, 32 bytes, timeout in ms)
    response = h.read(32, timeout=100)
```

### Full Frame Update

84 LEDs / 9 LEDs per packet = 10 packets per frame.

```python
def send_frame(device, colors: list[tuple[int, int, int]]):
    """Send full 84-LED frame. colors is list of (R, G, B) tuples."""
    for start in range(0, len(colors), 9):
        chunk = colors[start:start + 9]
        rgb_bytes = b''.join(bytes(c) for c in chunk)
        packet = bytes([0x00, 0x24, start, len(chunk)]) + rgb_bytes
        packet = packet.ljust(33, b'\x00')
        device.write(packet)
```

## Audio Capture

### BlackHole Setup (One-Time)

1. Install: `brew install blackhole-2ch`
2. Open **Audio MIDI Setup** (Spotlight -> "Audio MIDI Setup")
3. Click **+** -> **Create Multi-Output Device**
4. Check both your speakers/headphones AND BlackHole 2ch
5. Set the Multi-Output Device as system default output
6. In Python, open BlackHole as an **input** device

### Audio Stream

```python
import sounddevice as sd
import numpy as np

# Find BlackHole device
devices = sd.query_devices()
blackhole_idx = next(
    i for i, d in enumerate(devices)
    if 'BlackHole' in d['name']
)

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024   # ~23ms latency

def audio_callback(indata, frames, time, status):
    mono = indata[:, 0]

    # FFT
    fft = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / SAMPLE_RATE)

    # Frequency bands
    bass = np.sum(fft[(freqs >= 20) & (freqs <= 150)] ** 2)
    mids = np.sum(fft[(freqs >= 150) & (freqs <= 2000)] ** 2)
    highs = np.sum(fft[(freqs >= 2000) & (freqs <= 16000)] ** 2)

    # ... map to RGB colors and send to keyboard

with sd.InputStream(
    device=blackhole_idx,
    samplerate=SAMPLE_RATE,
    blocksize=BLOCK_SIZE,
    channels=1,
    callback=audio_callback,
):
    sd.sleep(1_000_000)  # run until interrupted
```

## Beat Detection

Simple energy-threshold approach (lower latency than librosa):

```python
class BeatDetector:
    def __init__(self, history_size=43, threshold=1.5):
        # 43 frames @ 23ms each ~ 1 second of history
        self.history = np.zeros(history_size)
        self.idx = 0
        self.threshold = threshold

    def is_beat(self, bass_energy: float) -> bool:
        avg = np.mean(self.history)
        self.history[self.idx % len(self.history)] = bass_energy
        self.idx += 1
        return bass_energy > avg * self.threshold and avg > 0
```

## Visualization Ideas

| Effect               | Description                                          |
|----------------------|------------------------------------------------------|
| Bass pulse           | All keys flash on beat, intensity = bass energy      |
| Spectrum bars        | Each column = frequency band, height = energy        |
| Ripple               | Beat triggers color ripple from center outward       |
| Color wash           | Hue shifts with dominant frequency, brightness = energy |
| Rain                 | Random keys light up, rate proportional to energy    |

## Alternative: No BlackHole (Per-App Capture)

Apple's ScreenCaptureKit can capture audio per-app without a kernel extension,
but it requires user permission per app and isn't system-wide. The
`AudioCap` wrapper (github.com/insidegui/AudioCap) makes it more accessible.
For system-wide capture, BlackHole remains the standard approach.

## Existing Reference Projects

| Project                          | What it does                              | Relevant bits                    |
|----------------------------------|-------------------------------------------|----------------------------------|
| Drugantibus/qmk-hid-rgb         | Python Raw HID RGB control for QMK        | Protocol implementation          |
| agustinmista/qmk-rgb-live       | WebHID-based dynamic RGB for QMK          | Browser-based alternative        |
| FrameworkComputer/qmk_hid       | Rust CLI for QMK RGB via Raw HID/VIA      | Rust alternative                 |
| CalcProgrammer1/KeyboardVisualizer | Music-reactive RGB via OpenRGB SDK      | Viz algorithms (no NuPhy support)|
| aiXander/Realtime_PyAudio_FFT    | Real-time FFT visualization in Python    | Audio processing patterns        |
