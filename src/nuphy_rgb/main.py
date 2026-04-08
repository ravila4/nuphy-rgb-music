"""Main loop: audio capture -> visualization -> HID output."""

import argparse
import sys
import threading
import time
from contextlib import ExitStack
from typing import Sequence

import hid
import sounddevice as sd
from pynput import keyboard

from nuphy_rgb.audio import AudioCapture
from nuphy_rgb.effects import ALL_EFFECTS
from nuphy_rgb.hid_utils import (
    KeyboardInfo,
    find_keyboards,
    select_keyboards,
    send_frame,
    streaming_mode,
)
from nuphy_rgb.probe import probe
from nuphy_rgb.visualizer import Visualizer


class _CyclicIndex:
    """Thread-safe cyclic index with an optional named-item registry.

    Tracks a current position within a fixed-size range [0, count) and
    exposes next/prev/set navigation. A changed flag is set on each mutation
    and consumed by poll_changed().

    Args:
        count: Number of positions in the cycle.
        names: Optional list of names for set_by_name() lookups. Must have
            exactly ``count`` entries if provided.
    """

    def __init__(self, count: int, names: Sequence[str] | None = None) -> None:
        if count <= 0:
            raise ValueError(f"count must be positive, got {count}")
        self._lock = threading.Lock()
        self._count = count
        self._index = 0
        self._changed = False
        self._names: list[str] | None = list(names) if names is not None else None

    @property
    def index(self) -> int:
        """Current index (read-only snapshot)."""
        with self._lock:
            return self._index

    def next(self) -> None:
        """Advance to the next position, wrapping around."""
        with self._lock:
            self._index = (self._index + 1) % self._count
            self._changed = True

    def prev(self) -> None:
        """Move to the previous position, wrapping around."""
        with self._lock:
            self._index = (self._index - 1) % self._count
            self._changed = True

    def set(self, index: int) -> None:
        """Jump directly to a position.

        Args:
            index: Target index in [0, count).

        Raises:
            ValueError: If index is out of range.
        """
        if index < 0 or index >= self._count:
            raise ValueError(f"index {index} out of range [0, {self._count})")
        with self._lock:
            self._index = index
            self._changed = True

    def set_by_name(self, name: str) -> bool:
        """Jump to the position whose name matches (case-insensitive).

        Args:
            name: Name to search for.

        Returns:
            True if found and index was updated; False if not found.

        Raises:
            ValueError: If this instance was created without names.
        """
        if self._names is None:
            raise ValueError("_CyclicIndex was created without names; cannot use set_by_name()")
        needle = name.lower()
        for i, n in enumerate(self._names):
            if n.lower() == needle:
                with self._lock:
                    self._index = i
                    self._changed = True
                return True
        return False

    def poll_changed(self) -> int | None:
        """Return current index if changed since last poll, else None.

        Resets the changed flag.
        """
        with self._lock:
            if self._changed:
                self._changed = False
                return self._index
            return None


class _HotkeyState:
    """Thread-safe state controlled by global hotkeys.

    Args:
        num_effects: Number of keyboard visualizer effects.
        effect_names: Names of the keyboard effects for set_by_name() support.
    """

    def __init__(self, num_effects: int, effect_names: Sequence[str] | None = None) -> None:
        self._lock = threading.Lock()
        self.key = _CyclicIndex(num_effects, names=effect_names)
        self.quit = False

    def next_effect(self) -> None:
        """Advance to the next keyboard effect."""
        self.key.next()

    def prev_effect(self) -> None:
        """Move to the previous keyboard effect."""
        self.key.prev()

    def request_quit(self) -> None:
        """Signal the main loop to exit."""
        with self._lock:
            self.quit = True



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


def _open_keyboards(
    infos: list[KeyboardInfo],
) -> list[tuple[KeyboardInfo, hid.device, int]]:
    """Open HID devices and probe each. Returns (info, device, led_count) triples."""
    opened: list[tuple[KeyboardInfo, hid.device, int]] = []
    for info in infos:
        device = hid.device()
        device.open_path(info.path)
        led_count = probe(device)
        if led_count is None:
            print(f"  Keyboard {info.index} ({info.serial[-8:]}): handshake failed, skipping")
            device.close()
            continue
        print(f"  Keyboard {info.index}: {info.serial[-8:]} — {led_count} LEDs")
        opened.append((info, device, led_count))
    return opened


