# Side LED Research — NuPhy Air75 V2

## Overview

The Air75 V2 has two WS2812 side light bars (6 LEDs each, 12 total) that
run independently from the 84 per-key RGB matrix. They share a single data
line and are driven by custom NuPhy code outside QMK's `rgb_matrix` system.

**No existing host-side control protocol exists for these LEDs.** Adding one
is straightforward — the per-key streaming protocol provides the template.

## Hardware

```text
         USB-C
           │
    ┌──────┴──────┐
    │  STM32F072  │
    │             │
    │  A7 (PWM) ──┼──► Per-key RGB matrix (84 LEDs, WS2812 via PWMD3)
    │             │
    │  C8 (GPIO) ─┼──► Side LED chain (12 LEDs, WS2812 bit-bang)
    │  C9 (CS)    │
    └─────────────┘
```

| Parameter      | Value                                    |
|----------------|------------------------------------------|
| LED count      | 12 (6 left + 6 right)                    |
| Data pin       | C8 (`DRIVER_SIDE_PIN`)                   |
| CS pin         | C9 (`DRIVER_SIDE_CS_PIN`, unused by driver) |
| Protocol       | WS2812, bit-banged with interrupt disable |
| Color order    | GRB (driver handles conversion)          |
| Refresh rate   | 50ms (~20 Hz) in `side_led_show()`       |

### Physical Layout

```text
    LEFT STRIP                                      RIGHT STRIP
    ┌───┐                                           ┌───┐
    │ 0 │  ┌─────────────────────────────────────┐  │ 6 │
    │ 1 │  │  Esc F1 F2 F3 F4 F5 F6 F7 ...  Del  │  │ 7 │
    │ 2 │  │  `   1  2  3  4  5  6  7  ...  Bks  │  │ 8 │
    │ 3 │  │  Tab Q  W  E  R  T  Y  U  ... PgUp  │  │ 9 │
    │ 4 │  │  Cap A  S  D  F  G  H  J  ... PgDn  │  │10 │
    │ 5 │  │  Sft Z  X  C  V  B  N  M  ...  Up   │  │11 │
    └───┘  │  Ctl Opt Cmd  Space  Cmd Fn  ← ↓ →  │  └───┘
           └─────────────────────────────────────┘
```

All 12 LEDs are on a single WS2812 chain — left first (0-5), then right
(6-11). One call to `side_ws2812_setleds(side_leds, 12)` writes the
entire chain.

## Firmware Architecture

### Buffer & Driver

```c
// side.c — shared buffer for both strips
RGB side_leds[SIDE_LED_NUM];  // SIDE_LED_NUM = 12

// Set individual LED color (both strips use this)
void side_rgb_set_color(int index, uint8_t red, uint8_t green, uint8_t blue);

// Flush buffer to hardware
void side_rgb_refresh(void);  // → side_ws2812_setleds(side_leds, 12)
```

The driver (`side_driver.c`) bit-bangs WS2812 protocol on pin C8:

- `chSysLock()` to disable interrupts during TX
- MSB-first, 900ns/350ns timing per bit
- GRB byte order (driver handles RGB→GRB conversion)

### Effect Engine

```text
housekeeping_task_kb()              [ansi.c]
  └─► side_led_show()               [side.c]
       ├─► left mode handler         (side_wave/mix/breath/static/off)
       ├─► right_side_led_loop()     [side_right.c]
       │    └─► right mode handler   (right_side_wave/mix/breath/static/off)
       ├─► battery/RF/caps overlays
       └─► if 50ms elapsed:
            └─► side_rgb_refresh()   (write to hardware)
```

Left and right strips have **independent** config (mode, brightness, speed,
color), stored in `kb_config_t` and persisted to EEPROM via VIA.

### Available Effects

| ID | Name       | Behavior                                    |
|----|------------|---------------------------------------------|
| 0  | SIDE_WAVE  | Sine wave brightness with color cycling     |
| 1  | SIDE_MIX   | Rainbow rotation (all LEDs same color)      |
| 2  | SIDE_BREATH| Smooth pulse/breathing                      |
| 3  | SIDE_STATIC| Solid color                                 |
| 4  | SIDE_OFF   | All off                                     |

Speed: 5 levels (10-38ms per animation frame).
Brightness: 6 levels (0, 16, 32, 64, 128, 255).
Colors: 8 preset + off, or rainbow mode using 224-step flow table.

### Configuration (kb_config_t)

```c
// Left side
uint8_t side_mode;            // 0-4
uint8_t side_brightness;      // 0-5
uint8_t side_speed;           // 0-4
uint8_t side_rgb;             // 0=fixed color, 1=rainbow
uint8_t side_color;           // 0-8

// Right side (independent)
uint8_t right_side_mode;
uint8_t right_side_brightness;
uint8_t right_side_speed;
uint8_t right_side_rgb;
uint8_t right_side_color;
```

### Helper Functions

```c
// Left: sets all 6 LEDs, brightness divided by 4 (>> 2)
void set_side_rgb(uint8_t r, uint8_t g, uint8_t b);

