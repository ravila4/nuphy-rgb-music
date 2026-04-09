"""Platform-specific audio loopback device discovery."""

import logging
import os
import subprocess
import sys

import sounddevice as sd

log = logging.getLogger(__name__)


def find_pactl_monitor() -> str | None:
    """Find a PulseAudio/PipeWire monitor source name via ``pactl``.

    Prefers the monitor of the default sink (what the user is hearing).
    Falls back to any ``.monitor`` source.
    """
    try:
        default_sink = subprocess.check_output(
            ["pactl", "get-default-sink"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        default_sink = None

    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources", "short"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    fallback: str | None = None
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[1].endswith(".monitor"):
            if default_sink and fields[1] == f"{default_sink}.monitor":
                return fields[1]
            if fallback is None:
                fallback = fields[1]
    return fallback


def move_source_output_to_monitor(monitor_name: str) -> None:
    """Redirect our own PulseAudio/PipeWire capture stream to *monitor_name*.

    Must be called after the ``sounddevice`` stream has been opened so that a
    source-output exists.  Finds the source-output belonging to our PID and
    moves it with ``pactl move-source-output``.
    """
    pid = str(os.getpid())
    try:
        out = subprocess.check_output(
            ["pactl", "list", "source-outputs"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        log.debug("pactl list source-outputs failed")
        return

    # Parse source-output blocks to find ours by PID.
    current_index: str | None = None
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("Source Output #"):
            current_index = stripped.split("#")[1]
        elif "application.process.id" in stripped and pid in stripped:
            if current_index is not None:
                try:
                    subprocess.check_call(
                        ["pactl", "move-source-output", current_index, monitor_name],
                        stderr=subprocess.DEVNULL,
                    )
                    log.debug(
                        "Moved source-output %s -> %s", current_index, monitor_name
                    )
                except subprocess.CalledProcessError:
                    log.warning(
                        "Failed to move source-output %s to %s",
                        current_index,
                        monitor_name,
                    )
                return

    log.debug("No source-output found for PID %s", pid)


def find_loopback_device() -> tuple[int, str | None] | None:
    """Find a system-audio loopback device.

    macOS: BlackHole virtual audio device.
    Linux: PulseAudio/PipeWire monitor source (via sounddevice or pactl).

    Returns ``(device_index, monitor_name)`` where *monitor_name* is set only
    when the device needs per-app routing via ``pactl move-source-output``
    after the stream is opened.  Returns ``None`` when no device is found.
    """
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] <= 0:
            continue
        name = d["name"]
        if "BlackHole" in name:
            return (i, None)
        if sys.platform.startswith("linux") and name.lower().startswith("monitor of "):
            return (i, None)

    # On Linux, PortAudio often lacks a PulseAudio backend so monitor sources
    # are invisible.  Fall back to pactl detection + per-app stream routing.
    if sys.platform.startswith("linux"):
        monitor = find_pactl_monitor()
        if monitor is not None:
            # Use the "default" ALSA device; we'll reroute our stream after open.
            default_idx = sd.default.device[0]
            if default_idx is None or default_idx < 0:
                default_idx = 0
            return (default_idx, monitor)

    return None


def list_audio_devices() -> None:
    """Print available audio input devices."""
    print("Audio input devices:")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            if "BlackHole" in d["name"]:
                marker = " <-- BlackHole"
            elif sys.platform.startswith("linux") and d["name"].lower().startswith(
                "monitor of "
            ):
                marker = " <-- monitor source"
            else:
                marker = ""
            print(f"  {i}: {d['name']} ({d['max_input_channels']}ch){marker}")
    if sys.platform.startswith("linux"):
        monitor = find_pactl_monitor()
        if monitor:
            print(f"\n  PipeWire/PulseAudio monitor: {monitor}")
            print("  (Auto-detected — will be routed at runtime via pactl)")
