import unittest

from openble.sonicare.identify import classify
from openble.sonicare.uuids import CONDOR_SCAN_SERVICE, cbt, cbt_suffix


class ClassifyTests(unittest.TestCase):
    def test_sonicare_service_and_name(self):
        kinds, reasons = classify("Philips Sonicare", [cbt("0001")])
        self.assertEqual(kinds, ["toothbrush"])
        self.assertEqual(len(reasons), 2)

    def test_name_alone(self):
        kinds, _reasons = classify("Philips Sonicare", [])
        self.assertEqual(kinds, ["toothbrush"])

    def test_condor_service(self):
        kinds, _reasons = classify("", [CONDOR_SCAN_SERVICE.upper()])
        self.assertEqual(kinds, ["toothbrush-condor"])

    def test_other_ble_device_is_ignored(self):
        kinds, reasons = classify(
            "Headphones", ["0000180f-0000-1000-8000-00805f9b34fb"]
        )
        self.assertEqual(kinds, [])
        self.assertEqual(reasons, [])


class UuidTests(unittest.TestCase):
    def test_suffix_round_trip(self):
        self.assertEqual(cbt_suffix(cbt("40D0").upper()), "40d0")

    def test_suffix_of_other_uuid(self):
        self.assertIsNone(cbt_suffix("0000180f-0000-1000-8000-00805f9b34fb"))


if __name__ == "__main__":
    unittest.main()
