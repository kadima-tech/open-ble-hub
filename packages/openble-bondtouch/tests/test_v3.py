"""V3 (Bond More): ffb1 commands and notifications, ffb2 touch frames."""

import unittest

from openble.bondtouch import v3
from openble.bondtouch.patterns import to_samples


class CommandTests(unittest.TestCase):
    def test_setup(self):
        self.assertEqual(v3.TOKEN, bytes.fromhex("03 3132333435363738"))
        self.assertEqual(v3.auid(0x12345678), bytes.fromhex("07 78"))
        self.assertEqual(v3.PAIRED_ACK, bytes.fromhex("01 31"))

    def test_lights_and_vibration(self):
        self.assertEqual(
            v3.show_colour((0, 0xFF, 0), True), bytes.fromhex("01 4b 00 01 00ff00")
        )
        self.assertEqual(v3.show_colour("FF2D55"), bytes.fromhex("01 4b 00 00 ff2d55"))
        self.assertEqual(v3.vibration_test(5, 2), bytes.fromhex("01 48 00 05 02 03"))
        self.assertEqual(v3.save_vibration(5, 2), bytes.fromhex("01 48 02 05 02 03"))

    def test_partner_menu(self):
        menu = v3.partner_menu(
            [(v3.ACTIVE, v3.TUTORIAL_MENU[0]), (v3.INACTIVE, (0, 0, 0))]
        )
        self.assertEqual(menu, bytes.fromhex("01 45 00 01ffff00 00000000 02000000"))
        with self.assertRaises(ValueError):
            v3.partner_menu([(3, (0, 0, 0))])


class NotificationTests(unittest.TestCase):
    def parse(self, text):
        return v3.parse(bytes.fromhex(text))

    def test_state_and_events(self):
        self.assertEqual(self.parse("04 82").value, v3.WAITING_TOKEN)
        self.assertEqual(self.parse("02 13").value, (v3.PAIRED_SIGNAL, None))
        self.assertEqual(self.parse("02 b4 02").value, (v3.PARTNER_PICKED, 2))

    def test_reports(self):
        self.assertEqual(self.parse("ac 01 01 03").value, (3, 1, 1))
        self.assertEqual(self.parse("aa 78 56 34 12").value, "12345678")
        self.assertEqual(self.parse("ab 01 00 00 a0").kind, "device number")
        message = self.parse("ae 05000000 06000000")
        self.assertEqual((message.kind, message.value), ("health", (5, "SREQ")))
        self.assertEqual(self.parse("ae 00000000 00000100").value, (0, "OFF"))
        self.assertEqual(self.parse("af 0100 0200 0300").value, (1, 2, 3))
        self.assertEqual(self.parse("a1 15 01 02 03").value, (1, 2, 3))
        self.assertEqual(self.parse("09 50 10 0e").value, bytes.fromhex("50 10 0e"))
        self.assertEqual(self.parse("05 01").kind, "ignored")

    def test_acks(self):
        menu = self.parse("0a 45 01ff0000 0000ff00 020000ff").value
        self.assertEqual(menu[0], 0x45)
        self.assertEqual(menu[1][0], (1, (0xFF, 0, 0)))
        self.assertEqual(self.parse("0a 48 05 02").value, (0x48, (5, 2)))
        self.assertEqual(
            self.parse("0a 49 14 ff0000 05 ff00ff").value,
            (0x49, ((20, (0xFF, 0, 0)), (5, (0xFF, 0, 0xFF)))),
        )
        self.assertEqual(self.parse("0a 4a 03").value, (0x4A, 3))


class TouchTests(unittest.TestCase):
    def test_frames(self):
        samples = to_samples([1000, 250, 500])  # 20 + 5 + 10 samples
        frames = v3.touch_frames(samples, (0xFF, 0, 0), (0, 0, 0xFF), slot=2)
        self.assertEqual(len(frames), 3)
        self.assertEqual(
            frames[0], bytes.fromhex("02 23 02 ff0000 0000ff 00").ljust(20, b"\xff")
        )
        self.assertEqual(frames[1], b"\x35" * 20)
        self.assertEqual(frames[2], (b"\xff" * 5 + b"\x35" * 10).ljust(20, b"\xff"))
        with self.assertRaises(ValueError):
            v3.touch_frames(b"", (0, 0, 0))

    def test_assembler_round_trip(self):
        samples = to_samples([1000, 250, 500])
        assembler = v3.TouchAssembler()
        results = [
            assembler.feed(frame)
            for frame in v3.touch_frames(samples, (1, 2, 3), slot=3)
        ]
        self.assertEqual(results[:2], [None, None])
        self.assertEqual(results[2], v3.TouchSamples(slot=3, samples=samples))


if __name__ == "__main__":
    unittest.main()
