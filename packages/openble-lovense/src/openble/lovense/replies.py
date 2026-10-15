"""Parse what a toy sends back, and answer the ``$01`` QCode challenge.

Replies are notifications. A first byte of 0xAA is a binary frame (see
``frames``); anything else is text in the command style, e.g. ``85;``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEVICE_TYPE_RE = re.compile(rb"^(\w+):(\d+):([A-Za-z0-9]{12});?$")
BATTERY_RE = re.compile(rb"^(s?)(\d+);$")
QCODE_RE = re.compile(r"^\$01[0-9A-Fa-f]{16};$")
UNKNOWN = b"unkown,"  # spelling as in the firmware

# GetCap byte 4, bit -> feature (u6.a, ToyLvsInfoBean.parseLvsData).
CAP_FEATURES = (
    "program",
    "feedback",
    "long commands",
    "pin",
    "rename",
    "led",
    "silent update",
)


@dataclass(frozen=True)
class DeviceType:
    model: str  # lower case, as the app keys its catalogue
    firmware: int
    mac: str  # 12 hex digits, no colons


@dataclass(frozen=True)
class Capabilities:
    features: frozenset[str]
    channels: tuple[str, ...]  # one function letter per LVS channel, in order
    raw: bytes


def is_binary(data: bytes) -> bool:
    """True for a 0xAA frame, False for a text reply (i5.c$b.c)."""
    return data[:1] == b"\xaa"


def unknown_command(data: bytes) -> bytes | None:
    """The command echoed in ``unkown,<command>``, or None for any other reply.

    A Max echoes the whole command, ``;`` included (``unkown,Mply:3:-1;``),
    so a client can tell which command a toy lacks and fall back.
    """
    if data.startswith(UNKNOWN):
        return data[len(UNKNOWN) :]
    return None


def parse_device_type(data: bytes) -> DeviceType | None:
    """``s:35:0082059AD3BD;`` -> DeviceType, or None when it is not that shape."""
    match = DEVICE_TYPE_RE.match(data.strip())
    if not match:
        return None
    model, firmware, mac = (part.decode("ascii") for part in match.groups())
    return DeviceType(model=model.lower(), firmware=int(firmware), mac=mac.upper())


def parse_battery(data: bytes) -> int | None:
    """``85;`` -> 85. None for anything else, including ``s<n>;``.

    The meaning of the ``s`` form is still open, so it is not read as a level.
    """
    match = BATTERY_RE.match(data.strip())
    if not match or match.group(1):
        return None
    return int(match.group(2))


def parse_capabilities(data: bytes) -> Capabilities | None:
    """The ``GetCap;`` reply, or None when the toy answers ``unkown,GetCap``.

    Bytes 0..3 are ``CAP:``, byte 4 the feature bits, byte 8 the channel
    count, then one ASCII function letter per channel. Bytes 5..7 are unknown.
    """
    if not data.startswith(b"CAP:"):
        return None
    if len(data) < 9:
        raise ValueError(f"GetCap reply too short: {data.hex(' ')}")
    count = data[8]
    letters = data[9 : 9 + count]
    if len(letters) != count:
        raise ValueError(f"GetCap names {count} channels: {data.hex(' ')}")
    features = frozenset(
        name for bit, name in enumerate(CAP_FEATURES) if data[4] & (1 << bit)
    )
    return Capabilities(
        features=features, channels=tuple(letters.decode("ascii")), raw=bytes(data)
    )


def is_qcode(data: bytes) -> bool:
    """True for a ``$01`` + 16 hex digits + ``;`` challenge."""
    try:
        return bool(QCODE_RE.match(data.decode("ascii")))
    except UnicodeDecodeError:
        return False


def qcode_reply(challenge: str) -> str:
    """The app's answer to a QCode challenge (s7.b, r9.a.f).

    Copied with its quirks: Java signed bytes, and a hex step that neither
    zero-pads nor stops ``Integer.toHexString`` printing ``ffffffxx`` for a
    negative value, so the length of the reply varies.
    """
    if not QCODE_RE.match(challenge):
        raise ValueError(f"not a QCode challenge: {challenge!r}")
    a, b, c, d = (int(challenge[i : i + 2], 16) for i in (3, 5, 7, 9))
    rest = challenge[11:]  # 8 hex digits and ";"
    key = _signed((c ^ _signed((c * d) & 0xFF) ^ _signed((c + d) & 0xFF) ^ d) & 0xFF)
    return (
        "$01"
        + _java_hex(_signed(a) ^ key)
        + _java_hex(_signed(b) ^ key)
        + "0000"
        + rest
    ).upper()


def _signed(value: int) -> int:
    return value - 256 if value > 127 else value


def _java_hex(value: int) -> str:
    return format(value & 0xFFFFFFFF, "x")
