# NuPhy Music-Reactive RGB

Real-time music-reactive per-key RGB control for NuPhy keyboards. Audio in,
FFT, beat detection, and visualizer effects rendered at 30fps over USB Raw HID.

Tested on **NuPhy Air75 V2**. Support for other Air models incoming.

## Requirements

- **macOS 14.2+** (tested on Apple Silicon), or **Linux** (X11/Wayland, experimental)
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
   # macOS
   brew install dfu-util
   # Linux (Debian/Ubuntu)
   sudo apt install dfu-util
   # Linux (Fedora)
   sudo dnf install dfu-util

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
brew install qmk/qmk/qmk   # macOS
python3 -m pip install qmk  # Linux
qmk setup -H ~/Projects/qmk-firmware
cd ~/Projects/qmk-firmware
qmk compile -kb nuphy/air75_v2/ansi -km via
```

The built binary lands in `.build/nuphy_air75v2_ansi_via.bin`.

## Installation

### macOS

```bash
brew install hidapi
```

### Linux (Debian/Ubuntu)

```bash
sudo apt install libhidapi-hidraw0 python3-dev
sudo cp udev/99-nuphy.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Linux (Fedora)

```bash
sudo dnf install hidapi python3-devel
sudo cp udev/99-nuphy.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Clone and install

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

#### macOS

System audio capture uses the CoreAudio Process Tap API (macOS 14.2+).
The app that runs `nuphy-rgb` needs **Screen & System Audio Recording**
permission: your terminal (Ghostty, iTerm2, Terminal.app, etc.) when
running from the command line, or the packaged app itself.

Grant it in **System Settings \> Privacy & Security \> Screen & System
Audio Recording**. You may need to restart the app after granting.

No extra audio software needed. Volume keys and audio routing work normally.

#### Linux

PipeWire and PulseAudio automatically expose monitor sources — no extra
software needed. Run `nuphy-rgb --list-audio` to find yours (look for
"Monitor of ...").

If no monitor source appears, ensure PipeWire or PulseAudio ALSA integration
is installed (`pipewire-pulse`, `pipewire-alsa`, or equivalent for your distro).

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

### IPC control

The daemon exposes a JSON-RPC 2.0 control socket for runtime control:

```
Linux:  $XDG_RUNTIME_DIR/nuphy-rgb/control.sock
macOS:  $TMPDIR/nuphy-rgb/control.sock
```

Switch effects, query status, tune parameters, or quit from another terminal:

```bash
# Using nc (netcat)
echo '{"jsonrpc":"2.0","method":"get_status","id":1}' | nc -U $XDG_RUNTIME_DIR/nuphy-rgb/control.sock
echo '{"jsonrpc":"2.0","method":"next_effect","id":1}' | nc -U $XDG_RUNTIME_DIR/nuphy-rgb/control.sock
echo '{"jsonrpc":"2.0","method":"set_effect","params":{"name":"Mycelium"},"id":1}' | nc -U $XDG_RUNTIME_DIR/nuphy-rgb/control.sock
echo '{"jsonrpc":"2.0","method":"get_params","id":1}' | nc -U $XDG_RUNTIME_DIR/nuphy-rgb/control.sock
echo '{"jsonrpc":"2.0","method":"set_param","params":{"name":"decay_rate","value":0.97},"id":1}' | nc -U $XDG_RUNTIME_DIR/nuphy-rgb/control.sock
echo '{"jsonrpc":"2.0","method":"quit","id":1}' | nc -U $XDG_RUNTIME_DIR/nuphy-rgb/control.sock
```

| Method | Params | Description |
|--------|--------|-------------|
| `get_status` | — | Current effect, sidelight, running state |
| `list_effects` | — | All available effect and sidelight names |
| `set_effect` | `{"name": "..."}` | Switch keyboard effect |
| `set_sidelight` | `{"name": "..."}` | Switch sidelight effect |
| `next_effect` | — | Cycle to next keyboard effect |
| `prev_effect` | — | Cycle to previous keyboard effect |
| `next_sidelight` | — | Cycle to next sidelight effect |
| `prev_sidelight` | — | Cycle to previous sidelight effect |
| `get_params` | — | Tunable parameters for the active keyboard effect |
| `set_param` | `{"name": "...", "value": N}` | Set a parameter on the active keyboard effect |
| `get_side_params` | — | Tunable parameters for the active sidelight effect |
| `set_side_param` | `{"name": "...", "value": N}` | Set a parameter on the active sidelight effect |
| `quit` | — | Stop the daemon |

Effects can expose tunable parameters (decay rates, brightness, etc.) with
min/max ranges. Use `get_params` to discover what's available, then `set_param`
to tweak values live. Parameters reset to defaults on restart.

Connected clients also receive push notifications (`effect_changed`,
`sidelight_changed`) when the active effect is switched.

## Effects

| Effect | Description |
|--------|-------------|
| Aurora Borealis | Spectroscopic curtain shimmer driven by audio energy |
| Chromatic Keys | Each key glows its pitch class color from chroma analysis |
| Color Wash | Smooth full-keyboard color cycling driven by frequency bands |
| Event Horizon | Gravitational lensing effect around a central attractor |
| Interference Pond | Ripple interference patterns from beat-triggered wave sources |
| Mycelium | Organic growth network that branches on beats |
| Spectral Waterfall | Scrolling spectrogram — frequency on x-axis, time on y-axis |
| Standing Waves | Resonant wave patterns driven by bass and mid frequencies |
| Strange Attractor | Chaotic particle system mapped to the keyboard grid |
| Blackout | All LEDs off — useful for isolating sidelight effects |

## Sidelights

Host-controlled side LED bars (12 WS2812 LEDs, 6 per side). Enabled by
default with the VU Meter effect. Use `--no-sidelight` to let the firmware
handle them instead.

| Effect | Description |
|--------|-------------|
| VU Meter | Symmetric bass-driven bar graph — green, yellow, red |
| Chroma Bars | Each LED tracks a pitch class — left strip C-F, right strip F#-B |
| Chord Glow | Both strips glow the blended color of the current chord |

## Plugins

Drop a `.py` file into `~/.config/nuphy-rgb/effects/` (keyboard) or
`~/.config/nuphy-rgb/sidelights/` (side bars) and it's automatically
discovered on next launch.

### Creating a plugin

A plugin is a Python class with a `name` string and a `render(self, frame)`
method. Import everything you need from `nuphy_rgb.plugin_api`:

```python
from nuphy_rgb.plugin_api import AudioFrame, NUM_LEDS, grid_to_leds, freq_to_hue, VisualizerParam

