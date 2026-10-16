"""ASCII text commands: ``<Name>[:<arg>…];``, one per GATT write.

No MTU is negotiated, so a write holds at most 20 bytes and the app does no
chunking. Command names are from com.component.dxtoy.core.commandcore.constant
(``b`` motion, ``e`` the rest); builders are in com.component.dxtoy.command.code.
"""

from __future__ import annotations

from collections.abc import Sequence

from openble.lovense.models import FUNCTIONS

MAX_WRITE = 20

DEVICE_TYPE = b"DeviceType;"
BATTERY = b"Battery;"
GET_CAP = b"GetCap;"
GET_BATCH = b"GetBatch,gb;"
DEVICE_INFO = b"DeviceInfo;"
GET_PARTS = b"GetParts;"
POWER_OFF = b"PowerOff;"
RESET_NAME = b"RstName;"
ROTATE_CHANGE = b"RotateChange;"  # reverse direction; the app never drops a repeat

# A reply tag byte cycles 1..127 per toy and skips these (y9.h).
TAG_SKIP = frozenset(b"\x00\n ,:;")


def text(name: str, *args: object) -> bytes:
    """``Name:arg:arg;`` as ASCII. Raises if it does not fit one 20-byte write."""
    out = ":".join((name, *(str(arg) for arg in args))).encode("ascii") + b";"
    if len(out) > MAX_WRITE:
        raise ValueError(f"{out!r} is {len(out)} bytes; one write holds {MAX_WRITE}")
    return out


def motion(letter: str, level: int) -> bytes:
    """The single-function command for a function letter, e.g. ``v`` 10 -> ``Vibrate:10;``."""
    try:
        _function, name, top = FUNCTIONS[letter]
    except KeyError:
        raise ValueError(f"unknown function letter {letter!r}") from None
    return text(name, _level(level, 0, top))


def stop(letters: Sequence[str] = ("v",)) -> list[bytes]:
    """Level-0 commands for each function letter. Stroke position has no stop."""
    return [motion(letter, 0) for letter in letters if letter != "pos"]


def vibrate(level: int, motor: int | None = None) -> bytes:
    """``Vibrate:<n>;``, or ``Vibrate<motor>:<n>;`` for motor 1..3."""
    if motor is None:
        return motion("v", level)
    if motor not in (1, 2, 3):
        raise ValueError("motor must be 1, 2 or 3")
    return motion(f"v{motor}", level)


def rotate(level: int, direction: bool | None = None) -> bytes:
    """``Rotate:<n>;``, or ``Rotate:True:<n>;`` / ``Rotate:False:<n>;``.

    The app's letters for those are ``rl`` (True) and ``rr`` (False). Which way
    each one turns is not recorded.
    """
    if direction is None:
        return motion("r", level)
    return text("Rotate", "True" if direction else "False", _level(level, 0, 20))


def air(direction: str, level: int) -> bytes:
    """``Air:In:<n>;`` or ``Air:Out:<n>;``, level 1..3."""
    if direction not in ("In", "Out"):
        raise ValueError("direction must be 'In' or 'Out'")
    return text("Air", direction, _level(level, 1, 3))


def set_stroke(low: int, high: int) -> bytes:
    """``SetStroke:<min>:<max>;``: min 0..80, max 20..100, at least 20 apart."""
    _level(low, 0, 80)
    _level(high, 20, 100)
    if high - low < 20:
        raise ValueError("max must be at least 20 above min")
    return text("SetStroke", low, high)


def preset(number: int) -> bytes:
    """``Preset:<0..10>;``: a built-in pattern, 0 stops it."""
    return text("Preset", _level(number, 0, 10))


def rename(name: str) -> bytes:
    """``CN:<name>;``: 1..12 of ``[0-9A-Za-z_ ]``, without ``dfu``, ``new`` or ``lvs``."""
    allowed = set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_ ")
    if not 1 <= len(name) <= 12 or not set(name) <= allowed:
        raise ValueError("name must be 1..12 of letters, digits, '_' or space")
    if any(word in name.lower() for word in ("dfu", "new", "lvs")):
        raise ValueError("name must not contain dfu, new or lvs")
    return text("CN", name)


def mply(levels: Sequence[int]) -> bytes:
    """``Mply:<v1>:…:<vN>;``: one level per function group, N <= 5, -1 leaves it.

    Not every toy takes it: a Max on firmware 223 answers ``unkown,Mply:…;``
    and takes ``lvs`` instead.

    Air pump groups take 0..3 and the rest 0..20; this checks only -1..20,
    because the group order comes from the toy's config.
    """
    return _combined("Mply", levels, 5)


def multiply(levels: Sequence[int]) -> bytes:
    """``Multiply:<v1>:…;``, the older form of ``Mply`` with N <= 3."""
    return _combined("Multiply", levels, 3)


def lvs(channels: Sequence[int]) -> bytes:
    """``LVS:`` + one byte per GetCap channel + ``;``, padded with 0xFF to 20 bytes.

    Each value is 0..127. A negative value sets bit 7, the rotate direction
    bit (sign-magnitude); which way that turns is not recorded.
    """
    if not 1 <= len(channels) <= 15:
        raise ValueError("LVS takes 1..15 channels")
    body = bytearray()
    for value in channels:
        if not -127 <= value <= 127:
            raise ValueError("channel values are -127..127")
        body.append(0x80 | -value if value < 0 else value)
    out = b"LVS:" + bytes(body) + b";"
    return out + b"\xff" * (MAX_WRITE - len(out))


def next_tag(previous: int) -> int:
    """The tag byte after ``previous``: 1..127, skipping the bytes in TAG_SKIP."""
    tag = previous
    while True:
        tag = tag % 127 + 1
        if tag not in TAG_SKIP:
            return tag


def tag_command(command: bytes, tag: bytes) -> bytes:
    """Insert ``,<tag>`` before the final ``;``, unless that exceeds 20 bytes.

    The app tags non-motion commands so it can match replies. Untagged commands
    work too: the app sends ``DeviceType;`` and ``Battery;`` without one.
    """
    if not command.endswith(b";"):
        raise ValueError("a command ends with ';'")
    tagged = command[:-1] + b"," + tag + b";"
    return command if len(tagged) > MAX_WRITE else tagged


def strip_tag(reply: bytes, tag: bytes) -> bytes:
    """Drop a matching ``,<tag>`` before the final ``;`` of a reply."""
    suffix = b"," + tag + b";"
    if reply.endswith(suffix):
        return reply[: -len(suffix)] + b";"
    return reply


def _combined(name: str, levels: Sequence[int], most: int) -> bytes:
    if not 1 <= len(levels) <= most:
        raise ValueError(f"{name} takes 1..{most} levels")
    return text(name, *(_level(level, -1, 20) for level in levels))


def _level(value: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("level must be an int")
    if not low <= value <= high:
        raise ValueError(f"level must be {low}..{high}, got {value}")
    return value
