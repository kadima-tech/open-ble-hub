"""Reassemble and read the JSON replies on ``SERIAL``.

Each notification is ``[n & 0x1F][n characters][padding]``. Chunks are
appended until the buffer parses as JSON (ConnectorImpl::is_valid_json).
Every reply carries an integer ``rc``; 0 is success.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openble.muse.models import model_from_serial

MIN_PROTOCOL, MAX_PROTOCOL = 1, 7  # do_protocol_version_handshake
MAX_BUFFER = 4096  # give up on a reply that never closes


class MuseError(Exception):
    """The headband answered with a non-zero ``rc`` or an unusable reply."""


class Replies:
    """Feed every ``SERIAL`` notification; ``feed`` returns each complete reply."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, data: bytes) -> dict[str, Any] | None:
        if not data:
            return None
        count = data[0] & 0x1F
        self._buffer += bytes(data[1 : 1 + count]).decode("ascii", "replace")
        try:
            reply = json.loads(self._buffer)
        except ValueError:
            if len(self._buffer) > MAX_BUFFER:
                self._buffer = ""
            return None
        if not isinstance(reply, dict):
            return None
        self._buffer = ""
        return reply

    def reset(self) -> None:
        self._buffer = ""


def return_code(reply: dict[str, Any]) -> int:
    """``rc`` as an int. A reply without one is an error, as in the app."""
    rc = reply.get("rc")
    if isinstance(rc, bool) or not isinstance(rc, int):
        raise MuseError(f"reply has no return code: {reply}")
    return rc


@dataclass(frozen=True)
class Version:
    """The ``v<n>`` reply (bridge::MuseVersion::make_version)."""

    protocol: int  # pv
    running: str  # ap: "headset" or "bootloader"
    firmware: str  # fw
    firmware_type: str  # tp: "consumer", "research" or "test"
    hardware: str  # hw
    build: str  # bn
    bsp: str  # sp
    bootloader: str  # bl
    raw: dict[str, Any]

    @property
    def in_bootloader(self) -> bool:
        return self.running == "bootloader"


@dataclass(frozen=True)
class Status:
    """The ``s`` reply (bridge::MuseConfigurationImpl::make_configuration)."""

    name: str  # hn, e.g. Muse-1234
    serial: str  # sn; selects the model
    mac: str  # ma
    mcu_id: str  # id
    battery_percent: float  # bp
    preset: str | None  # ps, as a code such as "21"
    raw: dict[str, Any]

    @property
    def model(self) -> str:
        return model_from_serial(self.serial)


def parse_version(reply: dict[str, Any]) -> Version:
    """Read a version reply. ``pv`` defaults to 1, as muse-js assumes."""
    if return_code(reply) != 0:
        raise MuseError(f"version query failed: {reply}")
    protocol = reply.get("pv", 1)
    if isinstance(protocol, str):
        protocol = int(protocol)
    return Version(
        protocol=protocol,
        running=str(reply.get("ap", "headset")),
        firmware=str(reply.get("fw", "")),
        firmware_type=str(reply.get("tp", "")),
        hardware=str(reply.get("hw", "")),
        build=str(reply.get("bn", "")),
        bsp=str(reply.get("sp", "")),
        bootloader=str(reply.get("bl", "")),
        raw=reply,
    )


def check_protocol(protocol: int) -> None:
    """Refuse a protocol version outside 1..7, with the app's two messages."""
    if protocol < MIN_PROTOCOL:
        raise MuseError(f"protocol version {protocol}: firmware too old")
    if protocol > MAX_PROTOCOL:
        raise MuseError(f"protocol version {protocol}: library too old")


def parse_status(reply: dict[str, Any]) -> Status:
    """Read a status reply. ``hn``, ``sn``, ``ma``, ``id`` and ``bp`` are required."""
    if return_code(reply) != 0:
        raise MuseError(f"status query failed: {reply}")
    missing = [key for key in ("hn", "sn", "ma", "id", "bp") if key not in reply]
    if missing:
        raise MuseError(f"status reply lacks {', '.join(missing)}: {reply}")
    preset = reply.get("ps")
    return Status(
        name=str(reply["hn"]),
        serial=str(reply["sn"]),
        mac=str(reply["ma"]),
        mcu_id=str(reply["id"]),
        battery_percent=float(reply["bp"]),
        preset=_preset_code(preset),
        raw=reply,
    )


def _preset_code(value: Any) -> str | None:
    """``ps`` is the preset code read as hex and sent as an int: 33 is ``21``.

    Seen on a Muse S: ``p21`` turns ``ps`` 81 (``51``) into 33.
    """
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:X}"
    return str(value).upper()
