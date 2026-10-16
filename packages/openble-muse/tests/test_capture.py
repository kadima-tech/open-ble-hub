"""Per-sensor packets captured from a Muse S (MU_04, firmware 1.0.1, pv 1).

Taken on 2026-10-16 over bleak on macOS with preset 21. Each is packet
counter 5 of its characteristic, except battery (counter 0). The electrodes
were railing (raw 0 and 4095), so the EEG checks stop at the bytes.
"""

import math
import unittest

from openble.muse import packets, uuids

TP10 = bytes.fromhex("00 05 22 e0 00 66 a0 79 ef 04 8e 00 06 30 04 0f 7b 56 60 00")
ACCELEROMETER = bytes.fromhex(
    "00 05 18 69 05 b6 c4 20 18 23 05 8e c3 dc 18 29 05 83 c3 8b"
)
GYRO = bytes.fromhex("00 05 fe 07 ff b3 fd e1 fd ba 00 04 fe 96 fd 83 00 52 fe bd")
DRL_REF = bytes.fromhex("00 05 7d 47 b1 7d 27 b2 7d 67 b1 7d 47 b2 7d 57 b2 7d 87 b1")
BATTERY = bytes.fromhex("00 00 3c 00 05 81 00 00 00 00 00 00 00 00 00 00 00 00 00 00")


class CaptureTests(unittest.TestCase):
    def test_eeg_bytes(self):
        counter, raw = packets.unpack_u12(TP10)
        self.assertEqual(counter, 5)
        self.assertEqual(raw[:3], [0x22E, 0x000, 0x66A])
        self.assertEqual(packets.decode(uuids.SIGNAL_TP10, TP10).samples[1], (-1000.0,))

    def test_accelerometer_reads_one_g_at_rest(self):
        reading = packets.decode(uuids.ACCELEROMETER, ACCELEROMETER)
        for row in reading.samples:
            self.assertAlmostEqual(math.hypot(*row), 1.0, delta=0.03)

    def test_gyro_is_small_at_rest(self):
        reading = packets.decode(uuids.GYRO, GYRO)
        self.assertTrue(all(abs(v) < 10 for row in reading.samples for v in row))

    def test_drl_ref_pairs(self):
        reading = packets.decode(uuids.DRL_REF, DRL_REF)
        self.assertEqual(reading.samples[0], (2004.0, 1969.0))

    def test_battery(self):
        # The status reply on the same connection said bp 25.
        percent, gauge_mv, _adc, _temp = packets.decode(uuids.BATTERY, BATTERY).samples[
            0
        ]
        self.assertEqual(percent, 30.0)
        self.assertAlmostEqual(gauge_mv, 3099.8)


if __name__ == "__main__":
    unittest.main()
