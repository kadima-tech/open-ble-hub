"""V3 (Bond More): ``ffb1`` commands and events, ``ffb2`` touch frames.

A write to ``ffb1`` is ``[type, payload…]`` with no padding
(WriteFFB1Command), written with response. Every V3 event arrives on
``ffb1`` too, with the type in byte 0.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from openble.bondtouch.colours import RGB, rgb
from openble.bondtouch.patterns import SAMPLE_IDLE
from openble.bondtouch.v2 import TOKEN_VALUE

FRAME_SIZE = 20

TOKEN = b"\x03" + TOKEN_VALUE
HELLO = b"\x01\x30"  # inferred: asks for the 0xAC firmware report
ENTER_DFU = b"\x01\x2a"
PAIRED_ACK = b"\x01\x31"
WAKE_GESTURE_ON = b"\x01\x43"
WAKE_GESTURE_OFF = b"\x01\x44"
READ_PARTNER_MENU = b"\x01\x45\x01"
LED_OFF = b"\x01\x4b\x01"
# Sent once on the first CONNECTED state. The app reads 2a19 between the
# last two. Which byte asks for which report is not proven.
CONNECT_BURST = (
    b"\x01\x19",
    b"\x01\x1b",
    b"\x01\x41",
    b"\x01\x42",
    b"\x01\x49\x01",  # battery warning settings, answered by ACK 0x49
    b"\x01\x1c",
)
TUTORIAL_MENU = (rgb("FFFF00"), rgb("007AFF"), rgb("FF2D55"))

# Menu entry ``active`` values.
INACTIVE, ACTIVE, IGNORE = 0, 1, 2

# Notification types (byte 0).
EVENT = 0x02
STATE = 0x04
BATTERY = 0x09
ACK = 0x0A
TOUCH_POSITION = 0xA1
LOT_NUMBER = 0xAA
DEVICE_NUMBER = 0xAB
FIRMWARE = 0xAC
HEALTH = 0xAE
FLASH_USAGE = 0xAF
ANCS = 0xB0

# 02 <event>
PAIRED_SIGNAL = 0x13
DOUBLE_TAP = 0xB2
PARTNER_PICKED = 0xB4  # 02 B4 <slot>: the wearer picked a partner on the bracelet

# 04 <state>
BOND_STATE_START = 0x01
WAITING_TOKEN = 0x82
WAITING_AUID = 0x83
OOBE = 0x84
CONNECTED = 0x85
MSG_RECORDING = 0x86
MSG_PLAYING = 0x87
MENU = 0x88
REPLY_MENU = 0x89
WAIT_FOR_ACT_PAIRED = 0x8A
WAIT_DOUBLE_TAP = 0x8D
TEST_COLORS = 0x8E
WAITING_START_AUTHENTICATION = 0x8F
STATES = {
    BOND_STATE_START: "BOND_STATE_START",
    WAITING_TOKEN: "WAITING_TOKEN",
    WAITING_AUID: "WAITING_AUID",
    OOBE: "OOBE",
    CONNECTED: "CONNECTED",
    MSG_RECORDING: "MSG_RECORDING",
    MSG_PLAYING: "MSG_PLAYING",
    MENU: "MENU",
    REPLY_MENU: "REPLY_MENU",
    WAIT_FOR_ACT_PAIRED: "WAIT_FOR_ACT_PAIRED",
    WAIT_DOUBLE_TAP: "WAIT_DOUBLE_TAP",
    TEST_COLORS: "TEST_COLORS",
    WAITING_START_AUTHENTICATION: "WAITING_START_AUTHENTICATION",
}
BUSY_STATES = frozenset({MSG_RECORDING, MSG_PLAYING, MENU, REPLY_MENU})

# Highest set bit of the 0xAE reason -> nRF51 reset cause.
RESET_CAUSES = {
    0: "RESETPIN",
    1: "DOG",
    2: "SREQ",
    3: "LOCKUP",
    16: "OFF",
    17: "LPCOMP",
    18: "DIF",
}


@dataclass(frozen=True)
class Message:
    """One ``ffb1`` notification.

    ``kind`` is ``event``, ``state``, ``battery``, ``ack``, ``touch position``,
    ``lot number``, ``device number``, ``firmware``, ``health``,
    ``flash usage``, ``ancs`` or ``ignored``. ``value`` depends on it:

    - event: ``(event, arg or None)``
    - state: the state byte
    - battery: the bytes after the type (layout still open)
    - ack: ``(command, value)``; see ``parse_ack``
    - touch position: ``(x, y, z)``
    - lot number, device number: hex text
    - firmware: ``(major, minor, patch)``
    - health: ``(resets, reset cause or None)``
    - flash usage: ``(factory, settings, status)``
    """

    kind: str
    value: Any
    raw: bytes


def parse(data: bytes) -> Message:
    data = bytes(data)
    if not data:
        raise ValueError("empty ffb1 notification")
    kind = data[0]
    body = data[1:]
    if kind == EVENT and body:
        return Message("event", (body[0], body[1] if len(body) > 1 else None), data)
    if kind == STATE and body:
        return Message("state", body[0], data)
    if kind == BATTERY:
        return Message("battery", body, data)
    if kind == ACK and body:
        return Message("ack", (body[0], parse_ack(body[0], body[1:])), data)
    if kind == TOUCH_POSITION and len(body) >= 4:
        return Message("touch position", tuple(body[1:4]), data)
    if kind in (LOT_NUMBER, DEVICE_NUMBER) and len(body) >= 4:
        name = "lot number" if kind == LOT_NUMBER else "device number"
        return Message(name, body[3::-1].hex().upper(), data)
    if kind == FIRMWARE and len(body) >= 3:
        patch, minor, major = body[:3]
        return Message("firmware", (major, minor, patch), data)
    if kind == HEALTH and len(body) >= 8:
        resets = int.from_bytes(body[0:4], "little")
        reason = int.from_bytes(body[4:8], "little")
        cause = RESET_CAUSES.get(reason.bit_length() - 1) if reason else None
        return Message("health", (resets, cause), data)
    if kind == FLASH_USAGE and len(body) >= 6:
        usage = tuple(int.from_bytes(body[i : i + 2], "little") for i in (0, 2, 4))
        return Message("flash usage", usage, data)
    if kind == ANCS:
        return Message("ancs", body, data)
    return Message("ignored", body, data)


def parse_ack(command: int, data: bytes) -> Any:
    """The value of ``0A <command> <data>``.

    - 0x45: the partner menu, three ``(active, (r, g, b))``
    - 0x48: ``(level, balance)`` vibration settings
    - 0x49: ``((low %, rgb), (critical %, rgb))`` battery warnings
    - 0x4A: accelerometer tap sensitivity
    - any other: the bytes
    """
    if command == 0x45 and len(data) >= 12:
        return tuple(
            (data[i], (data[i + 1], data[i + 2], data[i + 3])) for i in (0, 4, 8)
        )
    if command == 0x48 and len(data) >= 2:
        return (data[0], data[1])
    if command == 0x49 and len(data) >= 8:
        return ((data[0], tuple(data[1:4])), (data[4], tuple(data[5:8])))
    if command == 0x4A and data:
        return data[0]
    return bytes(data)


def auid(value: int) -> bytes:
    """``07 <auid low byte>``: V3 takes only the low byte of the AUID."""
    return bytes((0x07, value & 0xFF))


def show_colour(colour: RGB, first_led_only: bool = False) -> bytes:
    """``01 4B 00 <led> R G B``: led 0 lights all, 1 only the first."""
    return bytes((0x01, 0x4B, 0x00, int(first_led_only), *rgb(colour)))


def vibration_test(level: int, balance: int) -> bytes:
    return bytes((0x01, 0x48, 0x00, level, balance, 0x03))


def save_vibration(level: int, balance: int) -> bytes:
    return bytes((0x01, 0x48, 0x02, level, balance, 0x03))


def partner_menu(entries: Sequence[tuple[int, RGB]]) -> bytes:
    """``01 45 00`` + three ``[active, R, G, B]``. Missing entries are IGNORE."""
    if len(entries) > 3:
        raise ValueError("the menu has three slots")
    out = bytearray(b"\x01\x45\x00")
    padded = list(entries) + [(IGNORE, (0, 0, 0))] * (3 - len(entries))
    for active, colour in padded:
        if active not in (INACTIVE, ACTIVE, IGNORE):
            raise ValueError("active is 0 inactive, 1 active or 2 ignore")
        out += bytes((active, *rgb(colour)))
    return bytes(out)


def touch_frames(
    samples: bytes,
    start: RGB,
    end: RGB | None = None,
    slot: int = 1,
    flag: bool = False,
) -> list[bytes]:
    """The ``ffb2`` writes for a sample pattern (``patterns.to_samples``).

    A header ``slot, count, packets, R1 G1 B1, R2 G2 B2, flag`` and then
    ``packets`` frames of up to 20 samples, every frame padded with 0xFF.
    The app always sends ``flag`` 0; what it means is open.
    """
    if not 1 <= len(samples) <= 0xFF:
        raise ValueError("a message holds 1..255 samples")
    if slot not in (1, 2, 3):
        raise ValueError("slot is 1, 2 or 3")
    packets = -(-len(samples) // FRAME_SIZE)
    header = bytes(
        (slot, len(samples), packets, *rgb(start), *rgb(end or start), int(flag))
    )
    out = [_pad(header)]
    for offset in range(0, len(samples), FRAME_SIZE):
        out.append(_pad(samples[offset : offset + FRAME_SIZE]))
    return out


@dataclass(frozen=True)
class TouchSamples:
    slot: int
    samples: bytes  # leading and trailing 0xFF trimmed


class TouchAssembler:
    """Join ``ffb2`` notifications into one message.

    The bracelet sends a header ``[slot, count, packets, …]`` and then
    ``packets`` frames of 20 samples, as the app does.
    """

    def __init__(self) -> None:
        self._slot = 0
        self._left = 0
        self._samples = bytearray()

    def feed(self, data: bytes) -> TouchSamples | None:
        data = bytes(data)
        if self._left == 0:
            if len(data) < 3:
                raise ValueError(f"ffb2 header needs 3 bytes: {data.hex(' ')}")
            self._slot, self._left = data[0], data[2]
            self._samples = bytearray()
            return None
        self._samples += data
        self._left -= 1
        if self._left:
            return None
        trimmed = bytes(self._samples).strip(bytes((SAMPLE_IDLE,)))
        return TouchSamples(slot=self._slot, samples=trimmed)


def _pad(data: bytes) -> bytes:
    return bytes(data).ljust(FRAME_SIZE, bytes((SAMPLE_IDLE,)))
