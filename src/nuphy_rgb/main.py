"""Main loop: audio capture -> visualization -> HID output."""

import argparse
import logging
import sys
import time
from contextlib import ExitStack
from importlib.metadata import version as pkg_version
from pathlib import Path

import hid
import sounddevice as sd

from nuphy_rgb.audio import AudioCapture
from nuphy_rgb.audio_discovery import (
    LoopbackResult,
    find_loopback_device,
    list_audio_devices,
    move_source_output_to_monitor,
)
from nuphy_rgb.effects import ALL_EFFECTS
from nuphy_rgb.ipc import IPCServer
from nuphy_rgb.hid_utils import (
    SIDE_LED_COUNT,
    KeyboardInfo,
    find_keyboards,
    select_keyboards,
    send_frame,
    send_side_frame,
    side_streaming_mode,
    streaming_mode,
)
from nuphy_rgb.plugins import discover_effects, discover_sidelights
from nuphy_rgb.probe import probe
from nuphy_rgb.sidelights import ALL_SIDELIGHTS
from nuphy_rgb.state import DaemonState
from nuphy_rgb.visualizer import Visualizer

log = logging.getLogger(__name__)


def _open_keyboards(
    infos: list[KeyboardInfo],
) -> tuple[list[tuple[KeyboardInfo, hid.device, int]], bool]:
    """Open HID devices and probe each.

    Returns ``(opened, permission_denied)`` where *opened* is a list of
    ``(info, device, led_count)`` triples and *permission_denied* is True
    if any device failed to open due to OS permissions.
    """
    opened: list[tuple[KeyboardInfo, hid.device, int]] = []
    permission_denied = False
    for info in infos:
        device = hid.device()
        try:
            device.open_path(info.path)
        except OSError:
            permission_denied = True
            continue
        led_count = probe(device)
        if led_count is None:
            device.close()
            continue
        print(f"  Keyboard {info.index}: {info.serial[-8:]} — {led_count} LEDs")
        opened.append((info, device, led_count))
    return opened, permission_denied


def list_keyboards() -> None:
    """Print connected NuPhy keyboards and exit."""
    keyboards = find_keyboards()
    if not keyboards:
        print("No NuPhy keyboards found.")
        return
    print("Connected NuPhy keyboards:")
    for kb in keyboards:
        print(f"  {kb.index}: serial={kb.serial}  path={kb.path}")


def _dedupe_plugins(plugin_classes: list[type], builtin_names: set[str]) -> list[type]:
    """Filter out plugin classes whose name collides with a built-in."""
    kept: list[type] = []
    for cls in plugin_classes:
        if cls.name in builtin_names:
            log.warning("Plugin '%s' shadows a built-in effect, skipping", cls.name)
        else:
            kept.append(cls)
    return kept


