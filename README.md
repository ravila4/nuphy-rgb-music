# NuPhy Music-Reactive RGB

Real-time music-reactive per-key RGB control for NuPhy keyboards, driven from
macOS. Audio in, FFT, beat detection, and visualizer effects rendered at 30fps
over USB Raw HID.

Tested on **NuPhy Air75 V2**. Support for other Air models incoming.

## Requirements

- macOS (tested on Apple Silicon)
- [BlackHole 2ch](https://existential.audio/blackhole/) for audio loopback
- Python 3.11+
- Custom QMK firmware with RGB streaming handler (see below)

## Firmware

The keyboard needs custom QMK firmware that accepts RGB commands over Raw HID.
Pre-built binaries are in [`firmware/fallback/`](firmware/fallback/) — no
toolchain needed.

### Quick flash

1. Hold **Esc** and plug in the keyboard via USB (enters DFU mode)
2. Flash:

   ```bash
   brew install dfu-util  # if not installed
   dfu-util -a 0 -d 0x19F5:0x3246 -s 0x08000000:leave \
     -D firmware/fallback/qmk_rgb_streaming_a62d78d.bin
   ```

3. Keyboard reboots automatically

DFU mode is always recoverable — hold Esc + plug in to re-flash at any time.
Stock NuPhy firmware is also in the fallback directory if you want to revert.

### Building from source

The firmware lives in a [fork of ryodeushii/qmk-firmware](https://github.com/ravila4/qmk-firmware)
(branch: `nuphy-keyboards`):

```bash
brew install qmk/qmk/qmk
qmk setup -H ~/Projects/qmk-firmware
cd ~/Projects/qmk-firmware
qmk compile -kb nuphy/air75_v2/ansi -km via
```

The built binary lands in `.build/nuphy_air75v2_ansi_via.bin`.

## Installation

```bash
brew install hidapi blackhole-2ch
```

Clone and install:

```bash
git clone https://github.com/ravila4/nuphy-rgb-music.git
cd nuphy-rgb-music
pip install .
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

### Audio setup

BlackHole creates a virtual audio device. To capture system audio:

1. Open **Audio MIDI Setup** (built into macOS)
2. Create a **Multi-Output Device** combining your speakers + BlackHole 2ch
3. Set the Multi-Output Device as your system output

## Usage

```bash
nuphy-rgb                                    # auto-detects everything, VU Meter sidelights on
nuphy-rgb --debug                            # prints frame data
nuphy-rgb --no-sidelight                     # firmware handles sidelights
nuphy-rgb --effect blackout --sidelight "VU Meter"  # sidelights only
nuphy-rgb --effect "Spectral Waterfall"      # start on a specific effect
nuphy-rgb --list-effects                     # list keyboard effects
nuphy-rgb --list-sidelights                  # list sidelight effects
nuphy-rgb --audio-device 3 --fps 30
```

### Hotkeys

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+Right` | Next effect |
| `Ctrl+Shift+Left` | Previous effect |
| `Ctrl+Shift+Up` | Next sidelight |
| `Ctrl+Shift+Down` | Previous sidelight |
| `Ctrl+Shift+Q` | Quit |

## Effects

| Effect | Description |
|--------|-------------|
| Color Wash | Smooth full-keyboard color cycling driven by frequency bands |
| Interference Pond | Ripple interference patterns from beat-triggered wave sources |
| Mycelium | Organic growth network that branches on beats |
| Event Horizon | Gravitational lensing effect around a central attractor |
| Strange Attractor | Chaotic particle system mapped to the keyboard grid |
| Spectral Waterfall | Scrolling spectrogram — frequency on x-axis, time on y-axis |
| Blackout | All LEDs off — useful for isolating sidelight effects |

## Sidelights

Host-controlled side LED bars (12 WS2812 LEDs, 6 per side). Enabled by
default with the VU Meter effect. Use `--no-sidelight` to let the firmware
handle them instead.

| Effect | Description |
|--------|-------------|
| VU Meter | Symmetric bass-driven bar graph — green, yellow, red |

More effects in development.

## Reference Repos

- [ryodeushii/qmk-firmware](https://github.com/ryodeushii/qmk-firmware) — most maintained NuPhy QMK fork (base for our firmware)
- [zhouzengming/Nuphy-qmk-SignalRGB](https://github.com/zhouzengming/Nuphy-qmk-SignalRGB) — SignalRGB host RGB control (protocol reference)
- [Drugantibus/qmk-hid-rgb](https://github.com/Drugantibus/qmk-hid-rgb) — Python Raw HID RGB control for QMK
- [zhogov/nuphy-state-of-qmk-firmware](https://github.com/zhogov/nuphy-state-of-qmk-firmware) — tracks all NuPhy QMK fork status
