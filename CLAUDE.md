# NuPhy Air75 V2 Music-Reactive RGB

## Project Goal

Programmatic per-key RGB control of a NuPhy Air75 V2 keyboard from macOS (M1),
with real-time music-reactive visualizations.

## Hardware

- NuPhy Air75 **V2** (STM32F072, QMK firmware)
- 84 per-key RGB LEDs + 2 side light bars (separate WS2812 strips)
- USB VID: `0x19F5`, PID: `0x3246`
- Raw HID: Usage Page `0xFF60`, Usage ID `0x61`

## Architecture

Two workstreams:

### Phase 1: Host-to-Keyboard RGB Control
- **Firmware**: Fork `ryodeushii/qmk-firmware` (branch: `nuphy-keyboards`), add
  RGB streaming handler via `via_command_kb()` hook. Adapt SignalRGB protocol
  from `zhouzengming/Nuphy-qmk-SignalRGB`.
- **Host**: Python script using `hid` (pyhidapi) to send per-key RGB over USB Raw HID.
- **Validates**: end-to-end pipeline with static colors.

### Phase 2: Music-Reactive Visualizations
- Audio capture via BlackHole loopback + `sounddevice`
- Real-time FFT / beat detection with `numpy`
- Map frequency bands to per-key colors

## Key Technical Details

- Raw HID packet: `[0x24, start_idx, num_leds, R,G,B, ...]` -- max 9 LEDs/packet
- 10 packets needed for full 84-LED frame
- LED indices alternate direction per row (see `research/firmware.md`)
- VIA is enabled in the firmware -- must hook `via_command_kb()`, not `raw_hid_receive()`
- Update rate constraint: ~4 LEDs per scan cycle at 26ms intervals (perf fix in ryodeushii fork)
- DFU mode: hold Esc while plugging in USB (always recoverable)

## Local Repos

| Repo | Path | Branch | Purpose |
|------|------|--------|---------|
| This project | `~/Projects/nuphy-rgb-music` | `main` | Host code, research, docs |
| QMK firmware fork | `~/Projects/qmk-firmware` | `nuphy-keyboards` | Firmware we build & flash |

## Recovery

Fallback firmware binaries in `firmware/fallback/`:
- `current_dump.bin` -- dumped from keyboard 2026-04-07
- `nuphy_stock_v2.0.3.bin` -- NuPhy official
- `ryodeushii_via_ryo-1.1.4.bin` -- community QMK+VIA

Flash via DFU: hold Esc + plug in USB, then `dfu-util -a 0 -d 0x19F5:0x3246 -s 0x08000000:leave -D <file.bin>`

## Dependencies

```bash
# Firmware build
brew install qmk/qmk/qmk dfu-util && qmk setup

# Host
brew install hidapi blackhole-2ch
pip install hid sounddevice numpy
```

## Research

Detailed notes in `research/`:
- `architecture.md` -- system diagram and phase plan
- `firmware.md` -- QMK forks, protocol, LED map, build/flash
- `host-software.md` -- Python libs, audio capture, beat detection, viz ideas

## Reference Repos

- `ryodeushii/qmk-firmware` -- most maintained NuPhy QMK fork (base for our firmware)
- `zhouzengming/Nuphy-qmk-SignalRGB` -- SignalRGB host RGB control (protocol reference)
- `Drugantibus/qmk-hid-rgb` -- Python Raw HID RGB control for QMK
- `zhogov/nuphy-state-of-qmk-firmware` -- tracks all NuPhy QMK fork status
