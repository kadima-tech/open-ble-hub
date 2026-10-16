"""Millisecond patterns, the V3 sample form, and colours."""

import unittest

from openble.bondtouch.colours import argb, blend, rgb
from openble.bondtouch.patterns import (
    MAX_SAMPLES,
    from_samples,
    normalise,
    round_ms,
    steps,
    to_samples,
)

T, I = b"\x35", b"\xff"


class PatternTests(unittest.TestCase):
    def test_rounding(self):
        self.assertEqual(
            [round_ms(n) for n in (0, 24, 25, 74, 75, 480)], [50, 50, 50, 50, 100, 500]
        )
        self.assertEqual(normalise([480, 260, 10]), (500, 250, 50))
        with self.assertRaises(ValueError):
            normalise([100, 100])
        with self.assertRaises(ValueError):
            round_ms(-1)

    def test_steps(self):
        self.assertEqual(steps([400, 200, 300]), [(400, 200), (300, 0)])

    def test_samples(self):
        self.assertEqual(to_samples([100, 150, 50]), T * 2 + I * 3 + T)
        self.assertEqual(from_samples(I + T * 2 + I * 3 + T + I * 4), (100, 150, 50))
        # Anything but 0xFF is touching.
        self.assertEqual(from_samples(b"\x01\x35\xff\x10"), (100, 50, 50))
        self.assertEqual(from_samples(I * 3), ())

    def test_long_pattern_is_squeezed(self):
        samples = to_samples([10000, 5000, 5000])  # 20 s -> 100 ms a sample
        self.assertEqual(len(samples), MAX_SAMPLES)
        self.assertEqual(from_samples(samples, period_ms=100), (10000, 5000, 5000))


class ColourTests(unittest.TestCase):
    def test_forms(self):
        for value in ("#23E0E8", "23e0e8", 0x23E0E8, (0x23, 0xE0, 0xE8)):
            self.assertEqual(rgb(value), (0x23, 0xE0, 0xE8))
        for bad in ("23E0E", 0x1000000, (256, 0, 0)):
            with self.assertRaises(ValueError):
                rgb(bad)

    def test_argb_and_blend(self):
        self.assertEqual(argb((0x23, 0xE0, 0xE8)), 0xFF23E0E8)
        self.assertEqual(argb((0xFF, 0, 0), alpha=0), 0x00FF0000)
        self.assertEqual(blend((0, 0, 0), (200, 100, 50), 0.5), (100, 50, 25))
        self.assertEqual(blend((0, 0, 0), (200, 100, 50), 2), (200, 100, 50))


if __name__ == "__main__":
    unittest.main()