// Right: sets all 6 LEDs, brightness divided by 2 (>> 1)
void set_right_side_rgb(uint8_t r, uint8_t g, uint8_t b);
```

Note the asymmetric brightness scaling — left divides by 4, right by 2.
This may be a hardware calibration difference or a bug.

## Key Files

```text
~/Projects/qmk-firmware/keyboards/nuphy/air75v2/ansi/
  side.c            Left strip effects + shared infrastructure (side_leds, refresh)
  side_right.c      Right strip effects (261 lines, simplified subset of side.c)
  side_driver.c     WS2812 bit-bang driver
  side_table.h      Animation lookup tables (wave, breathe, rainbow flow)
  side.h            Constants: SIDE_LINE=6, RIGHT_SIDE_LINE=6, SIDE_LED_NUM=12
  config.h          Pin defs: DRIVER_SIDE_PIN=C8, DRIVER_SIDE_CS_PIN=C9
  ansi.c            housekeeping_task_kb() calls side_led_show()
  ansi.h            kb_config_t struct, VIA config IDs
```

## Proposed Host Control Protocol

### Design

Mirror the existing per-key streaming protocol. Use unused command IDs
starting at `0x28`.

```text
Existing (per-key):
  0x24  CMD_STREAM_RGB_DATA        host → kb  (per-key LED data)
  0x25  CMD_STREAMING_MODE_ON      host → kb  (disable local effects)
  0x26  CMD_STREAMING_MODE_OFF     host → kb  (re-enable local effects)
  0x27  CMD_GET_TOTAL_LEDS         host ↔ kb  (query LED count)

New (side LEDs):
  0x28  CMD_STREAM_SIDE_DATA       host → kb  (side LED data)
  0x29  CMD_SIDE_STREAMING_ON      host → kb  (disable local side effects)
  0x2A  CMD_SIDE_STREAMING_OFF     host → kb  (re-enable local side effects)
```

### Packet Format (0x28)

```text
Byte 0: 0x28 (CMD_STREAM_SIDE_DATA)
Byte 1: start_led_index (0-11)
Byte 2: num_leds (max 9 per packet, but 12 LEDs = 2 packets at most)
Byte 3+: R, G, B, R, G, B, ...
```

Full side update: 2 packets (9 + 3 LEDs). Negligible bandwidth.

### Firmware Changes

```c
// ansi.c — new static
static bool side_streaming_mode = false;

// In via_command_kb():
case CMD_SIDE_STREAMING_ON:
    side_streaming_mode = true;
    data[1] = 0x01;
    raw_hid_send(data, length);
    return true;

case CMD_SIDE_STREAMING_OFF:
    side_streaming_mode = false;
    data[1] = 0x01;
    raw_hid_send(data, length);
    return true;

case CMD_STREAM_SIDE_DATA: {
    if (!side_streaming_mode) return true;
    uint8_t start = data[1];
    if (start >= SIDE_LED_NUM) return true;
    uint8_t count = data[2];
    if ((uint16_t)start + count > SIDE_LED_NUM)
        count = SIDE_LED_NUM - start;
    uint8_t max_from_packet = (length - 3) / 3;
    if (count > max_from_packet)
        count = max_from_packet;
    for (uint8_t i = 0; i < count; i++) {
        uint8_t off = 3 + i * 3;
        side_rgb_set_color(start + i, data[off], data[off + 1], data[off + 2]);
    }
    side_rgb_refresh();
    return true;
}
```

```c
// side.c — in side_led_show():
void side_led_show(void) {
    if (side_streaming_mode) return;  // host owns side LEDs
    // ... existing effect logic ...
}
```

### Host-Side Changes

```python
# hid_utils.py — new constants
CMD_STREAM_SIDE_DATA    = 0x28
CMD_SIDE_STREAMING_ON   = 0x29
CMD_SIDE_STREAMING_OFF  = 0x2A
SIDE_LED_COUNT          = 12

def send_side_frame(device: hid.device, colors: list[tuple[int, int, int]]) -> None:
    """Send side LED colors. 12 LEDs = 2 packets max."""
    for start in range(0, len(colors), LEDS_PER_PACKET):
        chunk = colors[start : start + LEDS_PER_PACKET]
        rgb_bytes = []
        for r, g, b in chunk:
            rgb_bytes.extend((r, g, b))
        device.write(build_packet(CMD_STREAM_SIDE_DATA, start, len(chunk), *rgb_bytes))
```

## Open Questions

1. **Brightness asymmetry:** Left strip divides by 4, right by 2. Is this
   intentional calibration or a bug? Should host-side streaming bypass
   this scaling (raw values) or match it?

2. **Battery/RF overlays:** When side_streaming_mode is on, should we
   suppress battery level indicators on the side LEDs? Probably yes for
   full visual control, but losing battery indication could be annoying.
   Could reserve one LED for status, or flash a brief battery overlay
   on keypress.

3. **Refresh rate:** The 50ms refresh in `side_led_show()` is bypassed
   in streaming mode (we call `side_rgb_refresh()` directly per packet).
   Since there are only 12 LEDs and bit-bang is fast, this should be fine,
   but worth profiling to ensure no impact on key scanning.

4. **Combined streaming:** Should `CMD_STREAMING_MODE_ON` (0x25) also
   enable side streaming? Or keep them independent so you can run local
   side effects while streaming per-key? Independent is more flexible.

## Competitive Landscape

| Solution | Side LED control | Music reactive | Platform |
|----------|-----------------|----------------|----------|
| **This project (proposed)** | Per-LED host streaming | Yes | macOS |
| NuPhy V3 "rhythm light bar" | Canned firmware effects | Limited | Firmware only |
| SignalRGB + community fork | No side LED support | Via SignalRGB | Windows |
| Stock NuPhy firmware | 5 preset effects | No | Firmware only |

**Nobody else offers host-controlled side LEDs on NuPhy keyboards.**
