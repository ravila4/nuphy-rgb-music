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
    """Find all connected NuPhy keyboards with Raw HID interfaces."""
    devices = hid.enumerate(vid, pid)
    keyboards = []
    for d in devices:
        if d["usage_page"] == RAW_HID_USAGE_PAGE and d["usage"] == RAW_HID_USAGE:
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


def send_frame(device: hid.device, colors: list[tuple[int, int, int]]) -> None:
    """Send per-key RGB colors to the keyboard. Fire-and-forget (no ACK)."""
    for start in range(0, len(colors), LEDS_PER_PACKET):
        chunk = colors[start : start + LEDS_PER_PACKET]
        rgb_bytes = []
        for r, g, b in chunk:
            rgb_bytes.extend((r, g, b))
        device.write(build_packet(CMD_STREAM_RGB_DATA, start, len(chunk), *rgb_bytes))


@contextmanager
def streaming_mode(device: hid.device):
    """Context manager that enables/disables RGB streaming mode.

    Ensures streaming is disabled on exit, even on exceptions.
    """
    device.write(build_packet(CMD_STREAMING_MODE_ON))
    resp = device.read(32, timeout_ms=1000)
    if not resp or resp[0] != CMD_STREAMING_MODE_ON:
        raise ConnectionError("Failed to enable streaming mode")
    try:
        yield
    finally:
        device.write(build_packet(CMD_STREAMING_MODE_OFF))
        resp = device.read(32, timeout_ms=1000)
        if not resp or resp[0] != CMD_STREAMING_MODE_OFF:
            print(
                "Warning: failed to confirm streaming mode disabled. "
                "Keyboard may need USB replug.",
                file=sys.stderr,
            )
