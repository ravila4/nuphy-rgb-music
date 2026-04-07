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

## Dependencies

```bash
# Firmware build
brew install qmk/qmk/qmk && qmk setup

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
