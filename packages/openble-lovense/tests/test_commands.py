"""Text command builders and the reply parsers."""

import unittest

from openble.lovense import commands
from openble.lovense.models import depth_level
from openble.lovense.replies import (
    is_binary,
    is_qcode,
    parse_battery,
    parse_capabilities,
    parse_device_type,
    qcode_reply,
    unknown_command,
)


class MotionTests(unittest.TestCase):
    def test_single_functions(self):
        self.assertEqual(commands.vibrate(10), b"Vibrate:10;")
        self.assertEqual(commands.vibrate(20, motor=2), b"Vibrate2:20;")
        self.assertEqual(commands.motion("p", 3), b"Air:Level:3;")
        self.assertEqual(commands.motion("s", 5), b"suck:5;")
        self.assertEqual(commands.motion("pos", 100), b"FSetSite:100;")
        self.assertEqual(commands.rotate(7, direction=False), b"Rotate:False:7;")

    def test_ranges(self):
        for letter, level in (("v", 21), ("p", 4), ("d", 4), ("v", -1)):
            with self.assertRaises(ValueError):
                commands.motion(letter, level)
        with self.assertRaises(TypeError):
            commands.vibrate(True)
        with self.assertRaises(ValueError):
            commands.air("In", 0)

    def test_stop_skips_position(self):
        self.assertEqual(
            commands.stop(["v1", "r", "pos"]), [b"Vibrate1:0;", b"Rotate:0;"]
        )

    def test_depth_mapping(self):
        self.assertEqual(
            [depth_level(n) for n in (0, 1, 7, 8, 14, 15, 20)], [0, 1, 1, 2, 2, 3, 3]
        )

    def test_stroke(self):
        self.assertEqual(commands.set_stroke(10, 90), b"SetStroke:10:90;")
        with self.assertRaises(ValueError):
            commands.set_stroke(50, 60)


class CombinedTests(unittest.TestCase):
    def test_mply_fits_one_write(self):
        self.assertEqual(commands.mply([20] * 5), b"Mply:20:20:20:20:20;")
        self.assertEqual(commands.mply([5, -1]), b"Mply:5:-1;")
        with self.assertRaises(ValueError):
            commands.mply([0] * 6)
        with self.assertRaises(ValueError):
            commands.multiply([0] * 4)

    def test_lvs_padding_and_sign(self):
        frame = commands.lvs([10, -5])
        self.assertEqual(frame, b"LVS:\x0a\x85;" + b"\xff" * 13)
        self.assertEqual(len(commands.lvs([0] * 15)), 20)
        with self.assertRaises(ValueError):
            commands.lvs([0] * 16)


class TextTests(unittest.TestCase):
    def test_write_limit(self):
        with self.assertRaises(ValueError):
            commands.text("Pl0", "1/2", "01234567890123")

    def test_rename(self):
        self.assertEqual(commands.rename("Bedroom 1"), b"CN:Bedroom 1;")
        for bad in ("", "x" * 13, "my-toy", "NewOne", "lvs2"):
            with self.assertRaises(ValueError):
                commands.rename(bad)

    def test_tags(self):
        tags, tag = [], 0
        for _ in range(130):
            tag = commands.next_tag(tag)
            tags.append(tag)
        self.assertEqual(tags[:9], [1, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertNotIn(0x0A, tags)
        self.assertNotIn(0x20, tags)
        self.assertNotIn(0, tags)
        self.assertLessEqual(max(tags), 127)
        self.assertEqual(commands.tag_command(b"GetTx;", b"\x05"), b"GetTx,\x05;")
        self.assertEqual(
            commands.tag_command(b"AutoTime:36000;", b"\x05"), b"AutoTime:36000,\x05;"
        )
        full = b"Pressure:5:12345678;"
        self.assertEqual(commands.tag_command(full, b"x"), full)
        self.assertEqual(commands.strip_tag(b"Tx:3,\x05;", b"\x05"), b"Tx:3;")
        self.assertEqual(commands.strip_tag(b"Tx:3;", b"\x05"), b"Tx:3;")


class ReplyTests(unittest.TestCase):
    def test_device_type(self):
        reply = parse_device_type(b"S:35:0082059ad3bd;")
        self.assertEqual((reply.model, reply.firmware), ("s", 35))
        self.assertEqual(reply.mac, "0082059AD3BD")
        self.assertIsNone(parse_device_type(b"85;"))

    def test_battery(self):
        self.assertEqual(parse_battery(b"85;"), 85)
        self.assertIsNone(parse_battery(b"s85;"))
        self.assertIsNone(parse_battery(b"OK;"))

    def test_live_max(self):
        # LVS-Max223 (firmware 223) on 2026-10-15.
        reply = parse_device_type(b"B:223:D6111451517F;")
        self.assertEqual((reply.model, reply.firmware), ("b", 223))
        self.assertEqual(parse_battery(b"78;"), 78)
        caps = parse_capabilities(b"CAP:\x1e\x00\x00\x00\x02vp;")
        self.assertEqual(caps.channels, ("v", "p"))
        self.assertEqual(caps.features, {"feedback", "long commands", "pin", "rename"})

    def test_live_max_tags_and_unknown(self):
        # LVS-Max223 echoed both tags and rejected Mply on 2026-10-15.
        for tag in (b"\x05", b"A"):
            sent = commands.tag_command(commands.BATTERY, tag)
            self.assertEqual(sent, b"Battery," + tag + b";")
            self.assertEqual(
                parse_battery(commands.strip_tag(b"78," + tag + b";", tag)), 78
            )
        self.assertEqual(unknown_command(b"unkown,Mply:3:-1;"), commands.mply([3, -1]))
        self.assertEqual(unknown_command(b"unkown,\xaa\x8b"), b"\xaa\x8b")
        self.assertIsNone(unknown_command(b"OK;"))
        self.assertEqual(
            commands.lvs([3, 0]), bytes.fromhex("4c 56 53 3a 03 00 3b") + b"\xff" * 13
        )

    def test_capabilities(self):
        reply = b"CAP:" + bytes((0b0000_0101, 0, 0, 0, 2)) + b"vr;"
        caps = parse_capabilities(reply)
        self.assertEqual(caps.channels, ("v", "r"))
        self.assertEqual(caps.features, {"program", "long commands"})
        self.assertIsNone(parse_capabilities(b"unkown,GetCap"))
        with self.assertRaises(ValueError):
            parse_capabilities(b"CAP:" + bytes((0, 0, 0, 0, 3)) + b"v;")

    def test_binary_or_text(self):
        self.assertTrue(is_binary(b"\xaa\x8b\x00\x70"))
        self.assertFalse(is_binary(b"85;"))


class QcodeTests(unittest.TestCase):
    def test_detect(self):
        self.assertTrue(is_qcode(b"$010102030405060708;"))
        self.assertFalse(is_qcode(b"$01010203040506070;"))
        self.assertFalse(is_qcode(b"\xff\x00"))

    def test_reply(self):
        # a=1 b=2 c=3 d=4: key = 3 ^ 12 ^ 7 ^ 4 = 12, so a -> d and b -> e.
        self.assertEqual(qcode_reply("$010102030405060708;"), "$01DE000005060708;")

    def test_reply_keeps_java_sign_extension(self):
        # a=0x80 is -128 as a Java byte; Integer.toHexString prints ffffff80.
        self.assertEqual(
            qcode_reply("$018000000005060708;"), "$01FFFFFF800000005060708;"
        )


if __name__ == "__main__":
    unittest.main()
