"""V1 (the original Bond Touch): state, events, results and ``ffa6`` commands.

A V1 command is ``[cmdId u16, seq u16, payload]`` (WriteFF06Command). ``seq``
is a 16-bit counter, reset on each connection, that matches each command to
its ``ffa7`` result. A write is done only when that result arrives.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from openble.bondtouch.colours import RGB, rgb
from openble.bondtouch.patterns import round_ms

PAIRED_ACK = b"\x31"  # one byte to ffa6, the answer to PAIRED_SIGNAL

# ffa4: [bondState, pairedState, charging]
OOBE_OFF = 0x83
OOBE_ON = 0x84
WAITING_AUID = 0xF4
IDLE = 0xF6  # connected and ready for commands
BUSY = 0xF7  # recording or playing; the app pauses its queue for 30 s

# ffa5 event ids (AppEvent), the same numbers as V2.
AUID_RIGHT = 0x11
AUID_ERROR = 0x12
PAIRED_SIGNAL = 0x13
SEND_MSG = 0x14
END = 0xFFFF  # touchCount of the event that ends a message
TIMEOUT = 0xFFFE  # touchCount of a message ended by timeout

# Command ids.
COLOUR = 0x0021
ENTER_DFU = 0x0025
LIGHT_STEP = 0x0026
CONFIG = 0x0027
REBOOT = 0x0029
SAVE_CONFIG_KEY = 1000
TOUCH_COLOUR_KEY = 1003
LED_ID_KEY = 1006

# ffa7 results.
RESULTS = {
    0: "ACR_NULL",
    1: "ACR_SUCCESS",
    2: "ACR_FAIL",
    3: "ACR_PARAM_ERROR",
    4: "ACR_RES_NULL",
    5: "ACR_RES_UNENOUGH",
    6: "ACR_NUM_OVERFLOW",
    7: "ACR_ROUTING_ERROR",
    8: "ACR_HARDWARD_ERROR",
    9: "ACR_AUTH_ERROR",
    10: "ACR_TIMEOUT",
    11: "ACR_BUSY",
    12: "ACR_MAX",
}
SUCCESS = 1
BUSY_RESULT = 11  # after 10 in a row the app sends REBOOT

# V1 has 11 fixed LED colours (BleColorTable). ledId -> bracelet colour.
LED_COLOURS: dict[int, RGB] = {
    0: rgb("FF0000"),
    1: rgb("00EEF9"),
    2: rgb("000FF9"),
    3: rgb("BA00F9"),
    4: rgb("F9002D"),
    5: rgb("07F900"),
    6: rgb("61F900"),
    7: rgb("F9F500"),
    8: rgb("F94300"),
    9: rgb("FFFFFF"),
    10: rgb("000000"),
}
# The app's palette colours -> ledId. Anything else falls back to 1.
APP_COLOURS: dict[RGB, int] = {
    rgb("FF0000"): 0,
    rgb("23E0E8"): 1,
    rgb("106DED"): 2,
    rgb("BE5BFF"): 3,
    rgb("A502C0"): 3,
    rgb("FF44A6"): 4,
    rgb("03AB55"): 5,
    rgb("7BBE2F"): 6,
    rgb("E8D726"): 7,
    rgb("FF7931"): 8,
    rgb("FFFFFF"): 9,
    rgb("000000"): 10,
}
FALLBACK_LED = 1


@dataclass(frozen=True)
class State:
    bond_state: int
    paired_state: int
    charging: bool


@dataclass(frozen=True)
class Event:
    """``ffa5``: ``[id u8, counter u8, touchCount u16, touchTimeMs u16]``."""

    event_id: int
    counter: int
    touch_count: int
    touch_ms: int


@dataclass(frozen=True)
class Result:
    """``ffa7``: ``[result u16, seq u16]``."""

    result: int
    seq: int

    @property
    def ok(self) -> bool:
        return self.result == SUCCESS

    @property
    def name(self) -> str:
        return RESULTS.get(self.result, f"result {self.result}")


def parse_state(data: bytes) -> State:
    padded = bytes(data).ljust(3, b"\x00")
    return State(padded[0], padded[1], bool(padded[2]))


def parse_event(data: bytes) -> Event:
    padded = bytes(data).ljust(6, b"\x00")
    return Event(
        event_id=padded[0],
        counter=padded[1],
        touch_count=int.from_bytes(padded[2:4], "little"),
        touch_ms=int.from_bytes(padded[4:6], "little"),
    )


def parse_result(data: bytes) -> Result:
    if len(data) < 4:
        raise ValueError(f"ffa7 needs 4 bytes: {bytes(data).hex(' ')}")
    return Result(
        int.from_bytes(data[0:2], "little"), int.from_bytes(data[2:4], "little")
    )


def battery_percent(data: bytes) -> int:
    """``ff06`` millivolts (u16 LE) -> percent: 3.7 V is 0 and 4.1 V is 100."""
    if len(data) < 2:
        raise ValueError(f"ff06 needs 2 bytes on V1: {bytes(data).hex(' ')}")
    millivolts = int.from_bytes(data[0:2], "little")
    return min(max(millivolts - 3700, 0), 400) * 100 // 400


class TouchRecorder:
    """Join ``SEND_MSG`` events into a pattern.

    V1 reports presses but not gaps; the app works each gap out from the
    phone's arrival times. Pass the time each notification arrived, in
    seconds (``time.monotonic()``).
    """

    def __init__(self) -> None:
        self._presses: list[tuple[int, float]] = []  # (ms, arrival seconds)

    def feed(self, event: Event, arrival: float) -> tuple[int, ...] | None:
        """Take one event; return the pattern when the message ends."""
        if event.event_id != SEND_MSG:
            return None
        if event.touch_count in (END, TIMEOUT):
            presses, self._presses = self._presses, []
            return _pattern(presses) if presses else None
        if event.touch_count == 1:
            self._presses = []
        self._presses.append((event.touch_ms, arrival))
        return None


def _pattern(presses: list[tuple[int, float]]) -> tuple[int, ...]:
    out = [round_ms(presses[0][0])]
    for (_ms, arrival), (next_ms, next_arrival) in pairwise(presses):
        gap = round((next_arrival - arrival) * 1000) - next_ms
        out += [round_ms(gap if gap >= 0 else 100), round_ms(next_ms)]
    return tuple(out)


def command(command_id: int, payload: bytes, length: int, seq: int = 0) -> bytes:
    """``[cmdId u16, seq u16, payload]`` padded with zeros to ``length``."""
    out = command_id.to_bytes(2, "little") + _seq(seq) + payload
    if len(out) > length:
        raise ValueError(f"{len(out)} bytes do not fit a {length}-byte command")
    return out.ljust(length, b"\x00")


def with_seq(frame: bytes, seq: int) -> bytes:
    """The same command with another ``seq`` (bytes 2..3)."""
    if len(frame) < 4:
        return frame  # PAIRED_ACK has no header
    return frame[:2] + _seq(seq) + frame[4:]


def seq_of(frame: bytes) -> int | None:
    return int.from_bytes(frame[2:4], "little") if len(frame) >= 4 else None


def colour(value: RGB, seq: int = 0) -> bytes:
    """0x0021: the ARGB int as u32 LE with byte 7 set to 100, so ``B G R 64``."""
    red, green, blue = rgb(value)
    return command(COLOUR, bytes((blue, green, red, 100)), 16, seq)


def enter_dfu(seq: int = 0) -> bytes:
    return command(ENTER_DFU, b"\xff\xff\xff\xff", 8, seq)


def reboot(seq: int = 0) -> bytes:
    return command(REBOOT, b"\xff\xff\xff\xff", 8, seq)


def set_config(key: int, value: int, seq: int = 0) -> bytes:
    """0x0027: ``key u32, value u32``."""
    return command(
        CONFIG, key.to_bytes(4, "little") + value.to_bytes(4, "little"), 16, seq
    )


def save_config(seq: int = 0) -> bytes:
    return command(CONFIG, SAVE_CONFIG_KEY.to_bytes(4, "little"), 8, seq)


def light_step(
    led_id: int,
    mode: int,
    phase: int,
    level: int | None = None,
    time: int | None = None,
    seq: int = 0,
) -> bytes:
    """0x0026: ``ledId, mode, phase, 0x01, level u16, time u16``.

    The end step leaves out level and time. What ``mode``, ``phase`` and the
    time unit mean is still open; ``play_pattern`` copies the app.
    """
    payload = bytes((led_id, mode, phase, 0x01))
    if level is not None and time is not None:
        payload += level.to_bytes(2, "little") + time.to_bytes(2, "little")
    return command(LIGHT_STEP, payload, 16, seq)


def led_id_for(value: RGB) -> int:
    """The ledId the app maps a palette colour to, else 1."""
    return APP_COLOURS.get(rgb(value), FALLBACK_LED)


def touch_colour(value: RGB) -> list[bytes]:
    """Set the wearer's colour: config 1003 = RGB, 1006 = ledId, then save (mo4104f)."""
    red, green, blue = rgb(value)
    return [
        set_config(TOUCH_COLOUR_KEY, red << 16 | green << 8 | blue),
        set_config(LED_ID_KEY, led_id_for(value)),
        save_config(),
    ]


def play_pattern(pattern: Sequence[int], led_id: int) -> list[bytes]:
    """Play a pattern (mo4105g): one step per duration, then the end step.

    ``mode`` alternates 2, 1, 2, … from the first press. ``time`` is
    ``max(ms, 100) * 10 / steps``, where ``steps`` is 30 for red (ledId 0)
    and 100 otherwise. The app halves it for mode 4, which no step here uses.
    """
    if led_id not in LED_COLOURS:
        raise ValueError("ledId is 0..10")
    steps = 30 if led_id == 0 else 100
    out = []
    for index, ms in enumerate(pattern):
        mode = 1 if index % 2 else 2
        time = max(ms, 100) * 10 // steps
        out.append(light_step(led_id, mode, 1, 100, time))
    out.append(light_step(led_id, 2, 2))
    return out


def _seq(seq: int) -> bytes:
    return (seq & 0xFFFF).to_bytes(2, "little")
