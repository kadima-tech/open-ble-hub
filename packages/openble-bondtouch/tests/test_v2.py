"""V2, V4 and Mini: state, events, recording and the ffa6 frames."""

import unittest

from openble.bondtouch import v2
from openble.bondtouch.identify import MINI, V2, V4
from openble.bondtouch.patterns import MINI_PATTERN

TEAL = (0x23, 0xE0, 0xE8)
RED = (0xFF, 0, 0)


def h(text: str) -> bytes:
    """Hex, padded with zeros to the 20-byte frame."""
    return bytes.fromhex(text).ljust(20, b"\x00")


def press(counter, touch_ms, release_ms=0, last=False, slot=0):
    stop = 0xFFFFFFFF if last else 0
    return (
        bytes((v2.SEND_MSG, counter))
        + touch_ms.to_bytes(4, "little")
        + release_ms.to_bytes(4, "little")
        + stop.to_bytes(4, "little")
        + bytes((slot,))
    )


class StateTests(unittest.TestCase):
    def test_state(self):
        state = v2.parse_state(bytes((0x85, 1, 0, 0, 1)))
        self.assertEqual(state.name, "CONNECTED")
        self.assertEqual(v2.CHARGING_STATES[state.charging], "charging")
        self.assertTrue(state.touch_busy)
        self.assertFalse(state.motor_busy)
        self.assertEqual(v2.parse_state(b"\x82").name, "WAITING_TOKEN")

    def test_battery(self):
        self.assertEqual(v2.battery_percent(b"\x4b\x00"), 75)


class EventTests(unittest.TestCase):
    def test_send_msg(self):
        event = v2.parse_event(press(2, 400, 200, last=True, slot=3), V4)
        self.assertEqual((event.name, event.counter), ("SEND_MSG", 2))
        self.assertEqual((event.touch_ms, event.release_ms), (400, 200))
        self.assertTrue(event.last)
        self.assertEqual(event.slot, 3)
        self.assertIsNone(v2.parse_event(press(1, 400), V2).slot)
        self.assertEqual(v2.parse_event(press(1, 400, slot=9), V4).slot, 1)

    def test_short_event(self):
        event = v2.parse_event(b"\x13\x00")
        self.assertEqual(
            (event.name, event.touch_ms, event.last), ("PAIRED_SIGNAL", 0, False)
        )

    def test_ship_mode(self):
        report = b"\x19" + bytes(range(1, 14))
        event = v2.parse_event(report)
        self.assertEqual((event.name, event.raw), ("SHIP_MODE", report))


class RecorderTests(unittest.TestCase):
    def feed(self, recorder, generation, *events):
        return [recorder.feed(v2.parse_event(event, generation)) for event in events]

    def test_pattern(self):
        recorder = v2.TouchRecorder(V2)
        results = self.feed(
            recorder,
            V2,
            press(1, 30),
            press(2, 400, 20),
            press(3, 300, 250, last=True),
        )
        self.assertEqual(results[:2], [None, None])
        self.assertEqual(results[2], v2.TouchMessage((50, 50, 400, 250, 300), 1))

    def test_v4_slot_and_mini(self):
        v4 = v2.TouchRecorder(V4)
        message = self.feed(v4, V4, press(1, 300, last=True, slot=2))[0]
        self.assertEqual(message, v2.TouchMessage((300,), 2))
        mini = v2.TouchRecorder(MINI)
        message = self.feed(mini, MINI, press(1, 80), press(2, 90, 60, last=True))[1]
        self.assertEqual(message.pattern, MINI_PATTERN)

    def test_live_touch_ends_with_timeout(self):
        # V2 on 2.6.4, three presses, 2026-10-16. No press had stop 0xFFFFFFFF;
        # a SEND_MSG_TIMEOUT with counter 4 ended the message.
        recorder = v2.TouchRecorder(V2)
        results = self.feed(
            recorder,
            V2,
            bytes.fromhex("14 01 68000000 00000000 00000000"),
            bytes.fromhex("14 02 e6020000 16020000 00000000"),
            bytes.fromhex("14 03 32050000 d2010000 00000000"),
            bytes.fromhex("15 04 00000000 00000000 ffffffff"),
        )
        self.assertEqual(results[:3], [None, None, None])
        self.assertEqual(results[3], v2.TouchMessage((104, 534, 742, 466, 1330), 1))
        # A second timeout has nothing left to deliver.
        self.assertIsNone(self.feed(recorder, V2, bytes.fromhex("15 04"))[0])

    def test_timeout_discards(self):
        recorder = v2.TouchRecorder(V2)
        timeout = bytes((v2.SEND_MSG_TIMEOUT, 0))
        results = self.feed(
            recorder, V2, press(1, 400), timeout, press(2, 300, 100, last=True)
        )
        # The press after the discard starts a new pattern.
        self.assertEqual(results[2].pattern, (300,))


