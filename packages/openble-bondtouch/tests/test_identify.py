"""UUIDs, advertisement matching and generation detection."""

import unittest

from openble.bondtouch import uuids
from openble.bondtouch.identify import (
    MINI,
    V1,
    V2,
    V3,
    V4,
    classify,
    generation_of,
    is_v3,
    missing,
    needs_update,
    parse_firmware,
    v1_firmware,
)


class UuidTests(unittest.TestCase):
    def test_manual_spellings(self):
        # The fourth group differs per characteristic; these are copied from
        # the manual's characteristics table.
        self.assertEqual(uuids.API_VERSION, "d3c0ff10-add3-1d4b-0000-0000b5006bb1")
        self.assertEqual(uuids.BATTERY, "d3c0ff06-add3-1d4b-0000-0000b5006bb1")
        self.assertEqual(uuids.TOKEN, "d3c0ffa1-add3-1d4b-0001-0000b5006bb1")
        self.assertEqual(uuids.COMMAND, "d3c0ffa6-add3-1d4b-0001-0000b5006bb1")
        self.assertEqual(uuids.BOND_TRIGGER, "d3c0ffa8-add3-1d4b-0001-0000b5006bb1")
        self.assertEqual(uuids.V3_COMMAND, "d3c0ffb1-add3-1d4b-0000-0000b5006bb1")
        self.assertEqual(uuids.CONTROL_SERVICE, "d3c00002-add3-1d4b-0001-0000b5006bb1")
        self.assertEqual(uuids.V3_SERVICE, "d3c00003-add3-1d4b-0000-0000b5006bb1")
        self.assertEqual(
            uuids.FIRMWARE_REVISION, "00002a26-0000-1000-8000-00805f9b34fb"
        )


class ClassifyTests(unittest.TestCase):
    def test_names(self):
        for name in ("BOND", "Bond More", "BOND 4", "BOND MINI"):
            self.assertEqual(classify(name, []), (["bracelet"], [f"name {name}"]))

    def test_bootloader(self):
        kinds, reasons = classify("BOND_4_DFU", [])
        self.assertEqual(kinds, ["bracelet-dfu"])
        self.assertEqual(reasons, ["name BOND_4_DFU (bootloader)"])

    def test_service_uuid(self):
        kinds, reasons = classify("", [uuids.CONTROL_SERVICE.upper()])
        self.assertEqual(kinds, ["bracelet"])
        self.assertEqual(reasons, [f"service {uuids.CONTROL_SERVICE}"])

    def test_other_devices(self):
        for name in ("bond", "BONDING", "Headphones", ""):
            kinds, reasons = classify(name, ["0000180f-0000-1000-8000-00805f9b34fb"])
            self.assertEqual((kinds, reasons), ([], []))


class GenerationTests(unittest.TestCase):
    def test_api_version(self):
        self.assertEqual(generation_of(b"\x42"), V2)
        self.assertEqual(generation_of(0x44), V4)
        self.assertEqual(generation_of(bytearray(b"\x45\x00")), MINI)
        self.assertEqual(generation_of(b"\x01"), V1)
        with self.assertRaises(ValueError):
            generation_of(b"")

    def test_v3_service(self):
        self.assertTrue(is_v3([uuids.INFO_SERVICE, uuids.V3_SERVICE.upper()]))
        self.assertFalse(is_v3([uuids.INFO_SERVICE, uuids.CONTROL_SERVICE]))

    def test_missing(self):
        present = [uuids.BATTERY, uuids.TOKEN, uuids.AUID, uuids.STATE, uuids.EVENT]
        self.assertEqual(
            missing(V4, [uuid.upper() for uuid in present]),
            [uuids.COMMAND, uuids.FIRMWARE_REVISION],
        )
        self.assertEqual(missing(V3, [uuids.V3_COMMAND, uuids.V3_TOUCH]), [])

    def test_firmware(self):
        self.assertEqual(parse_firmware(b"2.7.9\x00"), (2, 7, 9))
        self.assertEqual(parse_firmware("v2.0.3"), (2, 0, 3))
        self.assertEqual(v1_firmware(bytes((96, 2))), (1, 2, 96))
        self.assertTrue(needs_update(V2, (2, 5, 0)))
        self.assertFalse(needs_update(V2, (2, 7, 9)))
        self.assertFalse(needs_update(V4, (2, 1, 0)))
        with self.assertRaises(ValueError):
            parse_firmware("abc")


if __name__ == "__main__":
    unittest.main()
