"""NuPhy Air75 V2 HID probe and LED test utility."""

import argparse
import sys

import hid

from nuphy_rgb.hid_utils import (
    CMD_GET_TOTAL_LEDS,
    build_packet,
    find_raw_hid_path,
    send_frame,
    streaming_mode,
)


def probe(device: hid.device) -> int | None:
    """Send GET_TOTAL_LEDS and return the count, or None on failure."""
    device.write(build_packet(CMD_GET_TOTAL_LEDS))
    resp = device.read(32, timeout_ms=1000)
    if not resp:
        print("No response (timeout). Firmware handler may not be installed yet.")
        return None
    if resp[0] == 0xFF:
        print("Got id_unhandled. Firmware handler not installed yet.")
        return None
    if resp[0] == CMD_GET_TOTAL_LEDS:
        count = resp[1]
        print(f"GET_TOTAL_LEDS -> {count} LEDs")
        return count
    print(f"Unexpected response: {bytes(resp[:8]).hex()}")
    return None


def test_single_led(device: hid.device, led_index: int = 0):
    """Enable streaming, set one LED to red, wait, then restore."""
    with streaming_mode(device):
        print(f"Setting LED {led_index} to red...")
        colors = [(0, 0, 0)] * 84
        colors[led_index] = (255, 0, 0)
        send_frame(device, colors)
        input("LED should be red. Press Enter to restore normal RGB...")
    print("Streaming disabled. Normal RGB restored.")


def test_all_red(device: hid.device, total_leds: int):
    """Set all LEDs to red, wait, then restore."""
    with streaming_mode(device):
        print(f"Setting all {total_leds} LEDs to red...")
        colors = [(255, 0, 0)] * total_leds
        send_frame(device, colors)
        input("All LEDs should be red. Press Enter to restore normal RGB...")
    print("Streaming disabled. Normal RGB restored.")


def main():
    parser = argparse.ArgumentParser(description="NuPhy Air75 V2 HID probe")
    parser.add_argument("--test-led", action="store_true", help="Test single LED (Esc key)")
    parser.add_argument("--all-red", action="store_true", help="Set all LEDs to red")
    args = parser.parse_args()

    print("Looking for NuPhy keyboard...")
    path = find_raw_hid_path()
    if path is None:
        print("Keyboard not found. Is it plugged in via USB?")
        print("(Also check: VIA must be closed, macOS Input Monitoring permission may be needed)")
        sys.exit(1)

    print(f"Found Raw HID interface: {path}")

    device = hid.device()
    try:
        device.open_path(path)
    except OSError as e:
        print(f"Failed to open device: {e}")
        print("On macOS, check System Settings > Privacy & Security > Input Monitoring")
        sys.exit(1)

    try:
        led_count = probe(device)

        if args.test_led and led_count is not None:
            test_single_led(device)
        elif args.all_red and led_count is not None:
            test_all_red(device, led_count)
    finally:
        device.close()


if __name__ == "__main__":
    main()
