"""Serial numbers, capability sets and advertisement matching."""

import unittest

from openble.muse import identify, models, uuids


class ModelTests(unittest.TestCase):
    def test_model_from_serial(self):
        cases = {
            "2031-…": "MU_02",
            "4210-…": "MU_03",
            "4310-…": "MU_06",
            "5031-…": "MU_04",
            "6001-…": "MU_05",
            "7001-…": "MS_03",
            "3001-…": "GL_01",
            "9001-…": "AMHL_01",
        }
        for serial, model in cases.items():
            self.assertEqual(models.model_from_serial(serial), model, serial)
        with self.assertRaises(ValueError):
            models.model_from_serial("8001")

    def test_characteristics(self):
        self.assertEqual(len(models.characteristics("MU_02", 1)), 10)
        self.assertEqual(len(models.characteristics("MU_03", 1)), 13)
        muse_s = models.characteristics("MU_04", 2)
        self.assertEqual(len(muse_s), 14)
        self.assertIn(uuids.THERMISTOR, muse_s)
        self.assertNotIn(uuids.SERIAL, muse_s)
        self.assertEqual(
            models.characteristics("MS_03", 4), (uuids.UNIVERSAL, uuids.MUSE_DEBUG)
        )
        self.assertIn(uuids.TIME_SYNC, models.characteristics("MS_03", 5))
        with self.assertRaises(ValueError):
            models.characteristics("MU_01", 1)

    def test_defaults_and_layout(self):
        self.assertEqual(models.default_preset("MU_04"), "21")
        self.assertEqual(models.default_preset("MS_03"), "1021")
        self.assertEqual(
            [models.layout(pv) for pv in (1, 2, 3, 4, 7)],
            ["per-sensor", "per-sensor", "universal", "ble4", "ble4"],
        )


class UuidTests(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(uuids.SERIAL, "273e0001-4c4d-454d-96be-f03bac821358")
        self.assertEqual(uuids.suffix_of(uuids.TIME_SYNC.upper()), 0x15)
        self.assertIsNone(uuids.suffix_of(uuids.SERVICE))


class IdentifyTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(
            identify.classify("", [uuids.SERVICE.upper()]),
            (["headband"], ["service fe8d"]),
        )
        self.assertEqual(identify.classify("Muse-1A2B", [])[0], ["headband"])
        self.assertEqual(identify.classify("Lush", []), ([], []))

    def test_generation_and_fallback_name(self):
        self.assertEqual(identify.generation({0x1234: b"\x00\x07"}), "athena")
        self.assertIsNone(identify.generation({0x1234: b"\x00\x02"}))
        self.assertIsNone(identify.generation({}))
        self.assertEqual(identify.fallback_name("00:55:DA:B0:1a:2b"), "Muse-1A2B")
        self.assertEqual(
            identify.fallback_name("00:55:DA:B0:1A:2B", "athena"), "MuseS-1A2B"
        )


if __name__ == "__main__":
    unittest.main()