class FrameTests(unittest.TestCase):
    def test_fixed_frames(self):
        self.assertEqual(v2.PAIRED_ACK, h("31 00 11 22 33 44"))
        self.assertEqual(v2.ENTER_DFU, h("25 00 11 22 33 44"))
        self.assertEqual(v2.RUN_TOUCH, h("32 00 11"))
        self.assertEqual(v2.RUN_ANIMATION, h("32 00 22"))
        self.assertEqual(v2.wake_gesture(False), h("34 00 22"))
        self.assertEqual(v2.auid(0x12345678), bytes.fromhex("78 56 34 12"))

    def test_presets(self):
        self.assertEqual(
            v2.show_colour(TEAL), h("26 00 00 00 0000 01 23e0e8 50 0000 0000 0000 ffff")
        )
        self.assertEqual(v2.clear_colour(), h("26 00 00 00 0000 04"))
        self.assertEqual(v2.vibration_test(60), h("26 00 00 3c d007 04"))
        self.assertEqual(
            v2.vibration_test(60, TEAL),
            h("26 00 00 3c d007 01 23e0e8 50 0000 0000 0000 d007"),
        )
        self.assertEqual(
            v2.double_tap_answer(TEAL),
            h("26 00 00 00 0000 02 23e0e8 50 f401 e803 0000 d007"),
        )
        self.assertEqual(
            v2.wake_demo(TEAL),
            h("26 00 00 32 fa00 02 23e0e8 50 f401 d007 fa00 ffff"),
        )

    def test_play_touch(self):
        frames = v2.play_touch([400, 200, 300], RED, 80)
        self.assertEqual(
            frames,
            [
                # press 400: fade 100, hold 200, sleep 200, total 600
                h("26 00 01 50 9001 02 ff0000 50 6400 c800 c800 5802"),
                # press 300: fade 75, hold 150, sleep 0, total 300
                h("26 00 01 50 2c01 02 ff0000 50 4b00 9600 0000 2c01"),
                v2.RUN_TOUCH,
            ],
        )
        self.assertTrue(all(len(frame) == 20 for frame in frames))

    def test_play_per_generation(self):
        v4 = v2.play([400], RED, V4, slot=2)
        self.assertEqual(v4[0], h("27 00 37 01 02"))
        self.assertEqual(len(v4), 3)
        mini = v2.play([400], RED, MINI)
        self.assertEqual(len(mini), 4)  # three presses of MINI_PATTERN, then run
        self.assertEqual(mini[0][4:6], (500).to_bytes(2, "little"))

    def test_play_blend(self):
        frames = v2.play_blend([400, 100, 200], RED, (0, 0, 0xFF), 60)
        self.assertEqual(len(frames), 5)  # 2 press frames, gap, 1 press frame, run
        self.assertEqual(frames[0], h("33 00 3c 505050 ff0000 ff0000 ff0000 c800"))
        self.assertEqual(frames[2], h("33 00 00 000000 000000 000000 000000 6400"))
        # The last press starts 500 ms into 700 ms: 5/7 of the way to blue.
        self.assertEqual(frames[3][6:9], bytes((73, 0, 182)))
        self.assertEqual(frames[-1], v2.RUN_ANIMATION)

    def test_ranges(self):
        with self.assertRaises(ValueError):
            v2.led_motor(strength=101)
        with self.assertRaises(ValueError):
            v2.led_motor(total_ms=0x10000)
        with self.assertRaises(ValueError):
            v2.frame(bytes(21))

    def test_strength(self):
        self.assertEqual(v2.strength_of(58), 58)
        self.assertEqual(v2.strength_of(50), 80)


class ConfigTests(unittest.TestCase):
    def test_colours_are_big_endian_argb(self):
        self.assertEqual(v2.touch_colour(TEAL), h("27 00 25 01 ff 23 e0 e8"))
        self.assertEqual(
            v2.own_colour(TEAL, V2),
            [h("27 00 25 01 ff23e0e8"), h("27 00 24 01 ff23e0e8")],
        )
        self.assertEqual(v2.own_colour(TEAL, V4)[1], h("27 00 24 01 ff23e0e8 00000080"))

    def test_partner_menu(self):
        self.assertEqual(
            v2.partner_menu([RED, TEAL]),
            [
                h("27 00 24 01 ffff0000 00000081"),
                h("27 00 24 01 ff23e0e8 00000082"),
                h("27 00 24 01 ff000000 00000003"),
            ],
        )
        # Slot 1 alone is not shown.
        self.assertEqual(v2.partner_menu([RED])[0], h("27 00 24 01 ff000000 00000001"))
        with self.assertRaises(ValueError):
            v2.partner_menu([RED] * 4)

    def test_after_bonding(self):
        batch = v2.after_bonding(V2)
        self.assertEqual(
            batch,
            [
                h("27 00 17 01 0a"),
                h("27 00 21 01 01 03e8 01f4 00000493 00ff0000"),
                h("27 00 14 01 32000000"),
                h("27 00 31 01 00 0000 0000 0000 00000000"),
                h("27 00 33 01 00"),
            ],
        )
        self.assertEqual(v2.after_bonding(V4), batch[:4])

    def test_other_properties(self):
        self.assertEqual(v2.selected_user(3), h("27 00 37 01 03"))
        self.assertEqual(v2.motor_strength(88), h("27 00 18 01 58"))
        self.assertEqual(v2.ancs(True), h("27 00 33 01 01"))
        self.assertEqual(v2.reset_config(), h("27 00 ef 01"))
        with self.assertRaises(ValueError):
            v2.selected_user(4)


if __name__ == "__main__":
    unittest.main()
