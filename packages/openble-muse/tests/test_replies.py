"""JSON reply reassembly and the version and status readers."""

import json
import unittest

from openble.muse.replies import (
    MuseError,
    Replies,
    check_protocol,
    parse_status,
    parse_version,
)

# Synthetic replies shaped like the keys MuseVersion and MuseConfiguration read.
VERSION = {
    "ap": "headset",
    "sp": "Blackcomb_revB",
    "tp": "consumer",
    "hw": "10.1",
    "bn": 27,
    "fw": "1.3.4",
    "bl": "1.0.1",
    "pv": 1,
    "rc": 0,
}
STATUS = {
    "hn": "Muse-1234",
    "sn": "4210-ABCD-1234",
    "ma": "00-55-da-b0-12-34",
    "id": "0x002d002a",
    "bp": 82,
    "ps": 33,
    "ts": 0,
    "rc": 0,
}


def chunks(reply: dict) -> list[bytes]:
    """20-byte notifications: a length byte, up to 19 characters, padding."""
    text = json.dumps(reply, separators=(",", ":")).encode("ascii")
    out = []
    for i in range(0, len(text), 19):
        part = text[i : i + 19]
        out.append(bytes((len(part),)) + part + b"\x00" * (19 - len(part)))
    return out


class RepliesTests(unittest.TestCase):
    def test_reassembles_across_notifications(self):
        replies = Replies()
        parts = chunks(VERSION)
        self.assertGreater(len(parts), 2)
        for part in parts[:-1]:
            self.assertIsNone(replies.feed(part))
        self.assertEqual(replies.feed(parts[-1]), VERSION)
        # The buffer is cleared for the next reply.
        self.assertEqual(replies.feed(chunks({"rc": 0})[0]), {"rc": 0})

    def test_length_byte_is_masked(self):
        self.assertEqual(Replies().feed(b"\xe8" + b'{"rc":0}'), {"rc": 0})


class VersionTests(unittest.TestCase):
    def test_fields(self):
        version = parse_version(VERSION)
        self.assertEqual(version.protocol, 1)
        self.assertEqual(version.firmware, "1.3.4")
        self.assertFalse(version.in_bootloader)
        self.assertTrue(parse_version({"rc": 0, "ap": "bootloader"}).in_bootloader)

    def test_no_return_code(self):
        with self.assertRaises(MuseError):
            parse_version({"pv": 1})

    def test_protocol_range(self):
        check_protocol(1)
        check_protocol(7)
        with self.assertRaisesRegex(MuseError, "firmware too old"):
            check_protocol(0)
        with self.assertRaisesRegex(MuseError, "library too old"):
            check_protocol(8)


class StatusTests(unittest.TestCase):
    def test_fields_and_model(self):
        status = parse_status(STATUS)
        self.assertEqual(status.name, "Muse-1234")
        self.assertEqual(status.battery_percent, 82.0)
        self.assertEqual(status.preset, "21")  # ps 33 = 0x21
        self.assertEqual(parse_status({**STATUS, "ps": 0x1045}).preset, "1045")
        self.assertEqual(status.model, "MU_03")

    def test_required_keys(self):
        with self.assertRaisesRegex(MuseError, "ma"):
            parse_status({key: v for key, v in STATUS.items() if key != "ma"})


if __name__ == "__main__":
    unittest.main()
