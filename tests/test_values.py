import unittest

from philips_ble.identify import classify, matches_scale
from philips_ble.uuids import cbt, sig
from philips_ble.values import interpret


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
    def test_sonicare_service_and_name(self):
        kinds, reasons = classify("Philips Sonicare", [cbt("0001")])
        self.assertEqual(kinds, ["toothbrush"])
        self.assertEqual(len(reasons), 2)

    def test_name_alone(self):
        kinds, _reasons = classify("Philips Sonicare", [])
        self.assertEqual(kinds, ["toothbrush"])

    def test_scale_service_digit(self):
        kinds, reasons = classify("unknown", [sig("7802").upper()])
        self.assertEqual(kinds, ["scale"])
        self.assertIn("digit 01", reasons[0])

    def test_other_ble_device_is_ignored(self):
        kinds, reasons = classify("Headphones", [sig("180f")])
        self.assertEqual(kinds, [])
        self.assertEqual(reasons, [])

    def test_watch_takes_the_requested_scale_address(self):
        self.assertTrue(
            matches_scale("0DL87801", [], "D6E45925-525A-8D69-AA6B-B056E0BEA6EA", "d6e45925-525a-8d69-aa6b-b056e0bea6ea")
        )
        self.assertFalse(matches_scale("0DL87801", [sig("78d2")], "OTHER", "D6E45925-525A-8D69-AA6B-B056E0BEA6EA"))

    def test_watch_takes_any_scale_when_no_address_is_requested(self):
        self.assertTrue(matches_scale("mystery", [sig("78d2")]))
        self.assertTrue(matches_scale("0DL87801", []))
        self.assertFalse(matches_scale("Headphones", [sig("180f")]))


if __name__ == "__main__":
    unittest.main()
