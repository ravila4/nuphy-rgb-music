"""Main loop: audio capture -> visualization -> HID output."""

import argparse
import sys
import threading
import time

import hid
import sounddevice as sd
from pynput import keyboard

from nuphy_rgb.audio import AudioCapture
from nuphy_rgb.effects import ALL_EFFECTS
from nuphy_rgb.hid_utils import find_raw_hid_path, send_frame, streaming_mode
from nuphy_rgb.probe import probe
from nuphy_rgb.visualizer import Visualizer


class _HotkeyState:
    """Thread-safe state controlled by global hotkeys."""

    def __init__(self, num_effects: int):
        self._lock = threading.Lock()
        self._num_effects = num_effects
        self.viz_index = 0
        self.quit = False
        self.changed = False  # flag: effect was just switched

    def next_effect(self) -> None:
        with self._lock:
            self.viz_index = (self.viz_index + 1) % self._num_effects
            self.changed = True

    def prev_effect(self) -> None:
        with self._lock:
            self.viz_index = (self.viz_index - 1) % self._num_effects
            self.changed = True

    def request_quit(self) -> None:
        with self._lock:
            self.quit = True

    def poll_changed(self) -> int | None:
        """Return new index if changed, else None. Resets the flag."""
        with self._lock:
            if self.changed:
                self.changed = False
                return self.viz_index
            return None


def _start_hotkey_listener(state: _HotkeyState) -> keyboard.GlobalHotKeys:
    """Start a pynput global hotkey listener (runs in a daemon thread)."""
    hotkeys = keyboard.GlobalHotKeys({
        "<ctrl>+<shift>+<right>": state.next_effect,
        "<ctrl>+<shift>+<left>": state.prev_effect,
        "<ctrl>+<shift>+q": state.request_quit,
    })
    hotkeys.daemon = True
    hotkeys.start()
    return hotkeys


def find_blackhole_device() -> int | None:
    """Find the BlackHole audio device index."""
    for i, d in enumerate(sd.query_devices()):
        if "BlackHole" in d["name"] and d["max_input_channels"] > 0:
            return i
    return None


def list_audio_devices() -> None:
    """Print available audio input devices."""
    print("Audio input devices:")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            marker = " <-- BlackHole" if "BlackHole" in d["name"] else ""
            print(f"  {i}: {d['name']} ({d['max_input_channels']}ch){marker}")


def run(audio_device: int | None = None, fps: int = 30, debug: bool = False) -> None:
    # Find audio device
    if audio_device is None:
        audio_device = find_blackhole_device()
        if audio_device is None:
            print("BlackHole not found. Install with: brew install blackhole-2ch")
            print("Use --list-devices to see available inputs, --audio-device to specify.")
            sys.exit(1)
    print(f"Audio device: {sd.query_devices(audio_device)['name']} (index {audio_device})")

    # Find keyboard
    print("Looking for NuPhy keyboard...")
    path = find_raw_hid_path()
    if path is None:
        print("Keyboard not found. Is it plugged in via USB?")
        sys.exit(1)

    device = hid.device()
    device.open_path(path)
    print(f"Found keyboard: {path}")

    try:
        led_count = probe(device)
        if led_count is None:
            print("Firmware handshake failed. Is the custom firmware flashed?")
            sys.exit(1)

        # Set up visualizers
        visualizers: list[Visualizer] = [cls() for cls in ALL_EFFECTS]

        # Set up hotkey listener
        state = _HotkeyState(len(visualizers))
        listener = _start_hotkey_listener(state)

        # Set up audio capture
        audio = AudioCapture(device_index=audio_device)

        frame_period = 1.0 / fps
        print(f"\nRunning: {visualizers[state.viz_index].name} @ {fps}fps")
        print(f"  Ctrl+Shift+Right/Left = cycle effects | Ctrl+Shift+Q = quit")
        if debug:
            print("  Debug mode: Ctrl+C also quits\n")

        with streaming_mode(device):
            audio.start()
            try:
                last_colors = [(0, 0, 0)] * led_count
                frame_count = 0
                while not state.quit:
                    t0 = time.monotonic()

                    # Check for effect switch
                    new_idx = state.poll_changed()
                    if new_idx is not None:
                        print(f"  Effect: {visualizers[new_idx].name}")

                    # Process audio
                    frame = audio.process_latest()
                    if frame is not None:
                        last_colors = visualizers[state.viz_index].render(frame)

                    # Send to keyboard
                    send_frame(device, last_colors)

                    if debug and frame_count % 30 == 0 and frame is not None:
                        print(f"  RGB={last_colors[0]} raw_rms={frame.raw_rms:.3f} rms={frame.rms:.3f} bass={frame.bass:.3f} freq={frame.dominant_freq:.0f}Hz beat={frame.is_beat}")

                    frame_count += 1

                    # Frame timing
                    elapsed = time.monotonic() - t0
                    remaining = frame_period - elapsed
                    if remaining > 0:
                        time.sleep(remaining)
            except KeyboardInterrupt:
                pass
            finally:
                audio.stop()
                listener.stop()
    finally:
        device.close()
        print("\nDone.")


def main():
    parser = argparse.ArgumentParser(
        description="NuPhy Air75 V2 music-reactive RGB"
    )
    parser.add_argument(
        "--audio-device", type=int, default=None,
        help="Audio input device index (default: auto-detect BlackHole)",
    )
    parser.add_argument(
        "--fps", type=int, default=30,
        help="Target frames per second (default: 30)",
    )
    parser.add_argument(
        "--list-devices", action="store_true",
        help="List audio input devices and exit",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Debug mode: prints frame data, Ctrl+C to quit",
    )
    args = parser.parse_args()

    if args.list_devices:
        list_audio_devices()
        return

    run(audio_device=args.audio_device, fps=args.fps, debug=args.debug)


if __name__ == "__main__":
    main()
