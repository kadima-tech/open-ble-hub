import unittest

from openble.lifesense.identify import classify, matches_scale, protocol_digit
from openble.lifesense.uuids import sig


class ClassifyTests(unittest.TestCase):
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
            matches_scale(
                "0DL87801",
                [],
                "D6E45925-525A-8D69-AA6B-B056E0BEA6EA",
                "d6e45925-525a-8d69-aa6b-b056e0bea6ea",
            )
        )
        self.assertFalse(
            matches_scale(
                "0DL87801",
                [sig("78d2")],
                "OTHER",
                "D6E45925-525A-8D69-AA6B-B056E0BEA6EA",
            )
        )

    def test_watch_takes_any_scale_when_no_address_is_requested(self):
        self.assertTrue(matches_scale("mystery", [sig("78d2")]))
        self.assertTrue(matches_scale("0DL87801", []))
        self.assertFalse(matches_scale("Headphones", [sig("180f")]))


class ProtocolDigitTests(unittest.TestCase):
    def test_digit_01_wins_over_02(self):
        self.assertEqual(protocol_digit([sig("78d2"), sig("7802").upper()]), "01")

    def test_fat_scale_services_are_02(self):
        self.assertEqual(protocol_digit([sig("180a"), sig("7892")]), "02")

    def test_unknown_table(self):
        self.assertEqual(protocol_digit([sig("180a")]), "")


if __name__ == "__main__":
    unittest.main()