class MyEffect:
    name = "My Effect"

    def __init__(self):
        # Optional: expose tunable parameters via IPC
        self.params = {
            "intensity": VisualizerParam(
                value=0.8, default=0.8, min=0.0, max=1.0,
                description="Effect intensity",
            ),
        }

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        hue = freq_to_hue(frame.dominant_freq)
        brightness = int(frame.rms * 255 * self.params["intensity"].get())
        # ... your logic here ...
        return [(brightness, 0, 0)] * NUM_LEDS
```

### Plugin directory layout

```
~/.config/nuphy-rgb/
  effects/
    my_effect.py          # single-file plugin
    spectral-pack/        # subdirectory packs work too
      aurora.py
      _helpers.py         # underscore-prefixed files are skipped
  sidelights/
    my_sidelight.py
```

### Notes

- Plugins that crash are skipped automatically -- the next effect takes over
- Plugin names that collide with built-in effects are ignored
- Use `--effects-dir` to override the config directory
- Use `--list-effects` / `--list-sidelights` to verify your plugin loads

## Reference Repos

- [ryodeushii/qmk-firmware](https://github.com/ryodeushii/qmk-firmware) — most maintained NuPhy QMK fork (base for our firmware)
- [zhouzengming/Nuphy-qmk-SignalRGB](https://github.com/zhouzengming/Nuphy-qmk-SignalRGB) — SignalRGB host RGB control (protocol reference)
- [Drugantibus/qmk-hid-rgb](https://github.com/Drugantibus/qmk-hid-rgb) — Python Raw HID RGB control for QMK
- [zhogov/nuphy-state-of-qmk-firmware](https://github.com/zhogov/nuphy-state-of-qmk-firmware) — tracks all NuPhy QMK fork status
