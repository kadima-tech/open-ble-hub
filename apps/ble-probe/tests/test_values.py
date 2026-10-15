import unittest

from ble_probe.gatt import short_of
from ble_probe.session import classify
from ble_probe.values import interpret
from openble.lifesense.uuids import sig
from openble.sonicare.uuids import cbt


class ValueTests(unittest.TestCase):
    def test_utf8_stops_at_null(self):
        self.assertEqual(interpret("utf8", b"HX100\x00\xff")["text"], "HX100")

    def test_one_byte_battery_is_the_sig_level(self):
        parsed = interpret("battery", bytes([72]))
        self.assertEqual(parsed["level"], 72)

    def test_wider_battery_stays_unresolved(self):
        parsed = interpret("battery", b"\x01\x02")
        self.assertNotIn("level", parsed)
        self.assertEqual(parsed["unsigned_little_endian"], 0x0201)

    def test_int_shows_little_endian_as_a_display(self):
        parsed = interpret("int", b"\xe8\x03\x00\x00")
        self.assertEqual(parsed["unsigned_little_endian"], 1000)
        self.assertIn("Endianness", parsed["note"])


class ClassifyTests(unittest.TestCase):
    def test_both_libraries_are_asked(self):
        kinds, reasons = classify("Philips Sonicare", [cbt("0001"), sig("7802")])
        self.assertEqual(kinds, ["toothbrush", "scale"])
        self.assertEqual(len(reasons), 3)

    def test_other_ble_device_is_ignored(self):
        self.assertEqual(classify("Headphones", [sig("180f")]), ([], []))

    def test_short_of_knows_both_bases(self):
        self.assertEqual(short_of(sig("2A25")), "2a25")
        self.assertEqual(short_of(cbt("4010")), "4010")
        self.assertEqual(
            short_of("E50BA3C0-AF04-4564-92AD-FEF019489DE6"),
            "e50ba3c0-af04-4564-92ad-fef019489de6",
        )


if __name__ == "__main__":
    unittest.main()
