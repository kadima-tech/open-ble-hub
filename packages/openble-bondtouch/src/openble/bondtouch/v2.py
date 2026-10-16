"""V2, V4 and Mini: state, events, touch recording and the ``ffa6`` frames.

The three share BleBondManagerV2Base. Every command on ``ffa6`` is padded with
zeros to 20 bytes and byte 1 is always 0x00. Integers are little-endian,
except config colours, the OUID and the breathe timings, which are
big-endian (BleAppCommandHelperKt).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from openble.bondtouch.colours import BLACK, RGB, argb, blend
from openble.bondtouch.identify import MINI, V2, V4
from openble.bondtouch.patterns import MIN_MS, MINI_PATTERN, steps

FRAME_SIZE = 20
TOKEN_VALUE = b"12345678"  # the same for every bracelet

# ffa4 bond states (v2/BondState).
NO_STATE = 0x00
WAITING_TOKEN = 0x82
WAITING_AUID = 0x83
OOBE = 0x84
CONNECTED = 0x85
MSG = 0x86  # recording or playing
FACTORY = 0x87
QUEUE_EXECUTING = 0x88
BOND_STATES = {
    NO_STATE: "NO_STATE",
    WAITING_TOKEN: "WAITING_TOKEN",
    WAITING_AUID: "WAITING_AUID",
    OOBE: "OOBE",
    CONNECTED: "CONNECTED",
    MSG: "MSG",
    FACTORY: "FACTORY",
    QUEUE_EXECUTING: "QUEUE_EXECUTING",
}
CHARGING_STATES = {0: "not charging", 1: "charging", 2: "full", 0xFF: "error"}

# ffa5 event ids (AppEvent).
AUID_RIGHT = 0x11
AUID_ERROR = 0x12
PAIRED_SIGNAL = 0x13
SEND_MSG = 0x14
SEND_MSG_TIMEOUT = 0x15
TAP_DETECTED = 0x16
DOUBLE_TAP = 0x17
SHIP_MODE = 0x19  # with 14 bytes or more: a ship-mode report, layout open
EVENTS = {
    AUID_RIGHT: "AUID_RIGHT",
    AUID_ERROR: "AUID_ERROR",
    PAIRED_SIGNAL: "PAIRED_SIGNAL",
    SEND_MSG: "SEND_MSG",
    SEND_MSG_TIMEOUT: "SEND_MSG_TIMEOUT",
    TAP_DETECTED: "TAP_DETECTED_SIGNAL",
    DOUBLE_TAP: "NO_ACTION_DOUBLE_TAP_DETECTED",
    SHIP_MODE: "SHIP_MODE",
}
LAST_PRESS = 0xFFFFFFFF  # the ``stop`` field of the last press of a pattern

# 0x26 LED modes, inferred from how the app uses them.
MODE_SOLID, MODE_BREATHE, MODE_OFF = 1, 2, 4
BRIGHTNESS = 80  # the app always uses this
UNTIL_CHANGED = 0xFFFF  # total step time: keep it on until the next command
BLEND_FRAME_MS = 200  # 0x33 frame length during a two-colour press

# Vibration strengths the app's setting allows (VibrationHelper); anything
# else becomes DEFAULT_STRENGTH.
STRENGTHS = (28, 33, 40, 58, 60, 73, 80, 88, 100)
DEFAULT_STRENGTH = 80

# 0x27 config properties.
OUID = 0x11
TOKEN = 0x12
MAX_TOUCH_COUNT = 0x13
MIN_TOUCH_DURATION = 0x14
MAX_TOUCH_DURATION = 0x15
MESSAGE_TIMEOUT = 0x16
LOW_BAT_THRESHOLD = 0x17
MOTOR_STRENGTH = 0x18
BLE_PARAMS = 0x19
LOW_BAT_COLOR = 0x21
OOBE_COLOR = 0x22
OOBE_PAIRED_COLOR = 0x23
DOUBLE_TAP_COLOR = 0x24  # V2. On V4 and Mini the same id sets a partner-menu entry
USER_MENU = 0x24
TOUCH_COLOR = 0x25
TOUCH_WARNING_COLOR = 0x26
ERROR_COLOR = 0x27
CHARGING_COLOR = 0x28
CHARGE_DONE_COLOR = 0x29
ACCEL_SENSITIVITY = 0x30
DISCONNECTED_PARAM = 0x31
ANCS_PARAM = 0x33
FACTORY_MODE = 0x35
SELECTED_USER = 0x37
RESET_CONFIG = 0xEF  # factory reset; the app reconnects 3 s later


@dataclass(frozen=True)
class State:
    """``ffa4``: ``[bondState, chargingState, ledBusy, motorBusy, touchBusy]``."""

    bond_state: int
    charging: int
    led_busy: bool
    motor_busy: bool
    touch_busy: bool  # the wearer is touching now

    @property
    def name(self) -> str:
        return BOND_STATES.get(self.bond_state, f"0x{self.bond_state:02x}")


@dataclass(frozen=True)
class Event:
    """``ffa5``: ``[id, counter, touchMs u32, releaseMs u32, stop u32, slot]``.

    ``release_ms`` is the gap before this press. ``slot`` is the V4 partner
    slot from byte 14, None on V2 and Mini. A ship-mode report keeps only
    ``raw``.
    """

    event_id: int
    counter: int
    touch_ms: int
    release_ms: int
    stop: int
    slot: int | None
    raw: bytes

    @property
    def name(self) -> str:
        return EVENTS.get(self.event_id, f"0x{self.event_id:02x}")

    @property
    def last(self) -> bool:
        return self.stop == LAST_PRESS


@dataclass(frozen=True)
class TouchMessage:
    """A recorded touch pattern and the partner slot it is for (1 unless V4 says)."""

    pattern: tuple[int, ...]
    slot: int = 1


def parse_state(data: bytes) -> State:
    data = bytes(data)
    if len(data) < 1:
        raise ValueError("empty ffa4 state")
    padded = data.ljust(5, b"\x00")
    return State(
        bond_state=padded[0],
        charging=padded[1],
        led_busy=bool(padded[2]),
        motor_busy=bool(padded[3]),
        touch_busy=bool(padded[4]),
    )


def parse_event(data: bytes, generation: str = V2) -> Event:
    """Read one ``ffa5`` notification. Missing trailing fields read as 0."""
    data = bytes(data)
    if len(data) < 1:
        raise ValueError("empty ffa5 event")
    if data[0] == SHIP_MODE and len(data) >= 14:
        return Event(SHIP_MODE, 0, 0, 0, 0, None, data)
    padded = data.ljust(15, b"\x00")
    slot = None
    if generation == V4:
        slot = padded[14] if padded[14] in (1, 2, 3) else 1
    return Event(
        event_id=padded[0],
        counter=padded[1],
        touch_ms=int.from_bytes(padded[2:6], "little"),
        release_ms=int.from_bytes(padded[6:10], "little"),
        stop=int.from_bytes(padded[10:14], "little"),
        slot=slot,
        raw=data,
    )


def battery_percent(data: bytes) -> int:
    """``ff06`` on V2, V4 and Mini: ``[percent, reserved]``."""
    if len(data) < 1:
        raise ValueError("empty ff06 battery value")
    return data[0]


class TouchRecorder:
    """Join ``SEND_MSG`` events into a pattern, as each manager's mo4212P does.

    Each event is one press. Counter 1 starts a pattern; later events add the
    gap before the press and the press. The pattern ends with the press whose
    ``stop`` is 0xFFFFFFFF, or with a ``SEND_MSG_TIMEOUT``: one with counter 0
    discards the pattern, any other delivers it. A V2 on firmware 2.6.4 ended
    every live touch with a timeout. A Mini's touch is always MINI_PATTERN.
    """

    def __init__(self, generation: str = V2) -> None:
        self.generation = generation
        self._pattern: list[int] = []
        self._slot = 1

    def feed(self, event: Event) -> TouchMessage | None:
        """Take one event; return the pattern when it ends."""
        if event.slot is not None and event.event_id in (SEND_MSG, SEND_MSG_TIMEOUT):
            self._slot = event.slot
        if event.event_id == SEND_MSG_TIMEOUT:
            if event.counter == 0:
                self._pattern = []
            return self._finish()
        if event.event_id != SEND_MSG:
            return None
        press = max(event.touch_ms, MIN_MS)
        if event.counter == 1 or not self._pattern:
            self._pattern = [press]
        else:
            self._pattern += [max(event.release_ms, MIN_MS), press]
        return self._finish() if event.last else None

    def _finish(self) -> TouchMessage | None:
        if not self._pattern:
            return None
        pattern = MINI_PATTERN if self.generation == MINI else tuple(self._pattern)
        self._pattern = []
        return TouchMessage(pattern=pattern, slot=self._slot)


def frame(*parts: int | bytes) -> bytes:
    """Join ints (one byte each) and bytes, and pad with zeros to 20 bytes."""
    out = bytearray()
    for part in parts:
        if isinstance(part, int):
            out.append(part)
        else:
            out += part
    if len(out) > FRAME_SIZE:
        raise ValueError(f"{len(out)} bytes do not fit one {FRAME_SIZE}-byte write")
    return bytes(out.ljust(FRAME_SIZE, b"\x00"))


def auid(value: int) -> bytes:
    """What the app writes to ``ffa2``: the AUID as u32 LE."""
    return value.to_bytes(4, "little")


ENTER_DFU = frame(0x25, 0, 0x11, 0x22, 0x33, 0x44)
PAIRED_ACK = frame(0x31, 0, 0x11, 0x22, 0x33, 0x44)  # answer to PAIRED_SIGNAL
RUN_TOUCH = frame(0x32, 0, 0x11)  # play the queued 0x26 steps
RUN_ANIMATION = frame(0x32, 0, 0x22)  # play the queued 0x33 frames


def wake_gesture(on: bool) -> bytes:
    """``34 00 11`` on, ``34 00 22`` off."""
    return frame(0x34, 0, 0x11 if on else 0x22)


def strength_of(setting: int) -> int:
    """The user's vibration setting if the app allows it, else 80."""
    return setting if setting in STRENGTHS else DEFAULT_STRENGTH


