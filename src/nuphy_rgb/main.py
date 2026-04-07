"""Main loop: audio capture -> visualization -> HID output."""

import argparse
import atexit
import os
import select
import signal
import sys
import termios
import time
import tty

import hid
import sounddevice as sd

from nuphy_rgb.audio import AudioCapture
from nuphy_rgb.hid_utils import find_raw_hid_path, send_frame, streaming_mode
from nuphy_rgb.probe import probe
from nuphy_rgb.visualizer import ColorWash, Visualizer

# Terminal state for raw mode keypress polling
_original_termios = None


def _save_terminal() -> None:
    global _original_termios
    try:
        _original_termios = termios.tcgetattr(sys.stdin)
    except termios.error:
        _original_termios = None


def _restore_terminal() -> None:
    if _original_termios is not None:
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _original_termios)
        except termios.error:
            pass


def _enter_raw_mode() -> None:
    _save_terminal()
    atexit.register(_restore_terminal)
    # In raw mode, Ctrl+C sends '\x03' instead of SIGINT.
    # We handle it in the main loop via poll_keypress().
    # SIGTERM still needs a handler to ensure cleanup.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    tty.setraw(sys.stdin.fileno())


def poll_keypress() -> str | None:
    """Non-blocking read of a single character from stdin (raw mode)."""
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1)
    return None


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
        visualizers: list[Visualizer] = [ColorWash(num_leds=led_count)]
        viz_index = 0

        # Set up audio capture
        audio = AudioCapture(device_index=audio_device)

        # Enter raw mode for keypress detection
        if not debug:
            _enter_raw_mode()

        frame_period = 1.0 / fps
        nl = "\r\n" if not debug else "\n"
        print(f"{nl}Running: {visualizers[viz_index].name} @ {fps}fps")
        if debug:
            print("  Debug mode: Ctrl+C to quit")
        else:
            print(f"{nl}  'n' = next effect | 'q' = quit{nl}")

        with streaming_mode(device):
            audio.start()
            try:
                last_colors = [(0, 0, 0)] * led_count
                frame_count = 0
                while True:
                    t0 = time.monotonic()

                    # Process audio
                    frame = audio.process_latest()
                    if frame is not None:
                        last_colors = visualizers[viz_index].render(frame)

                    # Send to keyboard
                    send_frame(device, last_colors)

                    if debug and frame_count % 30 == 0 and frame is not None:
                        print(f"  RGB={last_colors[0]} rms={frame.rms:.3f} bass={frame.bass:.3f} freq={frame.dominant_freq:.0f}Hz beat={frame.is_beat}")

                    # Check for keypress (skip in debug mode)
                    if not debug:
                        key = poll_keypress()
                        if key == "q" or key == "\x03":  # q or Ctrl+C
                            break
                        elif key == "n":
                            viz_index = (viz_index + 1) % len(visualizers)
                            print(f"\r  Effect: {visualizers[viz_index].name}    \r")

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
    finally:
        device.close()
        _restore_terminal()
        print("\r\nDone.")


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
        help="Debug mode: no raw terminal, prints frame data, Ctrl+C to quit",
    )
    args = parser.parse_args()

    if args.list_devices:
        list_audio_devices()
        return

    run(audio_device=args.audio_device, fps=args.fps, debug=args.debug)


if __name__ == "__main__":
    main()
