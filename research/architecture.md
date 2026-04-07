# NuPhy Air75 V2 Music-Reactive RGB - Architecture

## Overview

Programmatic control of NuPhy Air75 V2 per-key RGB LEDs from macOS,
with real-time music-reactive visualizations via audio capture and FFT analysis.

## System Architecture

```
+-----------------------------------------------------+
|  macOS Host (Python)                                 |
|                                                      |
|  +---------------+    +---------------+              |
|  | BlackHole     |--->| sounddevice   |              |
|  | (loopback)    |    | callback      |              |
|  +---------------+    +-------+-------+              |
|                               | audio frames         |
|                        +------v-------+              |
|                        | numpy FFT    |              |
|                        | beat detect  |              |
|                        +------+-------+              |
|                               | RGB values           |
|                        +------v-------+  USB Raw HID |
|                        | pyhidapi     |--------+     |
|                        | (hid lib)    |        |     |
|                        +--------------+        |     |
+------------------------------------------------|-----+
                                                 |
                   32-byte packets               |
                   cmd=0x24, 9 LEDs/packet        |
                                                 |
+------------------------------------------------|-----+
|  NuPhy Air75 V2 (STM32F072, QMK)              |     |
|                                                |     |
|  +---------------+    +---------------+        |     |
|  | raw_hid_      |<---| USB HID       |<------+     |
|  | receive()     |    | endpoint      |              |
|  +-------+-------+    +---------------+              |
|          | parse packet                              |
|  +-------v-------+                                   |
|  | rgb_matrix_   |   84 per-key LEDs                 |
|  | set_color()   |   + side light bars (separate)    |
|  +---------------+                                   |
+------------------------------------------------------+
```

## Two Workstreams

### Phase 1: Host-to-Keyboard RGB Control

Get basic per-key color control working end-to-end.

**Firmware side (~50 lines C):**
- Fork `ryodeushii/qmk-firmware` (most maintained NuPhy QMK fork)
- Add `raw_hid_receive()` handler via `via_command_kb()` hook
- Adapt SignalRGB protocol from `zhouzengming/Nuphy-qmk-SignalRGB`

**Host side (Python):**
- Open Raw HID interface via `pyhidapi`
- Send per-key color commands
- Validate with static color test

### Phase 2: Music-Reactive Visualizations

Layer audio capture and beat detection on top of Phase 1.

- Capture system audio via BlackHole loopback
- Real-time FFT with numpy
- Beat detection via bass-band energy thresholding
- Map frequency bands / energy to per-key colors