def run(
    audio_device: int | None = None,
    fps: int = 30,
    debug: bool = False,
    device_filter: str | None = None,
    effect: str | None = None,
    sidelight: str | None = None,
    config_dir: Path | None = None,
) -> None:
    if debug:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")

    # Find audio device
    monitor_name: str | None = None
    tap = None
    if audio_device is None:
        result = find_loopback_device()
        if result is None:
            if sys.platform == "darwin":
                print("No audio source found (macOS 14.2+ required).")
                print("  Grant 'Screen & System Audio Recording' in System Settings.")
            else:
                print("No monitor source found. Ensure PulseAudio/PipeWire is running.")
            print(
                "Use --list-audio to see available inputs, --audio-device to specify."
            )
            sys.exit(1)
        audio_device = result.device_index
        monitor_name = result.monitor_name
        tap = result.tap
    if tap is not None:
        print("Audio: CoreAudio Process Tap (system audio)")
    else:
        print(
            f"Audio device: {sd.query_devices(audio_device)['name']} (index {audio_device})"
        )
    if monitor_name:
        print(f"  Monitor source: {monitor_name} (will route after stream opens)")

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

    boards, permission_denied = _open_keyboards(selected)
    if not boards:
        if permission_denied:
            if sys.platform == "darwin":
                print("Permission denied — check Input Monitoring in System Settings")
            else:
                print("Permission denied — install udev rules:")
                print("  sudo cp udev/99-nuphy.rules /etc/udev/rules.d/")
                print("  sudo udevadm control --reload-rules && sudo udevadm trigger")
                print("Then unplug and replug the keyboard.")
        else:
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
        # Set up visualizers: built-in + plugins
        builtin_names = {cls.name for cls in ALL_EFFECTS}
        plugin_effects = _dedupe_plugins(discover_effects(config_dir), builtin_names)
        all_effect_classes = list(ALL_EFFECTS) + plugin_effects

        visualizers: list[Visualizer] = [cls() for cls in all_effect_classes]
        effect_names = [v.name for v in visualizers]

        # Set up sidelight visualizers (opt-in): built-in + plugins
        if sidelight is not None:
            builtin_side_names = {cls.name for cls in ALL_SIDELIGHTS}
            plugin_sidelights = _dedupe_plugins(
                discover_sidelights(config_dir), builtin_side_names
            )
            all_sidelight_classes = list(ALL_SIDELIGHTS) + plugin_sidelights

            side_visualizers = [cls() for cls in all_sidelight_classes]
            sidelight_names = [v.name for v in side_visualizers]
        else:
            side_visualizers = []
            sidelight_names = []

        state = DaemonState(
            len(visualizers),
            effect_names=effect_names,
            num_sidelights=len(side_visualizers),
            sidelight_names=sidelight_names,
            visualizers=visualizers,
            side_visualizers=side_visualizers,
        )

        # Apply --effect if specified
        if effect is not None:
            if not state.key.set_by_name(effect):
                known = ", ".join(effect_names)
                print(f"Error: unknown effect '{effect}'. Known effects: {known}")
                sys.exit(1)

        # Apply --sidelight if specified
        if sidelight is not None and state.side is not None:
            if not state.side.set_by_name(sidelight):
                known = ", ".join(sidelight_names)
                print(f"Error: unknown sidelight '{sidelight}'. Known: {known}")
                sys.exit(1)

        # Start IPC server
        ipc = IPCServer(state)
        sock_path = ipc.start()
        print(f"  IPC: {sock_path}")

        # Set up audio capture
        frame_period = 1.0 / fps
        kb_label = f"{len(devices)} keyboard{'s' if len(devices) > 1 else ''}"
        print(
            f"\nRunning: {visualizers[state.key.index].name} @ {fps}fps on {kb_label}"
        )
        if state.side is not None:
            print(f"  Sidelight: {side_visualizers[state.side.index].name}")
        if debug:
            print("  Debug mode: Ctrl+C also quits\n")

        with ExitStack() as stack:
            for dev, _ in devices:
                stack.enter_context(streaming_mode(dev))
            if state.side is not None:
                for dev, _ in devices:
                    stack.enter_context(side_streaming_mode(dev))

            # Start CoreAudio tap or sounddevice stream
            if tap is not None:
                try:
                    stack.enter_context(tap)
                    audio = AudioCapture(external_queue=tap.queue)
                except PermissionError:
                    log.warning(
                        "CoreAudio tap: permission denied. "
                        "Grant 'Screen & System Audio Recording' in System Settings."
                    )
                    tap = None
                except Exception:
                    log.warning("CoreAudio tap failed", exc_info=True)
                    tap = None

            if tap is None:
                audio = AudioCapture(device_index=audio_device)

            audio.start()
            if monitor_name:
                time.sleep(0.1)  # let PipeWire register the source-output
                move_source_output_to_monitor(monitor_name)
            try:
                last_colors = [(0, 0, 0)] * led_count
                last_side_colors = [(0, 0, 0)] * SIDE_LED_COUNT
                frame_count = 0
                while not state.quit_event.is_set():
                    t0 = time.monotonic()

                    # Check for effect switch (from IPC)
                    new_idx = state.key.poll_changed()
                    if new_idx is not None:
                        print(f"  Effect: {visualizers[new_idx].name}")
                        ipc.notify_effect_changed(visualizers[new_idx].name)

                    # Check for sidelight switch (from IPC)
                    if state.side is not None:
                        new_side_idx = state.side.poll_changed()
                        if new_side_idx is not None:
                            print(f"  Sidelight: {side_visualizers[new_side_idx].name}")
                            ipc.notify_sidelight_changed(side_visualizers[new_side_idx].name)

                    # Process audio
                    frame = audio.process_latest()
                    if frame is not None:
                        try:
                            last_colors = visualizers[state.key.index].render(frame)
                        except Exception:
                            name = visualizers[state.key.index].name
                            log.warning(
                                "Effect '%s' crashed, advancing", name, exc_info=True
                            )
                            state.key.next()
                        if state.side is not None:
                            try:
                                last_side_colors = side_visualizers[
                                    state.side.index
                                ].render(frame)
                            except Exception:
                                name = side_visualizers[state.side.index].name
                                log.warning(
                                    "Sidelight '%s' crashed, advancing",
                                    name,
                                    exc_info=True,
                                )
                                state.side.next()

                    # Send to all keyboards
                    for dev, _ in devices:
                        send_frame(dev, last_colors)
                        if state.side is not None:
                            send_side_frame(dev, last_side_colors)

                    if debug and frame_count % 30 == 0 and frame is not None:
                        print(
                            f"  RGB={last_colors[0]} raw_rms={frame.raw_rms:.3f} rms={frame.rms:.3f} bass={frame.bass:.3f} freq={frame.dominant_freq:.0f}Hz beat={frame.is_beat}"
                        )

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
                ipc.stop()
    finally:
        for dev, _ in devices:
            dev.close()
        print("\nDone.")


