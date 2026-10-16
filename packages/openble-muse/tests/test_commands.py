"""Command framing and builders, against the manual's examples."""

import unittest

from openble.muse import commands


class EncodeTests(unittest.TestCase):
    def test_manual_example(self):
        self.assertEqual(commands.encode("s"), bytes.fromhex("02 73 0a"))

    def test_start_streaming(self):
        self.assertEqual(commands.start_streaming(), "dc001")
        self.assertEqual(commands.encode("dc001"), b"\x06dc001\n")

    def test_length_limit(self):
        commands.encode("x" * 18)
        with self.assertRaises(ValueError):
            commands.encode("x" * 19)


class BuilderTests(unittest.TestCase):
    def test_version_is_hex(self):
        self.assertEqual(commands.version(), "v7")
        self.assertEqual(commands.version(10), "va")
        with self.assertRaises(ValueError):
            commands.version(16)

    def test_preset(self):
        self.assertEqual(commands.preset("21"), "p21")
        self.assertEqual(commands.preset("102a"), "p102A")
        self.assertEqual(commands.preset("1045"), "p1045")
        with self.assertRaises(ValueError):
            commands.preset("99")

    def test_fire_and_forget(self):
        self.assertFalse(commands.expects_reply(commands.led(True)))
        self.assertFalse(commands.expects_reply(commands.clock_sync(1, 0)))
        self.assertTrue(commands.expects_reply(commands.HALT))

    def test_clock_sync(self):
        command = commands.clock_sync(3, 0x0192F3A4B5C6)
        self.assertEqual(command, "Q3 C,0192f3a4b5c6")
        commands.encode(command)
        with self.assertRaises(ValueError):
            commands.clock_sync(3, 1 << 48)


if __name__ == "__main__":
    unittest.main()
