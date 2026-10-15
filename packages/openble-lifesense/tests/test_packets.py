"""Parser checks against the worked layouts in the scale manual, section 6."""

from __future__ import annotations

import unittest
from decimal import Decimal

from openble.lifesense.packets import (
    decode_composition,
    decode_u24_scaled,
    parse_a2_fat,
    parse_a2_weight,
    parse_a3_append,
    parse_a3_weight,
    parse_scale_notification,
)


def _scaled(magnitude: int, exponent: int) -> bytes:
    return bytes(
        (
            magnitude & 0xFF,
            (magnitude >> 8) & 0xFF,
            (magnitude >> 16) & 0xFF,
            exponent & 0xFF,
        )
    )


class NumberTests(unittest.TestCase):
    def test_weight_hundredths(self):
        # 7000 * 10^-2 = 70. The exponent byte 0xFE is the manual's example.
        self.assertEqual(decode_u24_scaled(bytes.fromhex("58 1b 00 fe")), Decimal(70))

    def test_composition_positive_exponent(self):
        # Nibble 2, bit 15 clear, mantissa 100 -> 100 * 10^2.
        self.assertEqual(decode_composition(bytes.fromhex("64 20")), Decimal(10000))

    def test_composition_transformed_exponent(self):
        # Nibble 0xF selects exponent -1. Mantissa 255. Value 25.5.
        self.assertEqual(decode_composition(bytes.fromhex("ff f0")), Decimal("25.5"))

    def test_composition_negative_mantissa(self):
        # Bit 11 set, low 11 bits = 1, exponent nibble 0 -> -1.
        self.assertEqual(decode_composition(bytes.fromhex("01 08")), Decimal(-1))


class PacketTests(unittest.TestCase):
    def test_a2_weight_all_presence_bits(self):
        # Section 6.7, flag 0x1F. Status: stable, barefoot, append.
        packet = bytearray(b"\x1f")
        packet += _scaled(7000, -2)
        packet += (1000).to_bytes(4, "little")
        packet += _scaled(500, -1)
        packet += _scaled(2500, -2)
        packet.append(2)
        packet.append(0x17)
        parsed = parse_a2_weight(bytes(packet))
        self.assertNotIn("error", parsed)
        self.assertEqual(parsed["weight_kg"], "70.0")
        self.assertEqual(parsed["lb"], "154.4")
        self.assertEqual(parsed["st_section"], 11)
        self.assertEqual(parsed["st_remainder"], "0.4")
        self.assertEqual(parsed["unit"], "Kg")
        self.assertEqual(parsed["date"], "2010-01-01 00:16:40")
        self.assertEqual(parsed["resistance_1"], "50")
        self.assertEqual(parsed["resistance_2"], "25")
        self.assertEqual(parsed["user_no"], 2)
        self.assertEqual(parsed["weight_status"], "WEIGHT STABLE")
        self.assertEqual(parsed["impedance_status"], "BAREFOOT")
        self.assertTrue(parsed["has_append_measurement"])
        self.assertNotIn("trailing_hex", parsed)

    def test_a2_unit_bits_add_no_bytes(self):
        packet = b"\x20" + _scaled(7000, -2)
        parsed = parse_a2_weight(packet)
        self.assertEqual(parsed["unit"], "LB")
        self.assertEqual(parsed["weight_kg"], "70.0")
        self.assertNotIn("trailing_hex", parsed)

    def test_a2_fat_layout(self):
        packet = bytearray(b"\x7f\x01\x02\x03\x04\x02")
        packet += (1500).to_bytes(2, "little")
        packet += bytes.fromhex("ff f0")  # 25.5
        packet += (1).to_bytes(2, "little")
        packet += (2).to_bytes(2, "little")
        packet += (3).to_bytes(2, "little")
        packet += (4).to_bytes(2, "little")
        parsed = parse_a2_fat(bytes(packet))
        self.assertNotIn("error", parsed)
        self.assertEqual(parsed["user_no"], 2)
        self.assertEqual(parsed["basal_metabolism"], "1500")
        self.assertEqual(parsed["body_fat_ratio"], "25.5")
        self.assertEqual(parsed["bone_density"], "4")
        self.assertNotIn("battery", parsed)

    def test_a2_fat_battery_and_voltage(self):
        packet = bytearray(b"\x80") + _scaled(0, 0) + bytes((0x0B, 0x64))
        parsed = parse_a2_fat(bytes(packet))
        self.assertEqual(parsed["battery"], 3)
        self.assertEqual(parsed["voltage"], "1")

    def test_a3_weight_and_append(self):
        packet = bytearray(b"\x3f")
        packet += _scaled(7000, -2)
        packet += (1000).to_bytes(4, "little")
        packet += _scaled(100, 0)
        packet += _scaled(200, 0)
        packet.append(4)
        packet.append(0x29)
        parsed = parse_a3_weight(bytes(packet))
        self.assertEqual(parsed["unit"], "lb")
        self.assertEqual(parsed["user_id"], 4)
        self.assertEqual(parsed["weight_status"], "WEIGHT STABLE")
        self.assertEqual(parsed["impedance_status"], "FINISH")
        self.assertEqual(parsed["accuracy_status"], "0.1LB division")
        self.assertFalse(parsed["has_append_measurement"])
        self.assertEqual(parsed["weight_difference"], "100")
        self.assertEqual(parsed["impedance"], "200")

        append = bytearray(b"\xff")
        append += (1000).to_bytes(4, "little")
        append.append(1)
        for value in (10, 11, 12, 13, 14, 15):
            append += value.to_bytes(2, "little")
        append.append(80)
        fat = parse_a3_append(bytes(append))
        self.assertEqual(fat["date"], "2010-01-01 00:16:40")
        self.assertEqual(fat["user_id"], 1)
        self.assertEqual(fat["basal_metabolism"], "10")
        self.assertEqual(fat["battery"], 80)
        self.assertNotIn("voltage", fat)

    def test_short_packet_keeps_partial_fields(self):
        parsed = parse_a2_weight(b"\x01" + _scaled(7000, -2))
        self.assertIn("error", parsed)
        self.assertEqual(parsed["weight_kg"], "70.0")

    def test_8a22_follows_the_weight_that_asked_for_it(self):
        weight = parse_scale_notification(
            "8a21", b"\x00" + _scaled(7000, -2), family="01", previous=None
        )
        weight["has_append_measurement"] = True
        fat = parse_scale_notification(
            "8a22", b"\x00\x00\x00\x00\x00", family="", previous=weight
        )
        self.assertEqual(fat["packet"], "a2-fat")

        both = parse_scale_notification(
            "8a22", b"\x00\x00\x00\x00\x00", family="", previous=None
        )
        self.assertIn("a2_fat", both)
        self.assertIn("a3_append", both)


if __name__ == "__main__":
    unittest.main()
