import pytest
from unittest.mock import patch

from nuphy_rgb.hid_utils import (
    NUPHY_PID,
    NUPHY_VID,
    PACKET_SIZE,
    RAW_HID_USAGE,
    RAW_HID_USAGE_PAGE,
    build_packet,
    find_raw_hid_path,
)


class TestBuildPacket:
    def test_length_is_33(self):
        pkt = build_packet(0x27)
        assert len(pkt) == PACKET_SIZE + 1  # 1 report ID + 32 payload

    def test_report_id_is_zero(self):
        pkt = build_packet(0x27)
        assert pkt[0] == 0x00

    def test_command_at_byte_1(self):
        pkt = build_packet(0x27)
        assert pkt[1] == 0x27

    def test_args_placed_after_command(self):
        pkt = build_packet(0x24, 10, 3, 255, 0, 128)
        assert pkt[1] == 0x24
        assert pkt[2] == 10   # start_idx
        assert pkt[3] == 3    # num_leds
        assert pkt[4] == 255  # R
        assert pkt[5] == 0    # G
        assert pkt[6] == 128  # B

    def test_zero_padded(self):
        pkt = build_packet(0x27)
        assert pkt[2:] == bytes(31)

    def test_max_payload_fits(self):
        # 32 bytes of payload = 1 command + 31 args
        args = list(range(31))
        pkt = build_packet(0x24, *args)
        assert len(pkt) == 33
        assert pkt[1] == 0x24
        for i, v in enumerate(args):
            assert pkt[2 + i] == v

    def test_overflow_raises_value_error(self):
        # 33 bytes of payload = 1 command + 32 args > PACKET_SIZE
        with pytest.raises(ValueError, match="exceeds max"):
            build_packet(0x24, *range(32))

    def test_full_rgb_packet_fits(self):
        # 9 LEDs: cmd + start + count + 9*3 RGB = 1+1+1+27 = 30 bytes
        pkt = build_packet(0x24, 0, 9, *([255, 0, 0] * 9))
        assert len(pkt) == 33
        assert pkt[1] == 0x24
        assert pkt[2] == 0     # start
        assert pkt[3] == 9     # count
        assert pkt[4] == 255   # first R


class TestFindRawHidPath:
    @patch("nuphy_rgb.hid_utils.hid")
    def test_finds_matching_device(self, mock_hid):
        mock_hid.enumerate.return_value = [
            {
                "vendor_id": NUPHY_VID,
                "product_id": NUPHY_PID,
                "usage_page": 0x01,
                "usage": 0x06,
                "path": b"keyboard-path",
            },
            {
                "vendor_id": NUPHY_VID,
                "product_id": NUPHY_PID,
                "usage_page": RAW_HID_USAGE_PAGE,
                "usage": RAW_HID_USAGE,
                "path": b"raw-hid-path",
            },
        ]
        assert find_raw_hid_path() == b"raw-hid-path"

    @patch("nuphy_rgb.hid_utils.hid")
    def test_returns_none_when_not_found(self, mock_hid):
        mock_hid.enumerate.return_value = []
        assert find_raw_hid_path() is None

    @patch("nuphy_rgb.hid_utils.hid")
    def test_ignores_wrong_usage_page(self, mock_hid):
        mock_hid.enumerate.return_value = [
            {
                "vendor_id": NUPHY_VID,
                "product_id": NUPHY_PID,
                "usage_page": 0x01,
                "usage": 0x06,
                "path": b"keyboard-path",
            },
        ]
        assert find_raw_hid_path() is None
