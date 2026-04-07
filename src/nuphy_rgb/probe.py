"""NuPhy Air75 V2 HID probe and LED test utility."""

import argparse
import sys

import hid

from nuphy_rgb.hid_utils import (
    CMD_GET_TOTAL_LEDS,
    CMD_STREAM_RGB_DATA,
    CMD_STREAMING_MODE_OFF,
    CMD_STREAMING_MODE_ON,
    LEDS_PER_PACKET,
    build_packet,
    find_raw_hid_path,
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
    print("Enabling streaming mode...")
    device.write(build_packet(CMD_STREAMING_MODE_ON))
    resp = device.read(32, timeout_ms=1000)
    if not resp or resp[0] != CMD_STREAMING_MODE_ON:
        print(f"Failed to enable streaming mode. Response: {bytes(resp[:4]).hex() if resp else 'timeout'}")
        return

    print(f"Setting LED {led_index} to red...")
    device.write(build_packet(CMD_STREAM_RGB_DATA, led_index, 1, 255, 0, 0))

    input("LED should be red. Press Enter to restore normal RGB...")

    device.write(build_packet(CMD_STREAMING_MODE_OFF))
    device.read(32, timeout_ms=1000)
    print("Streaming disabled. Normal RGB restored.")


def test_all_red(device: hid.device, total_leds: int):
    """Set all LEDs to red, wait, then restore."""
    print("Enabling streaming mode...")
    device.write(build_packet(CMD_STREAMING_MODE_ON))
    resp = device.read(32, timeout_ms=1000)
    if not resp or resp[0] != CMD_STREAMING_MODE_ON:
        print(f"Failed to enable streaming mode. Response: {bytes(resp[:4]).hex() if resp else 'timeout'}")
        return

    print(f"Setting all {total_leds} LEDs to red...")
    for start in range(0, total_leds, LEDS_PER_PACKET):
        count = min(LEDS_PER_PACKET, total_leds - start)
        rgb_data = [255, 0, 0] * count
        device.write(build_packet(CMD_STREAM_RGB_DATA, start, count, *rgb_data))

    input("All LEDs should be red. Press Enter to restore normal RGB...")

    device.write(build_packet(CMD_STREAMING_MODE_OFF))
    device.read(32, timeout_ms=1000)
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
