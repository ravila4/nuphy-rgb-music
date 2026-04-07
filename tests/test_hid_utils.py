import pytest
from unittest.mock import MagicMock, call, patch

from nuphy_rgb.hid_utils import (
    CMD_STREAMING_MODE_OFF,
    CMD_STREAMING_MODE_ON,
    CMD_STREAM_RGB_DATA,
    LEDS_PER_PACKET,
    NUPHY_PID,
    NUPHY_VID,
    PACKET_SIZE,
    RAW_HID_USAGE,
    RAW_HID_USAGE_PAGE,
    build_packet,
    find_raw_hid_path,
    send_frame,
    streaming_mode,
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


class TestSendFrame:
    def _make_device(self):
        return MagicMock()

    def test_sends_10_packets_for_84_leds(self):
        device = self._make_device()
        colors = [(255, 0, 0)] * 84
        send_frame(device, colors)
        assert device.write.call_count == 10  # ceil(84/9)

    def test_last_packet_has_partial_leds(self):
        device = self._make_device()
        colors = [(0, 255, 0)] * 84
        send_frame(device, colors)
        last_call = device.write.call_args_list[-1]
        pkt = last_call[0][0]
        assert pkt[1] == CMD_STREAM_RGB_DATA
        assert pkt[2] == 81  # start index
        assert pkt[3] == 3   # 3 LEDs in last packet

    def test_start_indices_are_correct(self):
        device = self._make_device()
        colors = [(0, 0, 255)] * 84
        send_frame(device, colors)
        expected_starts = list(range(0, 84, LEDS_PER_PACKET))
        for i, c in enumerate(device.write.call_args_list):
            pkt = c[0][0]
            assert pkt[2] == expected_starts[i]

    def test_rgb_values_placed_correctly(self):
        device = self._make_device()
        colors = [(10, 20, 30)] + [(0, 0, 0)] * 83
        send_frame(device, colors)
        first_pkt = device.write.call_args_list[0][0][0]
        assert first_pkt[4] == 10   # R
        assert first_pkt[5] == 20   # G
        assert first_pkt[6] == 30   # B

    def test_all_packets_are_33_bytes(self):
        device = self._make_device()
        colors = [(128, 64, 32)] * 84
        send_frame(device, colors)
        for c in device.write.call_args_list:
            assert len(c[0][0]) == PACKET_SIZE + 1

    def test_fewer_than_84_leds(self):
        device = self._make_device()
        colors = [(255, 0, 0)] * 10
        send_frame(device, colors)
        assert device.write.call_count == 2  # ceil(10/9)


class TestStreamingMode:
    def _make_device(self, ack_on=True, ack_off=True):
        device = MagicMock()
        responses = []
        if ack_on:
            responses.append([CMD_STREAMING_MODE_ON] + [0] * 31)
        else:
            responses.append(None)
        if ack_off:
            responses.append([CMD_STREAMING_MODE_OFF] + [0] * 31)
        else:
            responses.append(None)
        device.read.side_effect = responses
        return device

    def test_enables_and_disables_streaming(self):
        device = self._make_device()
        with streaming_mode(device):
            pass
        writes = [c[0][0] for c in device.write.call_args_list]
        assert writes[0][1] == CMD_STREAMING_MODE_ON
        assert writes[1][1] == CMD_STREAMING_MODE_OFF

    def test_disables_streaming_on_exception(self):
        device = self._make_device()
        with pytest.raises(RuntimeError):
            with streaming_mode(device):
                raise RuntimeError("boom")
        writes = [c[0][0] for c in device.write.call_args_list]
        assert writes[1][1] == CMD_STREAMING_MODE_OFF

    def test_raises_on_failed_enable(self):
        device = self._make_device(ack_on=False)
        with pytest.raises(ConnectionError, match="streaming mode"):
            with streaming_mode(device):
                pass
