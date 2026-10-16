"""Universal v3 and BLE4 frames, built with independent packers."""

import unittest

from openble.muse import ble4, universal
from openble.muse.readings import EEG14_OFFSET_MUSE_RS, EEG14_UV_PER_BIT


def pack_lsb_first(values: list[int], bits: int, size: int) -> bytes:
    word = 0
    for i, value in enumerate(values):
        word |= value << (bits * i)
    return word.to_bytes(size, "little")


def subpacket(tag: int, seq: int, offset: int, payload: bytes) -> bytes:
    return bytes((tag, seq)) + offset.to_bytes(3, "little", signed=True) + payload


def frame(counter: int, clock: int, *subpackets: bytes) -> bytes:
    body = counter.to_bytes(2, "little") + clock.to_bytes(6, "little")
    body += b"".join(subpackets)
    return bytes((len(body) + 1,)) + body


class UniversalTests(unittest.TestCase):
    def test_unpack_by_hand(self):
        self.assertEqual(
            universal.unpack_u12_le(bytes.fromhex("bc fa de")), [0xABC, 0xDEF]
        )
        row = bytes.fromhex("45 23 a1 89 67 ef cd 0b")
        self.assertEqual(universal.unpack_ppg(row), [(0x12345, 0x6789A, 0xBCDEF)])

    def test_eeg_and_time_sync(self):
        eeg = bytes.fromhex("00 08 80") * 8  # sixteen 0x800 values
        sync = bytes((0x09, 0, 0, 0, 0)) + (123456).to_bytes(6, "little")
        sync += (7).to_bytes(2, "little") + b"\x01"
        data = frame(0, 42, subpacket(0x11, 5, -2, eeg), sync)
        parsed = universal.parse_frame(data)
        self.assertEqual(parsed.time, 42)
        self.assertEqual(parsed.unparsed, b"")
        (sub,) = parsed.subpackets
        self.assertEqual(
            (sub.kind, sub.rate_code, sub.sequence, sub.offset), (1, 1, 5, -2)
        )
        reading = universal.reading(sub)
        self.assertEqual(reading.channels, ("TP10", "AF8", "TP9", "AF7"))
        self.assertEqual(len(reading.samples), 4)
        self.assertEqual(reading.samples[0], (0.0, 0.0, 0.0, 0.0))
        self.assertEqual(reading.rate_hz, 256)
        self.assertEqual(parsed.time_syncs, (universal.TimeSync(123456, 7, True),))

    def test_imu_and_unknown_type(self):
        imu = b"".join(
            v.to_bytes(2, "little", signed=True) for v in (16384, 0, 0, 0, 0, 100)
        )
        data = frame(0, 0, subpacket(0x46, 1, 0, imu), b"\x0f\x00")
        parsed = universal.parse_frame(data)
        self.assertEqual(parsed.unparsed, b"\x0f\x00")
        row = universal.reading(parsed.subpackets[0]).samples[0]
        self.assertEqual(row[0], 1.0)
        self.assertAlmostEqual(row[5], -0.74768)

    def test_length_mismatch(self):
        with self.assertRaises(ValueError):
            universal.parse_frame(frame(0, 0) + b"\x00")


class Ble4Tests(unittest.TestCase):
    def test_unpack_lsb_first(self):
        self.assertEqual(
            ble4.unpack_lsb_first(bytes.fromhex("01 80 00 00"), 14), [1, 2]
        )
        values = list(range(0, 16000, 1000))
        self.assertEqual(
            ble4.unpack_lsb_first(pack_lsb_first(values, 14, 28), 14), values
        )

    def test_eeg8_is_sample_major(self):
        values = [8192 + n for n in range(16)]
        data = frame(
            0x0102, 0x0A0B0C, subpacket(0x12, 3, 10, pack_lsb_first(values, 14, 28))
        )
        (parsed,) = ble4.parse_notification(data)
        self.assertEqual((parsed.counter, parsed.clock), (0x0102, 0x0A0B0C))
        reading = ble4.reading(parsed.subpackets[0], eeg_offset=EEG14_OFFSET_MUSE_RS)
        self.assertEqual(reading.channels[:4], ("TP9", "AF7", "AF8", "TP10"))
        self.assertEqual(len(reading.samples), 2)
        self.assertEqual(reading.samples[1][0], 8 * EEG14_UV_PER_BIT)
        self.assertEqual(
            ble4.reading(parsed.subpackets[0]).samples[0][0], 8192 * EEG14_UV_PER_BIT
        )

    def test_imu_optics_battery(self):
        imu = b"".join(
            v.to_bytes(2, "little", signed=True) for v in [0, 0, 16384, 100, 0, 0] * 3
        )
        optics = pack_lsb_first([1, 0xFFFFF] + [0] * 10, 20, 30)
        battery = (80 * 256).to_bytes(2, "little") + bytes(18)
        data = frame(
            1,
            0,
            subpacket(0x47, 0, 0, imu),
            subpacket(0x34, 0, 0, optics),
            subpacket(0x98, 0, 0, battery),
        )
        kinds = {r.kind: r for r in ble4.readings(data)}
        self.assertEqual(kinds["imu"].samples[2][2], 1.0)
        self.assertAlmostEqual(kinds["imu"].samples[0][3], -0.74768)
        self.assertEqual(kinds["optics"].samples[0][:2], (1.0, 0xFFFFF))
        self.assertEqual(len(kinds["optics"].samples), 3)
        self.assertEqual(kinds["battery"].samples, ((80.0,),))
        self.assertEqual(kinds["battery"].rate_hz, 0.1)

    def test_0x88_battery_runs_to_the_end(self):
        payload = (50 * 256).to_bytes(2, "little") + bytes(186)
        (parsed,) = ble4.parse_notification(frame(0, 0, subpacket(0x88, 0, 0, payload)))
        self.assertEqual(len(parsed.subpackets[0].payload), 188)
        self.assertEqual(ble4.reading(parsed.subpackets[0]).samples, ((50.0,),))

    def test_two_frames_and_unknown_tag(self):
        battery = subpacket(0x98, 0, 0, bytes(20))
        first = frame(1, 0, battery, b"\x0a\x01\x02\x03\x04\x05")
        second = frame(2, 0, battery)
        frames = ble4.parse_notification(first + second)
        self.assertEqual([f.counter for f in frames], [1, 2])
        self.assertEqual(frames[0].unparsed, b"\x0a\x01\x02\x03\x04\x05")
        with self.assertRaises(ValueError):
            ble4.parse_notification(second[:-1])


if __name__ == "__main__":
    unittest.main()