def list_keyboards() -> None:
    """Print connected NuPhy keyboards and exit."""
    keyboards = find_keyboards()
    if not keyboards:
        print("No NuPhy keyboards found.")
        return
    print("Connected NuPhy keyboards:")
    for kb in keyboards:
        print(f"  {kb.index}: serial={kb.serial}  path={kb.path}")


def run(
    audio_device: int | None = None,
    fps: int = 30,
    debug: bool = False,
    device_filter: str | None = None,
    effect: str | None = None,
) -> None:
    # Find audio device
    if audio_device is None:
        audio_device = find_blackhole_device()
        if audio_device is None:
            print("BlackHole not found. Install with: brew install blackhole-2ch")
            print("Use --list-audio to see available inputs, --audio-device to specify.")
            sys.exit(1)
    print(f"Audio device: {sd.query_devices(audio_device)['name']} (index {audio_device})")

    # Find keyboards
    print("Looking for NuPhy keyboards...")
    all_keyboards = find_keyboards()
    if not all_keyboards:
        print("No keyboards found. Are they plugged in via USB?")
        sys.exit(1)

    try:
        selected = select_keyboards(all_keyboards, device_filter)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    boards = _open_keyboards(selected)
    if not boards:
        print("No keyboards passed handshake. Is the custom firmware flashed?")
        sys.exit(1)

    devices = [(dev, leds) for _, dev, leds in boards]
    led_counts = {leds for _, leds in devices}
    if len(led_counts) > 1:
        print(f"Error: mixed LED counts across keyboards: {led_counts}")
        for dev, _ in devices:
            dev.close()
        sys.exit(1)
    led_count = led_counts.pop()

    try:
        # Set up visualizers
        visualizers: list[Visualizer] = [cls() for cls in ALL_EFFECTS]

        # Set up hotkey listener
        effect_names = [v.name for v in visualizers]
        state = _HotkeyState(len(visualizers), effect_names=effect_names)

        # Apply --effect if specified
        if effect is not None:
            if not state.key.set_by_name(effect):
                known = ", ".join(effect_names)
                print(f"Error: unknown effect '{effect}'. Known effects: {known}")
                sys.exit(1)

        listener = _start_hotkey_listener(state)

        # Set up audio capture
        audio = AudioCapture(device_index=audio_device)

        frame_period = 1.0 / fps
        kb_label = (
            f"{len(devices)} keyboard{'s' if len(devices) > 1 else ''}"
        )
        print(f"\nRunning: {visualizers[state.key.index].name} @ {fps}fps on {kb_label}")
        print("  Ctrl+Shift+Right/Left = cycle effects | Ctrl+Shift+Q = quit")
        if debug:
            print("  Debug mode: Ctrl+C also quits\n")

        with ExitStack() as stack:
            for dev, _ in devices:
                stack.enter_context(streaming_mode(dev))

            audio.start()
            try:
                last_colors = [(0, 0, 0)] * led_count
                frame_count = 0
                while not state.quit:
                    t0 = time.monotonic()

                    # Check for effect switch
                    new_idx = state.key.poll_changed()
                    if new_idx is not None:
                        print(f"  Effect: {visualizers[new_idx].name}")

                    # Process audio
                    frame = audio.process_latest()
                    if frame is not None:
                        last_colors = visualizers[state.key.index].render(frame)

                    # Send to all keyboards
                    for dev, _ in devices:
                        send_frame(dev, last_colors)

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
        for dev, _ in devices:
            dev.close()
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
        "--list-audio", action="store_true",
        help="List audio input devices and exit",
    )
    parser.add_argument(
        "--list-keyboards", action="store_true",
        help="List connected NuPhy keyboards and exit",
    )
    parser.add_argument(
        "--keyboard", type=str, default=None,
        help="Keyboard to drive: index (0, 1) or serial substring. Default: all connected.",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Debug mode: prints frame data, Ctrl+C to quit",
    )
    parser.add_argument(
        "--effect", type=str, default=None,
        help="Start on a specific effect by name (case-insensitive, e.g. colorwash).",
    )
    parser.add_argument(
        "--list-effects", action="store_true",
        help="List available effects and exit.",
    )
    args = parser.parse_args()

    if args.list_effects:
        for cls in ALL_EFFECTS:
            print(cls().name)
        return

    if args.list_audio:
        list_audio_devices()
        return

    if args.list_keyboards:
        list_keyboards()
        return

    run(
        audio_device=args.audio_device,
        fps=args.fps,
        debug=args.debug,
        device_filter=args.keyboard,
        effect=args.effect,
    )


if __name__ == "__main__":
    main()