def main():
    parser = argparse.ArgumentParser(description="NuPhy Air75 V2 music-reactive RGB")
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {pkg_version('nuphy-rgb')}",
    )
    parser.add_argument(
        "--audio-device",
        type=int,
        default=None,
        help="Audio input device index (default: auto-detect loopback device)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="Target frames per second (default: 30)",
    )
    parser.add_argument(
        "--list-audio",
        action="store_true",
        help="List audio input devices and exit",
    )
    parser.add_argument(
        "--list-keyboards",
        action="store_true",
        help="List connected NuPhy keyboards and exit",
    )
    parser.add_argument(
        "--keyboard",
        type=str,
        default=None,
        help="Keyboard to drive: index (0, 1) or serial substring. Default: all connected.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug mode: prints frame data, Ctrl+C to quit",
    )
    parser.add_argument(
        "--effect",
        type=str,
        default=None,
        help="Start on a specific effect by name (case-insensitive, e.g. colorwash).",
    )
    parser.add_argument(
        "--list-effects",
        action="store_true",
        help="List available effects and exit.",
    )
    parser.add_argument(
        "--sidelight",
        type=str,
        default="VU Meter",
        help="Sidelight effect name (default: 'VU Meter').",
    )
    parser.add_argument(
        "--no-sidelight",
        action="store_true",
        help="Disable host sidelights (firmware handles them).",
    )
    parser.add_argument(
        "--list-sidelights",
        action="store_true",
        help="List available sidelight effects and exit.",
    )
    parser.add_argument(
        "--effects-dir",
        type=str,
        default=None,
        help="Custom plugin directory (default: ~/.config/nuphy-rgb).",
    )
    args = parser.parse_args()

    config_dir = Path(args.effects_dir) if args.effects_dir else None

    if args.list_effects:
        builtin_names = {cls.name for cls in ALL_EFFECTS}
        plugin_classes = _dedupe_plugins(discover_effects(config_dir), builtin_names)
        for cls in list(ALL_EFFECTS) + plugin_classes:
            print(cls.name)
        return

    if args.list_sidelights:
        builtin_names = {cls.name for cls in ALL_SIDELIGHTS}
        plugin_classes = _dedupe_plugins(discover_sidelights(config_dir), builtin_names)
        for cls in list(ALL_SIDELIGHTS) + plugin_classes:
            print(cls.name)
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
        sidelight=None if args.no_sidelight else args.sidelight,
        config_dir=config_dir,
    )


if __name__ == "__main__":
    main()