def led_motor(
    *,
    queue: bool = False,
    strength: int = 0,
    vibration_ms: int = 0,
    mode: int = MODE_OFF,
    colour: RGB = BLACK,
    brightness: int = BRIGHTNESS,
    fade_ms: int = 0,
    hold_ms: int = 0,
    sleep_ms: int = 0,
    total_ms: int = 0,
) -> bytes:
    """One 0x26 LED and motor step (LedAndMotorCommand).

    ``queue`` False plays it now; True appends it for RUN_TOUCH.
    """
    _byte(strength, "strength", 100)
    _byte(brightness, "brightness")
    return frame(
        0x26,
        0,
        int(queue),
        strength,
        _u16(vibration_ms),
        mode,
        bytes(colour),
        brightness,
        _u16(fade_ms),
        _u16(hold_ms),
        _u16(sleep_ms),
        _u16(total_ms),
    )


def show_colour(colour: RGB) -> bytes:
    """Light the bracelet in one colour until cleared (mo4123y)."""
    return led_motor(mode=MODE_SOLID, colour=colour, total_ms=UNTIL_CHANGED)


def clear_colour() -> bytes:
    """Turn the LED off (mo4106h)."""
    return led_motor(mode=MODE_OFF, brightness=0)


def vibration_test(strength: int, colour: RGB | None = None) -> bytes:
    """Two seconds of vibration, with the LED on when ``colour`` is given."""
    if colour is None:
        return led_motor(
            strength=strength, vibration_ms=2000, mode=MODE_OFF, brightness=0
        )
    return led_motor(
        strength=strength,
        vibration_ms=2000,
        mode=MODE_SOLID,
        colour=colour,
        total_ms=2000,
    )


