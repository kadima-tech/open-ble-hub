import unittest

from openble.lovense.identify import classify, identity_of, parse_identity
from openble.lovense.uuids import swap_halves

BE_35 = "42450001-0023-4bd4-bbd5-a6920e4c5653"


class IdentityTests(unittest.TestCase):
    def test_manual_example(self):
        identity = parse_identity(BE_35.upper())
        self.assertEqual(identity.model, "be")
        self.assertEqual(identity.uuid_version, 35)
        self.assertFalse(identity.pin_set)

    def test_live_max(self):
        # LVS-Max223 on 2026-10-15; DeviceType; answered B:223:D6111451517F;
        identity = parse_identity("42300001-0023-4bd4-bbd5-a6920e4c5653")
        self.assertEqual((identity.model, identity.uuid_version), ("b", 0x23))
        kinds, reasons = classify(
            "LVS-Max223", ["42300001-0023-4bd4-bbd5-a6920e4c5653"]
        )
        self.assertEqual(kinds, ["toy"])
        self.assertEqual(
            reasons, ["service …-bbd5-a6920e4c5653 (model b)", "name LVS-Max223"]
        )

    def test_one_letter_code_and_pin(self):
        identity = parse_identity("53300011-0040-4bd4-bbd5-a6920e4c5653")
        self.assertEqual((identity.model, identity.uuid_version), ("s", 64))
        self.assertTrue(identity.pin_set)

    def test_other_uuid(self):
        self.assertIsNone(parse_identity("0000180f-0000-1000-8000-00805f9b34fb"))
        self.assertIsNone(parse_identity("zz450001-0023-4bd4-bbd5-a6920e4c5653"))

    def test_swapped_halves(self):
        swapped = swap_halves(BE_35)
        self.assertEqual(swapped, "bbd5a692-0e4c-5653-4245-000100234bd4")
        self.assertEqual(swap_halves(swapped), BE_35)
        self.assertEqual(identity_of([swapped]).model, "be")


class ClassifyTests(unittest.TestCase):
    def test_identity_service(self):
        kinds, reasons = classify("", [BE_35])
        self.assertEqual(kinds, ["toy"])
        self.assertIn("model be", reasons[0])

    def test_identity_in_app_half_order(self):
        kinds, _reasons = classify("", [swap_halves(BE_35)])
        self.assertEqual(kinds, ["toy"])

    def test_name_alone(self):
        kinds, reasons = classify("LVS-Lush42", [])
        self.assertEqual(kinds, ["toy"])
        self.assertEqual(reasons, ["name LVS-Lush42"])

    def test_bootloader_and_other_devices_are_ignored(self):
        for name in ("DfuTarg", "Headphones"):
            kinds, reasons = classify(name, ["0000180f-0000-1000-8000-00805f9b34fb"])
            self.assertEqual((kinds, reasons), ([], []))


if __name__ == "__main__":
    unittest.main()
