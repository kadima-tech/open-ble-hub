"""0xAA frames and the CRC-8, checked against the manual's example bytes."""

import unittest

from openble.lovense.frames import (
    PATTERN_STOP,
    crc8,
    parse_response,
    pattern_points_20,
    pattern_points_100,
    pattern_status,
    play_pattern_action,
    read_pattern_status,
    request,
    wifi_status,
)


def response(*body: int) -> bytes:
    return bytes(body) + bytes((crc8(bytes(body)),))


class CrcTests(unittest.TestCase):
    def test_check_value(self):
        self.assertEqual(crc8(b"123456789"), 0xD4)


class RequestTests(unittest.TestCase):
    def test_manual_examples(self):
        self.assertEqual(read_pattern_status(), bytes.fromhex("aa 8b 00 70"))
        self.assertEqual(
            play_pattern_action(PATTERN_STOP), bytes.fromhex("aa 8a 01 00 a1")
        )
        self.assertEqual(wifi_status(), bytes.fromhex("aa 93 01 00 05"))

    def test_length_limit(self):
        request(0x80, bytes(245))
        with self.assertRaises(ValueError):
            request(0x80, bytes(246))

    def test_unknown_play_action(self):
        with self.assertRaises(ValueError):
            play_pattern_action(4)


class ResponseTests(unittest.TestCase):
    def test_split(self):
        frame = parse_response(response(0xAA, 0x93, 0x00, 0x02, 0x00, 0x01))
        self.assertEqual((frame.command, frame.status), (0x93, 0x00))
        self.assertEqual(frame.params, b"\x00\x01")
        self.assertTrue(frame.ok)

    def test_status_text(self):
        frame = parse_response(response(0xAA, 0x8A, 0x03, 0x00))
        self.assertFalse(frame.ok)
        self.assertEqual(frame.status_text, "command not supported")

    def test_bad_crc(self):
        data = bytearray(response(0xAA, 0x8B, 0x00, 0x00))
        data[-1] ^= 0xFF
        with self.assertRaisesRegex(ValueError, "CRC"):
            parse_response(bytes(data))

    def test_length_mismatch(self):
        with self.assertRaisesRegex(ValueError, "LEN"):
            parse_response(response(0xAA, 0x8B, 0x00, 0x02, 0x00))

    def test_pattern_status(self):
        # params: 00, free space 0x0210, time index 0x040005 masked to 18 bits.
        frame = parse_response(
            response(0xAA, 0x8B, 0x00, 0x06, 0x00, 0x10, 0x02, 0x05, 0x00, 0x04)
        )
        self.assertEqual(pattern_status(frame), (528, 5))


class PatternPointTests(unittest.TestCase):
    def test_points_20(self):
        self.assertEqual(
            pattern_points_20([(0x2_1234, 20), (1, 0)]),
            bytes.fromhex("34 12 94 01 00 00"),
        )
        with self.assertRaises(ValueError):
            pattern_points_20([(0, 21)])

    def test_points_100(self):
        self.assertEqual(
            pattern_points_100([(0x010203, 100)]), bytes.fromhex("03 02 01 64")
        )


if __name__ == "__main__":
    unittest.main()