def double_tap_answer(colour: RGB) -> bytes:
    """The wearer's own colour breathing once, the app's answer to a double tap."""
    return led_motor(
        mode=MODE_BREATHE,
        colour=colour,
        fade_ms=500,
        hold_ms=1000,
        total_ms=2000,
    )


def wake_demo(colour: RGB, vibrate: bool = True) -> bytes:
    """The setup screen's wake-up demo (mo4107i)."""
    return led_motor(
        strength=50 if vibrate else 0,
        vibration_ms=250 if vibrate else 0,
        mode=MODE_BREATHE,
        colour=colour,
        fade_ms=500,
        hold_ms=2000,
        sleep_ms=250,
        total_ms=UNTIL_CHANGED,
    )


def three_led(
    strength: int,
    brightness: tuple[int, int, int],
    colours: tuple[RGB, RGB, RGB],
    frame_ms: int,
) -> bytes:
    """One 0x33 frame: motor strength, three brightnesses, three colours, time."""
    _byte(strength, "strength", 100)
    for value in brightness:
        _byte(value, "brightness")
    return frame(
        0x33,
        0,
        strength,
        bytes(brightness),
        *(bytes(colour) for colour in colours),
        _u16(frame_ms),
    )


def play_touch(
    pattern: Sequence[int], colour: RGB, strength: int = DEFAULT_STRENGTH
) -> list[bytes]:
    """The writes that play a one-colour touch pattern, RUN_TOUCH last.

    One queued 0x26 step per press: vibration for the press, breathe with a
    fade of a quarter of the press, sleep for the gap that follows.
    """
    out = []
    for press, gap in steps(pattern):
        fade = press // 4
        out.append(
            led_motor(
                queue=True,
                strength=strength,
                vibration_ms=press,
                mode=MODE_BREATHE,
                colour=colour,
                fade_ms=fade,
                hold_ms=press - 2 * fade,
                sleep_ms=gap,
                total_ms=press + gap,
            )
        )
    out.append(RUN_TOUCH)
    return out


