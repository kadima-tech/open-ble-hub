"""ASCII commands on ``SERIAL`` and their length-prefixed framing.

Builders follow ``interaxon::cmd::nevis``; framing is ``ConnectorImpl::send``:
one byte ``n`` (the command bytes that follow, ``\\n`` included, at most 19),
then the ASCII command ending in ``\\n``. ``s`` goes out as ``02 73 0a``.
Builders return the command text; ``encode`` frames it for the write.
"""

from __future__ import annotations

from openble.muse.models import PRESETS

MAX_PAYLOAD = 19  # command bytes after the length byte, "\n" included

STATUS = "s"
HALT = "h"
KEEP_ALIVE = "k"  # every 2.5 s while paused
BOOT_TO_HEADSET = "*1"  # leave the bootloader
BOOT_TO_BOOTLOADER = "*0"  # for firmware update; no reply
LED_ON = "L1"  # MU_04, MU_05 and MS_03 only; no reply
LED_OFF = "L0"
START_FLAGS = 0xC001  # meaning not known; public clients send it too
START_LEGACY = "d"  # what muse-js and the per-sensor path in muse-rs send


def encode(command: str) -> bytes:
    """``[n][command]\\n`` as one write. Raises if it exceeds 19 bytes."""
    body = (command + "\n").encode("ascii")
    if len(body) > MAX_PAYLOAD:
        raise ValueError(f"{command!r} is {len(body)} bytes with '\\n'; max 19")
    return bytes((len(body),)) + body


def expects_reply(command: str) -> bool:
    """False for the fire-and-forget commands, which start with ``L`` or ``Q``."""
    return not command.startswith(("L", "Q"))


def version(offered: int = 7) -> str:
    """``v<n>``: the version query, offering protocol version ``n`` in hex.

    The app sends ``v7``. Public clients send ``v1``, ``v4`` or ``v6``.
    """
    if not 0 <= offered <= 0xF:
        raise ValueError("offered protocol version is one hex digit")
    return f"v{offered:x}"


def preset(code: str) -> str:
    """``p<code>``, e.g. ``p21`` or ``p1035``. Halt streaming first."""
    code = code.upper()
    if code not in PRESETS:
        raise ValueError(f"unknown preset {code!r}")
    return "p" + code


def start_streaming(flags: int = START_FLAGS) -> str:
    """``d`` + flags in hex, ``dc001``. Older clients send ``START_LEGACY``."""
    return f"d{flags:x}"


def led(on: bool) -> str:
    return LED_ON if on else LED_OFF


def clock_sync(index: int, host_ms: int) -> str:
    """``Q<k> C,<12 hex digits>``: the universal v3 clock-sync answer.

    ``host_ms`` is wall-clock milliseconds, most significant digit first.
    What ``k`` counts is not recorded; this formats it in decimal.
    """
    if not 0 <= host_ms < 1 << 48:
        raise ValueError("host time is 48 bits")
    return f"Q{index} C,{host_ms:012x}"
