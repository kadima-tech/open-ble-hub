"""V1: state, events, results and the WriteFF06Command layout."""

import unittest

from openble.bondtouch import v1

TEAL = (0x23, 0xE0, 0xE8)


def h(text: str, length: int) -> bytes:
    return bytes.fromhex(text).ljust(length, b"\x00")


def touch(count: int, ms: int) -> v1.Event:
    data = (
        bytes((v1.SEND_MSG, 0)) + count.to_bytes(2, "little") + ms.to_bytes(2, "little")
    )
    return v1.parse_event(data)


class ParseTests(unittest.TestCase):
    def test_state(self):
        state = v1.parse_state(bytes((0x84, 0xF4, 1)))
        self.assertEqual(
            (state.bond_state, state.paired_state), (v1.OOBE_ON, v1.WAITING_AUID)
        )
        self.assertTrue(state.charging)

    def test_event(self):
        event = v1.parse_event(bytes.fromhex("14 03 0200 2c01"))
        self.assertEqual((event.event_id, event.counter), (v1.SEND_MSG, 3))
        self.assertEqual((event.touch_count, event.touch_ms), (2, 300))

    def test_result(self):
        result = v1.parse_result(bytes.fromhex("0100 0700"))
        self.assertTrue(result.ok)
        self.assertEqual((result.name, result.seq), ("ACR_SUCCESS", 7))
        self.assertEqual(v1.parse_result(bytes.fromhex("0b00 0000")).name, "ACR_BUSY")
        with self.assertRaises(ValueError):
            v1.parse_result(b"\x01")

    def test_battery(self):
        def mv(value):
            return value.to_bytes(2, "little")

        self.assertEqual(v1.battery_percent(mv(3900)), 50)
        self.assertEqual(v1.battery_percent(mv(4200)), 100)
        self.assertEqual(v1.battery_percent(mv(3500)), 0)


class RecorderTests(unittest.TestCase):
    def test_gaps_from_arrival_times(self):
        recorder = v1.TouchRecorder()
        self.assertIsNone(recorder.feed(touch(1, 310), 10.0))
        self.assertIsNone(recorder.feed(touch(2, 200), 10.75))
        # Arrived 100 ms after the last, but pressed for 200: the gap is negative.
        self.assertIsNone(recorder.feed(touch(3, 200), 10.85))
        pattern = recorder.feed(touch(v1.END, 0), 11.0)
        self.assertEqual(pattern, (300, 550, 200, 100, 200))

    def test_timeout_ends_and_new_message_resets(self):
        recorder = v1.TouchRecorder()
        recorder.feed(touch(1, 400), 0.0)
        recorder.feed(touch(1, 100), 5.0)
        self.assertEqual(recorder.feed(touch(v1.TIMEOUT, 0), 6.0), (100,))
        self.assertIsNone(recorder.feed(touch(v1.END, 0), 7.0))


class CommandTests(unittest.TestCase):
    def test_colour_is_bgr_and_100(self):
        self.assertEqual(v1.colour(TEAL, seq=0x0102), h("2100 0201 e8e023 64", 16))

    def test_config(self):
        self.assertEqual(
            v1.touch_colour(TEAL),
            [
                h("2700 0000 eb030000 e8e02300", 16),
                h("2700 0000 ee030000 01000000", 16),
                h("2700 0000 e8030000", 8),
            ],
        )
        self.assertEqual(v1.led_id_for((0xA5, 0x02, 0xC0)), 3)
        self.assertEqual(v1.led_id_for((1, 2, 3)), v1.FALLBACK_LED)

    def test_dfu_and_reboot(self):
        self.assertEqual(v1.enter_dfu(seq=5), bytes.fromhex("2500 0500 ffffffff"))
        self.assertEqual(v1.reboot(), bytes.fromhex("2900 0000 ffffffff"))

    def test_play_pattern(self):
        self.assertEqual(
            v1.play_pattern([400, 50, 400], 2),
            [
                h("2600 0000 02 02 01 01 6400 2800", 16),
                h("2600 0000 02 01 01 01 6400 0a00", 16),  # max(50, 100) * 10 / 100
                h("2600 0000 02 02 01 01 6400 2800", 16),
                h("2600 0000 02 02 02 01", 16),
            ],
        )
        red = v1.play_pattern([400], 0)
        self.assertEqual(red[0][10:12], (133).to_bytes(2, "little"))  # 4000 / 30
        with self.assertRaises(ValueError):
            v1.play_pattern([400], 11)

    def test_seq(self):
        frame = v1.save_config()
        self.assertEqual(v1.seq_of(v1.with_seq(frame, 0x1FFFF)), 0xFFFF)
        self.assertEqual(v1.with_seq(v1.PAIRED_ACK, 9), b"\x31")
        self.assertIsNone(v1.seq_of(v1.PAIRED_ACK))


if __name__ == "__main__":
    unittest.main()
