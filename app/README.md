# NuPhy RGB Menu Bar App

Native macOS menu bar app for controlling NuPhy music-reactive RGB.
Bundles the Python daemon via PyInstaller and manages its lifecycle
automatically.

## Requirements

- macOS 14.2+ (Apple Silicon)
- Xcode command line tools (`xcode-select --install`)
- [uv](https://docs.astral.sh/uv/) (for building the Python daemon)

## Build

```bash
cd app
bash build.sh
```

This builds the PyInstaller daemon binary, compiles the Swift app, and
assembles the `.app` bundle at `.build/debug/NuPhyRGBMenu.app`.

## Install

Drag `NuPhyRGBMenu.app` to `/Applications` (or run it from the build
directory).

## Permissions

On first launch, the app prompts for two macOS permissions:

1. **Screen & System Audio Recording** -- captures system audio for
   music-reactive effects (CoreAudio Process Tap)
2. **Input Monitoring** -- sends RGB data to the keyboard over USB HID

Grant both in **System Settings > Privacy & Security**. Restart the app
after granting.

> The app is ad-hoc signed (no Apple Developer certificate).
> Rebuilding changes the binary hash, which invalidates macOS permission
> grants. After rebuilding, remove and re-add the app in both permission
> panes.

## Usage

Click the waveform icon in the menu bar to:

- Switch effects and sidelight modes
- Pause/resume rendering
- Quit (cleanly restores firmware RGB)

The daemon starts automatically with the app.
