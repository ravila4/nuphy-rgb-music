import sys
from contextlib import contextmanager
from dataclasses import dataclass

import hid

NUPHY_VID = 0x19F5
NUPHY_PID = 0x3246
RAW_HID_USAGE_PAGE = 0xFF60
RAW_HID_USAGE = 0x61
PACKET_SIZE = 32  # payload size (write prepends 0x00 report ID)

# Protocol command IDs (must match firmware defines)
CMD_STREAM_RGB_DATA = 0x24
CMD_STREAMING_MODE_ON = 0x25
CMD_STREAMING_MODE_OFF = 0x26
CMD_GET_TOTAL_LEDS = 0x27
CMD_STREAM_SIDE_DATA = 0x28
CMD_SIDE_STREAMING_ON = 0x29
CMD_SIDE_STREAMING_OFF = 0x2A
SIDE_LED_COUNT = 12

LEDS_PER_PACKET = 9  # max RGB triples that fit in 32-byte payload


@dataclass(frozen=True)
class KeyboardInfo:
    """A discovered NuPhy keyboard."""

    index: int
    path: bytes
    serial: str


def find_keyboards(
    vid: int = NUPHY_VID, pid: int = NUPHY_PID
) -> list[KeyboardInfo]:
    """Find all connected NuPhy keyboards with Raw HID interfaces.

    On Linux the hidraw backend does not populate usage_page/usage (always 0),
    so we fall back to returning all VID/PID matches and let the caller probe.
    """
    devices = hid.enumerate(vid, pid)
    keyboards = []
    for d in devices:
        # usage_page=0 means the backend didn't populate it (Linux hidraw) —
        # accept the device and let the caller probe to confirm.
        if d["usage_page"] != 0 and (
            d["usage_page"] != RAW_HID_USAGE_PAGE or d["usage"] != RAW_HID_USAGE
        ):
            continue
        keyboards.append(KeyboardInfo(
            index=len(keyboards),
            path=d["path"],
            serial=d["serial_number"],
        ))
    return keyboards


def select_keyboards(
    keyboards: list[KeyboardInfo], device_filter: str | None = None
) -> list[KeyboardInfo]:
    """Filter keyboards by index or serial substring.

    None filter → all keyboards. Single digit → match by index (0-9).
    Anything else → match serial number as substring (case-insensitive).
    Raises ValueError on no match or ambiguous match.
    """
    if device_filter is None:
        return keyboards

    # Try index match first (single digit only — serials are long hex strings)
    if len(device_filter) == 1 and device_filter.isdigit():
        idx = int(device_filter)
        for kb in keyboards:
            if kb.index == idx:
                return [kb]
        raise ValueError(
            f"No keyboard at index {idx}. "
            f"Available: {', '.join(str(kb.index) for kb in keyboards)}"
        )

    # Serial substring match (case-insensitive)
    needle = device_filter.lower()
    matches = [kb for kb in keyboards if needle in kb.serial.lower()]
    if len(matches) == 1:
        return matches
    if len(matches) == 0:
        raise ValueError(
            f"No keyboard serial matches '{device_filter}'. "
            f"Use --list-keyboards to see connected devices."
        )
    raise ValueError(
        f"'{device_filter}' matches {len(matches)} keyboards — be more specific. "
        f"Serials: {', '.join(m.serial for m in matches)}"
    )


def find_raw_hid_path(vid: int = NUPHY_VID, pid: int = NUPHY_PID) -> bytes | None:
    """Find the Raw HID interface path for the NuPhy keyboard."""
    keyboards = find_keyboards(vid, pid)
    return keyboards[0].path if keyboards else None


def build_packet(command_id: int, *args: int) -> bytes:
    """Build a 33-byte HID write packet (report ID + 32-byte payload).

    Raises ValueError if the payload exceeds PACKET_SIZE.
    """
    payload = bytes([command_id, *args])
    if len(payload) > PACKET_SIZE:
        raise ValueError(
            f"Packet payload {len(payload)} bytes exceeds max {PACKET_SIZE}"
        )
    return b"\x00" + payload.ljust(PACKET_SIZE, b"\x00")


def _send_led_frame(
    device: hid.device, command_id: int, colors: list[tuple[int, int, int]]
) -> None:
    """Send LED colors to the keyboard. Fire-and-forget (no ACK)."""
    for start in range(0, len(colors), LEDS_PER_PACKET):
        chunk = colors[start : start + LEDS_PER_PACKET]
        rgb_bytes = []
        for r, g, b in chunk:
            rgb_bytes.extend((r, g, b))
        device.write(build_packet(command_id, start, len(chunk), *rgb_bytes))


def send_frame(device: hid.device, colors: list[tuple[int, int, int]]) -> None:
    """Send per-key RGB colors to the keyboard."""
    _send_led_frame(device, CMD_STREAM_RGB_DATA, colors)


def send_side_frame(device: hid.device, colors: list[tuple[int, int, int]]) -> None:
    """Send side LED colors to the keyboard (12 LEDs)."""
    if len(colors) != SIDE_LED_COUNT:
        raise ValueError(
            f"Expected {SIDE_LED_COUNT} side LED colors, got {len(colors)}"
        )
    _send_led_frame(device, CMD_STREAM_SIDE_DATA, colors)


@contextmanager
def _streaming_ctx(device: hid.device, on_cmd: int, off_cmd: int, label: str):
    """Context manager that enables/disables a streaming mode.

    Ensures streaming is disabled on exit, even on exceptions.
    """
    device.write(build_packet(on_cmd))
    resp = device.read(32, timeout_ms=1000)
    if not resp or resp[0] != on_cmd:
        raise ConnectionError(f"Failed to enable {label} streaming mode")
    try:
        yield
    finally:
        device.write(build_packet(off_cmd))
        resp = device.read(32, timeout_ms=1000)
        if not resp or resp[0] != off_cmd:
            print(
                f"Warning: failed to confirm {label} streaming mode disabled. "
                "Keyboard may need USB replug.",
                file=sys.stderr,
            )


def streaming_mode(device: hid.device):
    """Context manager for per-key RGB streaming mode."""
    return _streaming_ctx(device, CMD_STREAMING_MODE_ON, CMD_STREAMING_MODE_OFF, "RGB")


def side_streaming_mode(device: hid.device):
    """Context manager for side LED streaming mode."""
    return _streaming_ctx(
        device, CMD_SIDE_STREAMING_ON, CMD_SIDE_STREAMING_OFF, "side"
    )