def play_blend(
    pattern: Sequence[int],
    start: RGB,
    end: RGB,
    strength: int = DEFAULT_STRENGTH,
) -> list[bytes]:
    """The writes that play a two-colour ("touch meaning") pattern, RUN_ANIMATION last.

    Presses become 200 ms 0x33 frames (the last one shorter) on all three
    LEDs, the colour blended from ``start`` to ``end`` over the whole
    message. Each gap is one dark, still frame. The app's exact blend
    rounding is not recorded; this blends at each frame's start time.
    """
    total = sum(pattern)
    out = []
    elapsed = 0
    for index, duration in enumerate(pattern):
        if index % 2:
            out.append(three_led(0, (0, 0, 0), (BLACK, BLACK, BLACK), duration))
            elapsed += duration
            continue
        left = duration
        while left > 0:
            frame_ms = min(BLEND_FRAME_MS, left)
            colour = blend(start, end, elapsed / total if total else 0.0)
            level = (BRIGHTNESS,) * 3
            out.append(three_led(strength, level, (colour,) * 3, frame_ms))
            elapsed += frame_ms
            left -= frame_ms
    out.append(RUN_ANIMATION)
    return out


def play(
    pattern: Sequence[int],
    colour: RGB,
    generation: str = V2,
    strength: int = DEFAULT_STRENGTH,
    slot: int | None = None,
) -> list[bytes]:
    """Play a received touch the way the app does for ``generation``.

    The Mini always plays MINI_PATTERN. On V4 a ``slot`` first selects the
    sending partner with SELECTED_USER.
    """
    out = []
    if generation == V4 and slot is not None:
        out.append(selected_user(slot))
    if generation == MINI:
        pattern = MINI_PATTERN
    out += play_touch(pattern, colour, strength)
    return out


def config(prop: int, value: bytes = b"") -> bytes:
    """``27 00 <prop> 01 <value>`` (BleAppCommandHelper.m4223d)."""
    _byte(prop, "property")
    return frame(0x27, 0, prop, 0x01, value)


def colour_config(prop: int, colour: RGB | None) -> bytes:
    """A colour property, ARGB u32 big-endian. None writes 0xFF000000 (black)."""
    return config(prop, argb(colour or BLACK).to_bytes(4, "big"))


def touch_colour(colour: RGB) -> bytes:
    return colour_config(TOUCH_COLOR, colour)


def own_colour(colour: RGB, generation: str = V2) -> list[bytes]:
    """The wearer's colour: TOUCH_COLOR, plus DOUBLE_TAP_COLOR on V2 or menu entry 0x80."""
    if generation == V2:
        return [touch_colour(colour), colour_config(DOUBLE_TAP_COLOR, colour)]
    return [touch_colour(colour), _menu_entry(colour, 0x80)]


