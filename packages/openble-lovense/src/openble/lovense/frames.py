"""0xAA binary frames ("long commands", CmdAA) with their CRC-8.

Builder command/code/a.java, parser t6.a, CRC com.component.dxtoy.utils.b.
The app sends these when GetCap sets bit 2 ("long commands") or its config
sets supportLanPattern. A Max with bit 2 set still read one as text and
answered ``unkown,``, so expect that too. There is no encryption, only the CRC.

    request:  AA | CMD | LEN | PAYLOAD[LEN]          | CRC8
    response: AA | CMD | STATUS | LEN | PARAMS[LEN] | CRC8

The CRC covers every byte before it. Multi-byte fields are little-endian.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

START = 0xAA
MAX_BODY = 248  # bytes after 0xAA in one request

LIGHT_RGB = 0x30
FEEDBACK_EVENT = 0x70
WRITE_PATTERN_JUST_20 = 0x80
WRITE_PATTERN_CLEAR_20 = 0x81
WRITE_PATTERN_CLEAR_RUN_20 = 0x82
WRITE_PATTERN_JUST_100 = 0x85
WRITE_PATTERN_CLEAR_100 = 0x86
WRITE_PATTERN_CLEAR_RUN_100 = 0x87
PLAY_PATTERN_ACTION = 0x8A
READ_PATTERN_STATUS = 0x8B
SET_PATTERN_SPEED = 0x8C
SET_PATTERN_PROGRAM = 0x8D
PATTERN_PROGRAM_CONTROL = 0x8E
WRITE_PATTERN_JUST_100_2 = 0x90
WRITE_PATTERN_CLEAR_100_2 = 0x91
WRITE_PATTERN_CLEAR_RUN_100_2 = 0x92
WIFI = 0x93

# Commands whose reply echoes a sub-command byte as well as CMD.
SUB_COMMANDS = frozenset({LIGHT_RGB, FEEDBACK_EVENT, PATTERN_PROGRAM_CONTROL, WIFI})

# Payload of PLAY_PATTERN_ACTION.
PATTERN_STOP, PATTERN_PAUSE, PATTERN_PLAY, PATTERN_END = 0, 1, 2, 3

STATUS = {
    0x00: "success",
    0x01: "bad command",
    0x02: "bad parameter",
    0x03: "command not supported",
    0x04: "crc error",
    0x05: "flash write error",
    0x20: "funscript queue full",
    0x21: "funscript needs more data",
    0x22: "funscript queue empty",
    0x2F: "funscript unknown",
    0x30: "queue empty",
    0x80: "unknown",
}


@dataclass(frozen=True)
class Response:
    command: int
    status: int
    params: bytes

    @property
    def ok(self) -> bool:
        return self.status == 0x00

    @property
    def status_text(self) -> str:
        return STATUS.get(self.status, f"status 0x{self.status:02x}")


def crc8(data: bytes) -> int:
    """CRC-8, poly 0xB1 reflected (0x8D), init 0, xorout 0x35. check = 0xD4."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8D if crc & 1 else crc >> 1
    return crc ^ 0x35


def request(command: int, payload: bytes = b"") -> bytes:
    """``AA CMD LEN PAYLOAD CRC``, sent as one write without response."""
    if not 0 <= command <= 0xFF:
        raise ValueError("command is one byte")
    if 2 + len(payload) + 1 > MAX_BODY:
        raise ValueError(f"at most {MAX_BODY} bytes follow 0xAA")
    body = bytes((START, command, len(payload))) + payload
    return body + bytes((crc8(body),))


def parse_response(data: bytes) -> Response:
    """Check the start byte, length and CRC of a toy's frame and split it."""
    data = bytes(data)
    if len(data) < 5 or data[0] != START:
        raise ValueError(f"not an AA response: {data.hex(' ')}")
    length = data[3]
    if len(data) != length + 5:
        raise ValueError(f"LEN {length} needs {length + 5} bytes: {data.hex(' ')}")
    if crc8(data[:-1]) != data[-1]:
        raise ValueError(f"CRC mismatch: {data.hex(' ')}")
    return Response(command=data[1], status=data[2], params=data[4:-1])


def play_pattern_action(action: int) -> bytes:
    """0x8A: stop, pause, play or end the stored pattern (PATTERN_* constants)."""
    if action not in (PATTERN_STOP, PATTERN_PAUSE, PATTERN_PLAY, PATTERN_END):
        raise ValueError("action is 0 stop, 1 pause, 2 play or 3 end")
    return request(PLAY_PATTERN_ACTION, bytes((action,)))


def read_pattern_status() -> bytes:
    """0x8B with an empty payload. The reply reads with pattern_status."""
    return request(READ_PATTERN_STATUS)


def wifi_status() -> bytes:
    """0x93 sub-command 0, which needs no server token."""
    return request(WIFI, b"\x00")


def pattern_status(response: Response) -> tuple[int, int]:
    """``(free space, time index)`` of a pattern write ack or 0x8B reply.

    Frame bytes 5..6 are the free space (u16 LE) and 7..9 the time index
    (18 bits LE), i.e. params 1..2 and 3..5.
    """
    params = response.params
    if len(params) < 6:
        raise ValueError(f"pattern status needs 6 params, got {params.hex(' ')}")
    free = int.from_bytes(params[1:3], "little")
    index = int.from_bytes(params[3:6], "little") & 0x3FFFF
    return free, index


def pattern_points_20(points: Iterable[tuple[int, int]]) -> bytes:
    """3-byte points for the ``_20`` writes: 18-bit index, level 0..20.

    ``idx[7:0], idx[15:8], (idx[17:16] << 6) | level``. The rest of the
    0x80..0x82 payload is not recorded in the manual.
    """
    out = bytearray()
    for index, level in points:
        if not 0 <= index < 1 << 18 or not 0 <= level <= 20:
            raise ValueError("index is 18 bits and level 0..20")
        out += bytes((index & 0xFF, (index >> 8) & 0xFF, (index >> 16) << 6 | level))
    return bytes(out)


def pattern_points_100(points: Iterable[tuple[int, int]]) -> bytes:
    """4-byte points for the ``_100`` and ``_100_2`` writes: u24 LE index, level 0..100."""
    out = bytearray()
    for index, level in points:
        if not 0 <= index < 1 << 24 or not 0 <= level <= 100:
            raise ValueError("index is 24 bits and level 0..100")
        out += index.to_bytes(3, "little") + bytes((level,))
    return bytes(out)
