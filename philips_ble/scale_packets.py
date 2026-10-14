"""Lifesense weight-packet parsers.

Layouts follow docs/lifesense-scale-protocol.md section 6. Multi-byte numbers
are little-endian. The phone rewrites the kilogram value to one decimal place
and derives pounds and stones from that. Body-composition fields use the
16-bit decimal float in section 6.1.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
EPOCH = datetime(2010, 1, 1, tzinfo=SHANGHAI)

IMPEDANCE_NAMES = {
    0: "IDLE",
    1: "PROCESSING",
    2: "SHOES",
    3: "BAREFOOT",
    4: "FINISH",
    5: "ERROR",
}

A2_UNITS = {0x00: "Kg", 0x20: "LB", 0x40: "St", 0x60: "Kg"}
A3_UNITS = {0: "Kg", 1: "lb", 2: "St"}


class ShortPacket(Exception):
    def __init__(self, message: str, parsed: dict):
        super().__init__(message)
        self.parsed = parsed


def _num(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _one_decimal(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
    return format(rounded, "f")


def decode_u24_scaled(chunk: bytes) -> Decimal:
    """c/f.m: uint24 little-endian times 10 to a signed exponent byte."""
    if len(chunk) != 4:
        raise ValueError("scaled value is 4 bytes")
    magnitude = chunk[0] | (chunk[1] << 8) | (chunk[2] << 16)
    exponent = chunk[3] if chunk[3] < 128 else chunk[3] - 256
    return Decimal(magnitude) * (Decimal(10) ** exponent)


def decode_composition(chunk: bytes) -> Decimal:
    """c/f.n: 16-bit decimal float.

    Bits 12-15 are the exponent nibble. Bit 15 selects the transform
    exponent = -(((nibble - 1) ^ -1) & 0x0F). With bit 15 clear, the nibble
    itself is the exponent. Bit 11 clear keeps the 12-bit mantissa. Bit 11
    set negates the 11-bit two's-complement mantissa.
    """
    if len(chunk) != 2:
        raise ValueError("composition value is 2 bytes")
    uint16 = chunk[0] | (chunk[1] << 8)
    nibble = (uint16 >> 12) & 0x0F
    if uint16 & 0x8000:
        exponent = -(((nibble - 1) ^ -1) & 0x0F)
    else:
        exponent = nibble
    if uint16 & 0x0800:
        raw = uint16 & 0x07FF
        signed = raw - 0x800 if raw & 0x400 else raw
        mantissa = -signed
    else:
        mantissa = uint16 & 0x0FFF
    return Decimal(mantissa) * (Decimal(10) ** exponent)


def _u32(chunk: bytes) -> int:
    return chunk[0] | (chunk[1] << 8) | (chunk[2] << 16) | (chunk[3] << 24)


def format_date(seconds: int) -> str:
    moment = EPOCH + timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _lb_and_st(kg: Decimal) -> dict:
    """Phone-side conversion from section 6.2.

    n is the one-decimal kilogram value times 10. Pounds are
    ((n * 11023 + 5000) // 10000) * 2 * 0.1. The integer division is what
    produces the manual's factor of about 2.2046. Stones are that pound
    value split by 14.
    """
    rounded = kg.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
    n = int(rounded * 10)
    pounds = Decimal((n * 11023 + 5000) // 10000) * Decimal("0.2")
    section = int(pounds) // 14
    remainder = pounds - (Decimal(section) * 14)
    remainder = remainder.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    return {
        "weight_kg": _one_decimal(kg),
        "weight_kg_exact": _num(kg),
        "lb": _num(pounds),
        "st_section": section,
        "st_remainder": _num(remainder),
    }


def _finish(parsed: dict, data: bytes, cursor: int) -> dict:
    parsed["raw"] = data.hex(" ")
    if cursor < len(data):
        parsed["trailing_hex"] = data[cursor:].hex(" ")
    return parsed


def _guard(parse, data: bytes) -> dict:
    try:
        return parse(data)
    except ShortPacket as exc:
        body = dict(exc.parsed)
        body["error"] = str(exc)
        body["raw"] = data.hex(" ")
        return body


class _Cursor:
    def __init__(self, data: bytes, parsed: dict, start: int):
        self.data = data
        self.parsed = parsed
        self.cursor = start

    def take(self, width: int) -> bytes:
        end = self.cursor + width
        if end > len(self.data):
            raise ShortPacket(
                f"need {width} bytes at offset {self.cursor}, packet length is {len(self.data)}",
                self.parsed,
            )
        chunk = self.data[self.cursor : end]
        self.cursor = end
        return chunk


def _status(parsed: dict, status: int, *, accuracy: bool) -> None:
    bit0 = status & 0x01
    impedance = (status >> 1) & 0x07
    parsed["status_byte"] = status
    parsed["weight_status"] = "WEIGHT STABLE" if bit0 else "WEIGHT UNSTABLE"
    parsed["impedance_status"] = IMPEDANCE_NAMES.get(impedance, str(impedance))
    parsed["has_append_measurement"] = bool(status & 0x10)
    if accuracy:
        parsed["accuracy_status"] = (
            "0.1LB division" if status & 0x20 else "0.2LB division"
        )


def _parse_a2_weight(data: bytes) -> dict:
    parsed: dict = {"packet": "a2-weight"}
    if len(data) < 5:
        raise ShortPacket("A2 weight packet is shorter than 5 bytes", parsed)
    flag = data[0]
    parsed["flag"] = flag
    kg = decode_u24_scaled(data[1:5])
    parsed.update(_lb_and_st(kg))
    parsed["unit"] = A2_UNITS[flag & 0x60]
    cur = _Cursor(data, parsed, 5)
    if flag & 0x01:
        seconds = _u32(cur.take(4))
        parsed["utc_seconds"] = seconds
        parsed["date"] = format_date(seconds)
    if flag & 0x02:
        parsed["resistance_1"] = _num(decode_u24_scaled(cur.take(4)))
    if flag & 0x04:
        parsed["resistance_2"] = _num(decode_u24_scaled(cur.take(4)))
    if flag & 0x08:
        parsed["user_no"] = cur.take(1)[0]
    if flag & 0x10:
        _status(parsed, cur.take(1)[0], accuracy=False)
    if flag & 0x80:
        parsed["flag_0x80"] = "not read by the A2 weight parser"
    return _finish(parsed, data, cur.cursor)


def _parse_a2_fat(data: bytes) -> dict:
    parsed: dict = {"packet": "a2-fat"}
    if len(data) < 5:
        raise ShortPacket("A2 fat packet is shorter than 5 bytes", parsed)
    flag = data[0]
    parsed["flag"] = flag
    # Bytes 1-4 are read into a local the next instruction overwrites.
    cur = _Cursor(data, parsed, 5)
    if flag & 0x01:
        parsed["user_no"] = cur.take(1)[0]
    if flag & 0x02:
        parsed["basal_metabolism"] = _num(decode_composition(cur.take(2)))
    if flag & 0x04:
        parsed["body_fat_ratio"] = _num(decode_composition(cur.take(2)))
    if flag & 0x08:
        parsed["body_water_ratio"] = _num(decode_composition(cur.take(2)))
    if flag & 0x10:
        parsed["visceral_fat_level"] = _num(decode_composition(cur.take(2)))
    if flag & 0x20:
        parsed["muscle_mass_ratio"] = _num(decode_composition(cur.take(2)))
    if flag & 0x40:
        parsed["bone_density"] = _num(decode_composition(cur.take(2)))
    if flag & 0x80:
        byte = cur.take(1)[0]
        parsed["battery"] = byte & 0x07
        if byte & 0x08:
            nxt = cur.take(1)[0]
            voltage = (((byte >> 7) & 1) * 4096 + ((byte >> 6) & 1) * 256 + nxt) / 100
            parsed["voltage"] = _num(Decimal(str(voltage)))
    return _finish(parsed, data, cur.cursor)


def _parse_a3_weight(data: bytes) -> dict:
    parsed: dict = {"packet": "a3-weight"}
    if len(data) < 5:
        raise ShortPacket("A3 weight packet is shorter than 5 bytes", parsed)
    flag = data[0]
    parsed["flag"] = flag
    kg = decode_u24_scaled(data[1:5])
    parsed.update(_lb_and_st(kg))
    unit_code = (flag & 0x60) >> 5
    parsed["unit"] = A3_UNITS.get(unit_code, f"code {unit_code}")
    cur = _Cursor(data, parsed, 5)
    if flag & 0x01:
        seconds = _u32(cur.take(4))
        parsed["utc_seconds"] = seconds
        parsed["date"] = format_date(seconds)
    if flag & 0x02:
        parsed["weight_difference"] = _num(decode_u24_scaled(cur.take(4)))
    if flag & 0x04:
        parsed["impedance"] = _num(decode_u24_scaled(cur.take(4)))
    if flag & 0x08:
        parsed["user_id"] = cur.take(1)[0]
    if flag & 0x10:
        _status(parsed, cur.take(1)[0], accuracy=True)
    if flag & 0x80:
        parsed["flag_0x80"] = "not read by the A3 weight parser"
    return _finish(parsed, data, cur.cursor)


def _parse_a3_append(data: bytes) -> dict:
    parsed: dict = {"packet": "a3-append"}
    if len(data) < 5:
        raise ShortPacket("A3 append packet is shorter than 5 bytes", parsed)
    flag = data[0]
    parsed["flag"] = flag
    parsed["utc_seconds"] = _u32(data[1:5])
    parsed["date"] = format_date(parsed["utc_seconds"])
    cur = _Cursor(data, parsed, 5)
    if flag & 0x01:
        parsed["user_id"] = cur.take(1)[0]
    if flag & 0x02:
        parsed["basal_metabolism"] = _num(decode_composition(cur.take(2)))
    if flag & 0x04:
        parsed["body_fat_ratio"] = _num(decode_composition(cur.take(2)))
    if flag & 0x08:
        parsed["body_water_ratio"] = _num(decode_composition(cur.take(2)))
    if flag & 0x10:
        parsed["visceral_fat_level"] = _num(decode_composition(cur.take(2)))
    if flag & 0x20:
        parsed["muscle_mass_ratio"] = _num(decode_composition(cur.take(2)))
    if flag & 0x40:
        parsed["bone_density"] = _num(decode_composition(cur.take(2)))
    if flag & 0x80:
        parsed["battery"] = cur.take(1)[0]
    return _finish(parsed, data, cur.cursor)


def parse_a2_weight(data: bytes) -> dict:
    return _guard(_parse_a2_weight, data)


def parse_a2_fat(data: bytes) -> dict:
    return _guard(_parse_a2_fat, data)


def parse_a3_weight(data: bytes) -> dict:
    return _guard(_parse_a3_weight, data)


def parse_a3_append(data: bytes) -> dict:
    return _guard(_parse_a3_append, data)


def parse_scale_notification(
    short: str, data: bytes, *, family: str, previous: dict | None
) -> dict:
    """Pick the parser the Lifesense dispatcher uses for this characteristic.

    family is the protocol digit from the advertised service ("01", "02", or "").
    previous is the last parsed packet from this connection, used when 8A22 can
    be either an A2 fat packet or an A3 append packet.
    """
    key = short.lower()
    if key == "8a21":
        parsed = parse_a2_weight(data)
        if family == "02":
            parsed["note"] = (
                "Digit 02 GENERIC_FAT feeds this packet to the A2 weight parser. "
                "The phone then applies body-composition polynomials from a user profile. "
                "Those coefficients are not BLE fields, so they are left unapplied."
            )
        return parsed
    if key == "8a24":
        return parse_a3_weight(data)
    if key == "8a22":
        kind = (previous or {}).get("packet")
        if kind == "a2-weight" and previous.get("has_append_measurement"):
            return parse_a2_fat(data)
        if kind == "a3-weight" and previous.get("has_append_measurement"):
            return parse_a3_append(data)
        if family == "01":
            return parse_a2_fat(data)
        if family == "02" and kind == "a3-weight":
            return parse_a3_append(data)
        return {
            "packet": "8a22",
            "raw": data.hex(" "),
            "a2_fat": parse_a2_fat(data),
            "a3_append": parse_a3_append(data),
            "note": "8A22 is the A2 fat characteristic and the A3 append characteristic. Both parses are shown.",
        }
    if key == "a402":
        return {
            "packet": "a4",
            "raw": data.hex(" "),
            "note": "A402 notifications are enabled by the scale app. The byte layout is unresolved.",
        }
    return {"packet": key, "raw": data.hex(" ")}
