"""Per-sensor packets (protocol versions 1-2), with hand-packed bytes."""

import math
import unittest

from openble.muse import packets, uuids
from openble.muse.readings import EEG12_UV_PER_BIT, thermistor_c


def packet(counter: int, body: bytes) -> bytes:
    return counter.to_bytes(2, "big") + body.ljust(18, b"\x00")


class UnpackTests(unittest.TestCase):
    def test_u12_high_nibble_first(self):
        counter, values = packets.unpack_u12(packet(0x0102, bytes.fromhex("ab cd ef")))
        self.assertEqual(counter, 0x0102)
        self.assertEqual(values[:3], [0xABC, 0xDEF, 0])
        self.assertEqual(len(values), 12)

    def test_s16_u24_u32(self):
        body = bytes.fromhex("40 00 c0 00 ff ff")
        self.assertEqual(
            packets.unpack_s16(packet(0, body))[1][:3], [16384, -16384, -1]
        )
        body = bytes.fromhex("01 02 03 ff ff ff")
        self.assertEqual(
            packets.unpack_u24(packet(0, body))[1][:2], [0x010203, 0xFFFFFF]
        )
        self.assertEqual(packets.unpack_u32(packet(0, body))[1][0], 0x010203FF)

    def test_short_packet(self):
        with self.assertRaises(ValueError):
            packets.unpack_u12(bytes(19))


class DecodeTests(unittest.TestCase):
    def test_eeg_is_centred(self):
        # 0x800, 0x801 repeated: mid-scale and one step above.
        data = packet(7, bytes.fromhex("80 08 01") * 6)
        reading = packets.decode(uuids.SIGNAL_TP9.upper(), data)
        self.assertEqual((reading.kind, reading.channels), ("eeg", ("TP9",)))
        self.assertEqual(reading.sequence, 7)
        self.assertEqual(reading.samples[0], (0.0,))
        self.assertEqual(reading.samples[1], (EEG12_UV_PER_BIT,))
        self.assertEqual(reading.rate_hz, 256)

    def test_imu(self):
        body = bytes.fromhex("40 00 c0 00 00 00") + bytes(12)
        accel = packets.decode(uuids.ACCELEROMETER, packet(1, body))
        self.assertEqual(accel.samples[0], (1.0, -1.0, 0.0))
        self.assertEqual(len(accel.samples), 3)
        gyro = packets.decode(uuids.GYRO, packet(1, bytes.fromhex("00 64")))
        self.assertAlmostEqual(gyro.samples[0][0], -0.74768)

    def test_battery(self):
        body = (40960).to_bytes(2, "big") + (1900).to_bytes(2, "big")
        body += (500).to_bytes(2, "big") + (30).to_bytes(2, "big")
        reading = packets.decode(uuids.BATTERY, packet(9, body))
        self.assertEqual(reading.samples, ((80.0, 4180.0, 2200.0, 30.0),))

    def test_ppg_and_drl_ref(self):
        ppg = packets.decode(uuids.PPG_IR, packet(0, bytes.fromhex("01 02 03")))
        self.assertEqual((ppg.channels, ppg.samples[0]), (("infrared",), (66051.0,)))
        drl = packets.decode(uuids.DRL_REF, packet(0, bytes.fromhex("ab cd ef")))
        self.assertEqual(drl.samples[0], (0xABC, 0xDEF))
        self.assertEqual(len(drl.samples), 6)

    def test_thermistor(self):
        self.assertAlmostEqual(thermistor_c(2528), 25.0, delta=0.1)
        self.assertTrue(math.isnan(thermistor_c(0)))
        reading = packets.decode(uuids.THERMISTOR, packet(0, bytes(18)))
        self.assertEqual(len(reading.samples), 12)

    def test_not_covered(self):
        self.assertIsNone(packets.decode(uuids.MAGNETOMETER, packet(0, b"")))


if __name__ == "__main__":
    unittest.main()
