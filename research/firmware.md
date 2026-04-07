# Firmware Research - NuPhy Air75 V2

## Hardware Specs

| Parameter          | Value                                        |
|--------------------|----------------------------------------------|
| MCU                | STM32F072                                    |
| Bootloader         | stm32-dfu                                    |
| USB VID            | `0x19F5`                                     |
| USB PID            | `0x3246`                                     |
| RGB LED count      | 84 (per-key, WS2812 via PWM on PWMD3 ch. 2) |
| Side LEDs          | ~12 total (6L + 6R), separate WS2812 strips  |
| Max brightness     | 190                                          |
| Matrix             | 6 rows x 17 cols, COL2ROW                    |

## QMK Firmware Forks

| Fork                              | Branch             | Notes                                        |
|-----------------------------------|--------------------|----------------------------------------------|
| ryodeushii/qmk-firmware           | nuphy-keyboards    | Most maintained, RGB perf fixes, no SignalRGB |
| zhouzengming/Nuphy-qmk-SignalRGB  | nuphy-keyboards    | Adds SignalRGB host RGB control               |
| qbane/qmk_firmware_nuphy          | --                 | Custom Air75 V2 firmware                      |

Reference tracker: `zhogov/nuphy-state-of-qmk-firmware`

### Directory Structure (ryodeushii fork)

```
keyboards/nuphy/air75v2/ansi/
  ansi.c            -- main keyboard logic, key processing, VIA handlers
  ansi.h            -- custom keycodes, kb_config_t struct
  config.h          -- hardware pin definitions, RGB config
  keyboard.json     -- QMK descriptor (USB IDs, matrix, features)
  rules.mk          -- build sources
  user_kb.c/h       -- RF, sleep, side LED helpers
  side.c            -- left side LED strip effects
  side_right.c      -- right side LED strip effects
  side_driver.c     -- WS2812 side LED driver
  side_table.h      -- side LED effect tables
  rf.c/rf_driver.c  -- wireless RF/BLE
  sleep.c           -- sleep/wake logic
  matrix.c          -- custom key matrix scanning
  keymaps/{default,via,ryodeushii}/
```

## QMK Raw HID Protocol

| Parameter    | Value                                              |
|--------------|----------------------------------------------------|
| Usage Page   | `0xFF60` (vendor-defined, configurable)             |
| Usage ID     | `0x61`                                             |
| Packet size  | 32 bytes, both directions, always exactly 32        |
| Enable       | `RAW_ENABLE = yes` in rules.mk                     |

### Firmware Callback

```c
void raw_hid_receive(uint8_t *data, uint8_t length) {
    // data = 32-byte buffer from host
    // length = always 32
    // Process, then optionally:
    raw_hid_send(response, 32);  // send 32 bytes back
}
```

**Important:** When VIA is enabled (which it is in ryodeushii fork), VIA takes over
`raw_hid_receive()`. Custom commands must hook into `via_command_kb()` instead.

## SignalRGB Protocol (Reference Implementation)

Source: `zhouzengming/Nuphy-qmk-SignalRGB` -- `quantum/signalrgb.c`

### Command IDs

| Command                     | Byte 0 | Direction       |
|-----------------------------|--------|-----------------|
| `GET_QMK_VERSION`           | `0x21` | host <-> kb     |
| `GET_PROTOCOL_VERSION`      | `0x22` | host <-> kb     |
| `GET_UNIQUE_IDENTIFIER`     | `0x23` | host <-> kb     |
| **`STREAM_RGB_DATA`**       | `0x24` | **host -> kb**  |
| `SET_SIGNALRGB_MODE_ENABLE` | `0x25` | host -> kb      |
| `SET_SIGNALRGB_MODE_DISABLE`| `0x26` | host -> kb      |
| `GET_TOTAL_LEDS`            | `0x27` | host <-> kb     |
| `GET_FIRMWARE_TYPE`         | `0x28` | host <-> kb     |

### RGB Streaming Packet Format (0x24)

```
Byte 0: 0x24 (STREAM_RGB_DATA)
Byte 1: start_led_index
Byte 2: number_of_leds (max 9 per packet)
Byte 3+: R, G, B, R, G, B, ... (3 bytes per LED)
```

Max 9 LEDs per 32-byte packet: 3 header + 9*3 = 27 data = 30 bytes used.

To update all 84 LEDs: ceil(84/9) = 10 packets per frame.

### Firmware-Side Receiver

```c
void led_streaming(uint8_t *data) {
    uint8_t index = data[1];          // start LED index
    uint8_t numberofleds = data[2];   // count
    for (uint8_t i = 0; i < numberofleds; i++) {
        uint8_t offset = (i * 3) + 3;
        rgb_matrix_set_color(index + i, data[offset], data[offset+1], data[offset+2]);
    }
}
```

### VIA Compatibility Hook

```c
#if defined(VIA_ENABLE)
bool via_command_kb(uint8_t *data, uint8_t length) {
    return srgb_raw_hid_rx(data, length);  // intercepts unhandled VIA commands
}
#else
void raw_hid_receive(uint8_t *data, uint8_t length) {
    srgb_raw_hid_rx(data, length);
}
#endif
```

## LED Index Mapping

Indices are **not** sequential left-to-right. Odd rows are reversed.

```
Row 0 (Esc..Del):     0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
Row 1 (`..Bksp):     30 29 28 27 26 25 24 23 22 21 20 19 18 17 16       <- reversed
Row 2 (Tab..PgUp):   31 32 33 34 35 36 37 38 39 40 41 42 43 44 45
Row 3 (Caps..PgDn):  59 58 57 56 55 54 53 52 51 50 49 48 47 46          <- reversed
Row 4 (Shft..Up):    60 61 62 63 64 65 66 67 68 69 70 71 72 73
Row 5 (Ctrl..Right): 83 82 81 80 79 78 77 76 75 74                      <- reversed
```

Source: `vKeys` array in the SignalRGB JS plugin (`NuPhy_Air75v2_QMK_ANSI_Keyboard.js`).

## Building and Flashing

### Prerequisites

```bash
brew install qmk/qmk/qmk
qmk setup  # installs ARM toolchain
```

### Build

```bash
qmk compile -kb nuphy/air75v2/ansi -km via
# or: make nuphy/air75v2/ansi:via
```

### Flash

1. Enter DFU mode: **hold Esc while plugging in USB**
2. Flash:
   ```bash
   qmk flash -kb nuphy/air75v2/ansi -km via
   # or directly:
   dfu-util -a 0 -d 0x19F5:0x3246 -s 0x08000000:leave -D firmware.bin
   ```

### Recovery

DFU mode (Esc + plug) always works, even with bad firmware.
The bootloader lives in a protected ROM region and cannot be overwritten.

## Performance Considerations

The ryodeushii fork found that updating too many LEDs simultaneously impacts
key scanning latency. Their fix limits updates to ~4 LEDs per scan cycle
at 26ms intervals. For music reactivity, we may need to:

- Batch LED updates across multiple scan cycles
- Accept ~100-200ms full-frame latency (10 packets * ~10ms each)
- Or reduce visual resolution (update zones instead of per-key)

## VIA Conflict

Only one host application can use the Raw HID interface at a time.
Our music visualizer and VIA cannot run simultaneously.
VIA key remapping still works when stored in EEPROM -- the conflict
is only for real-time communication.