def partner_menu(partners: Sequence[RGB | None]) -> list[bytes]:
    """V4 and Mini: one USER_MENU write per slot 1..3, None for an empty slot.

    An active slot ``n`` is entry ``n | 0x80`` with the partner's colour, an
    empty one ``n`` with black. Slot 1 is shown only when slot 2 or 3 is
    active.
    """
    if len(partners) > 3:
        raise ValueError("the menu has three slots")
    slots = list(partners) + [None] * (3 - len(partners))
    if slots[1] is None and slots[2] is None:
        slots[0] = None
    out = []
    for number, colour in enumerate(slots, start=1):
        if colour is None:
            out.append(_menu_entry(None, number))
        else:
            out.append(_menu_entry(colour, number | 0x80))
    return out


def selected_user(slot: int) -> bytes:
    """V4: select the partner slot (1..3) whose colour the next touch plays in."""
    if slot not in (1, 2, 3):
        raise ValueError("slot is 1, 2 or 3")
    return config(SELECTED_USER, bytes((slot,)))


def motor_strength(strength: int) -> bytes:
    return config(MOTOR_STRENGTH, bytes((_byte(strength, "strength", 100),)))


def min_touch_duration(ms: int) -> bytes:
    return config(MIN_TOUCH_DURATION, ms.to_bytes(4, "little"))


def low_battery_threshold(percent: int) -> bytes:
    return config(LOW_BAT_THRESHOLD, bytes((_byte(percent, "percent", 100),)))


def low_battery_colour(
    enabled: bool,
    breathe_ms: int,
    sleep_ms: int,
    repeat_sleep_ms: int,
    colour_argb: int,
) -> bytes:
    """LOW_BAT_COLOR: ``enabled u8, breathe u16, sleep u16, repeatSleep u32, colour u32``, BE."""
    return config(
        LOW_BAT_COLOR,
        bytes((int(enabled),))
        + breathe_ms.to_bytes(2, "big")
        + sleep_ms.to_bytes(2, "big")
        + repeat_sleep_ms.to_bytes(4, "big")
        + colour_argb.to_bytes(4, "big"),
    )


def disconnected_param(
    enabled: bool = False,
    breathe_ms: int = 0,
    sleep_ms: int = 0,
    repeat_sleep_ms: int = 0,
    colour_argb: int = 0,
) -> bytes:
    """DISCONNECTED_PARAM: like LOW_BAT_COLOR but ``repeatSleep`` is u16. Off by default."""
    return config(
        DISCONNECTED_PARAM,
        bytes((int(enabled),))
        + breathe_ms.to_bytes(2, "big")
        + sleep_ms.to_bytes(2, "big")
        + repeat_sleep_ms.to_bytes(2, "big")
        + colour_argb.to_bytes(4, "big"),
    )


def ancs(on: bool) -> bytes:
    """ANCS_PARAM. On V2 firmware 2.5.0+, 1 is inferred to start OS pairing."""
    return config(ANCS_PARAM, bytes((int(on),)))


def reset_config() -> bytes:
    """RESET_CONFIG: factory reset. The bracelet then needs setting up again."""
    return config(RESET_CONFIG)


def after_bonding(generation: str = V2) -> list[bytes]:
    """The batch the app writes once Android reports the bracelet bonded."""
    out = [
        low_battery_threshold(10),
        low_battery_colour(True, 1000, 500, 1171, 0x00FF0000),
        min_touch_duration(50),
        disconnected_param(),
    ]
    if generation == V2:
        out.append(ancs(False))
    return out


def _menu_entry(colour: RGB | None, entry: int) -> bytes:
    return config(
        USER_MENU,
        argb(colour or BLACK).to_bytes(4, "big") + entry.to_bytes(4, "big"),
    )


def _u16(value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"a time is 0..65535 ms, got {value}")
    return value.to_bytes(2, "little")


def _byte(value: int, what: str, top: int = 0xFF) -> int:
    if not 0 <= value <= top:
        raise ValueError(f"{what} is 0..{top}, got {value}")
    return value
