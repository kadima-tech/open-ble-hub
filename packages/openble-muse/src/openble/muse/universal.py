"""The universal v3 stream (protocol version 3) on ``UNIVERSAL``.

Read from UniversalDataHandler::handle and the ``*Buffer::receive_data``
functions. No public project documents this revision and no capture has been
checked against it; it appears to precede the BLE4 framing.

    frame:      len | 2 bytes unread | frame time u48 LE | sub-packets…
    sub-packet: tag | seq u8 | time offset s24 LE | payload

The tag's low nibble is the type and its high nibble the rate code. Type 9
is a time-sync request with its own layout (see ``TimeSync``).
"""

from __future__ import annotations

from dataclasses import dataclass

from openble.muse.readings import (
    BATTERY_CHANNELS,
    DPS_PER_BIT,
    G_PER_BIT,
    Reading,
    battery_fields,
    eeg12_uv,
)

HEADER = 9
TIME_SYNC = 9
RATES_HZ = {1: 256, 2: 128, 3: 64, 4: 52, 5: 32, 6: 16, 7: 10, 8: 0.1}
PAYLOAD = {1: 24, 2: 27, 3: 27, 4: 18, 5: 24, 6: 12, 7: 8, 8: 3}
# EegBuffer accessors: TP10() = 0, FP2() = 1, and so on.
EEG_CHANNELS = ("TP10", "AF8", "TP9", "AF7", "AUX_RIGHT", "AUX_LEFT")
PPG_CHANNELS = ("red", "infrared", "ambient")


@dataclass(frozen=True)
class SubPacket:
    tag: int
    kind: int  # low nibble
    rate_code: int  # high nibble
    sequence: int
    offset: int  # sample time = frame time * 1000 + offset * 10
    payload: bytes


@dataclass(frozen=True)
class TimeSync:
    """A type-9 sub-packet: answer it with ``commands.clock_sync``."""

    device_time: int  # u48 LE
    value: int  # u16 LE, meaning unknown
    reset: bool  # flag 1 resets the app's sync filters


@dataclass(frozen=True)
class Frame:
    time: int  # u48 LE; the app multiplies it by 1000
    subpackets: tuple[SubPacket, ...]
    time_syncs: tuple[TimeSync, ...]
    unparsed: bytes  # from the first unknown or truncated sub-packet on


def parse_frame(data: bytes) -> Frame:
    """Split one notification. Byte 0 must equal its length."""
    data = bytes(data)
    if len(data) < HEADER or data[0] != len(data):
        raise ValueError(f"universal frame length mismatch: {data.hex(' ')}")
    subpackets: list[SubPacket] = []
    syncs: list[TimeSync] = []
    i = HEADER
    while i < len(data):
        tag = data[i]
        kind = tag & 0x0F
        if kind == TIME_SYNC:
            if i + 14 > len(data):
                break
            syncs.append(
                TimeSync(
                    device_time=int.from_bytes(data[i + 5 : i + 11], "little"),
                    value=int.from_bytes(data[i + 11 : i + 13], "little"),
                    reset=data[i + 13] == 1,
                )
            )
            i += 14
            continue
        size = PAYLOAD.get(kind)
        if size is None or i + 5 + size > len(data):
            break
        subpackets.append(
            SubPacket(
                tag=tag,
                kind=kind,
                rate_code=tag >> 4,
                sequence=data[i + 1],
                offset=int.from_bytes(data[i + 2 : i + 5], "little", signed=True),
                payload=data[i + 5 : i + 5 + size],
            )
        )
        i += 5 + size
    return Frame(
        time=int.from_bytes(data[3:9], "little"),
        subpackets=tuple(subpackets),
        time_syncs=tuple(syncs),
        unparsed=data[i:],
    )


def unpack_u12_le(payload: bytes) -> list[int]:
    """Two 12-bit values per three bytes, little-endian (``pack1x12``)."""
    values = []
    for o in range(0, len(payload) - 2, 3):
        b0, b1, b2 = payload[o : o + 3]
        values += [b0 | (b1 & 0x0F) << 8, b1 >> 4 | b2 << 4]
    return values


def unpack_ppg(payload: bytes) -> list[tuple[int, int, int]]:
    """Rows of 8 bytes, each three 20-bit values (``pack3x19``)."""
    rows = []
    for o in range(0, len(payload) - 7, 8):
        r = payload[o : o + 8]
        rows.append(
            (
                r[0] | r[1] << 8 | (r[2] & 0x0F) << 16,
                r[2] >> 4 | r[3] << 4 | r[4] << 12,
                r[5] | r[6] << 8 | (r[7] & 0x0F) << 16,
            )
        )
    return rows


def reading(sub: SubPacket) -> Reading:
    """Convert a sub-packet the way the per-sensor packets are converted."""
    rate = RATES_HZ.get(sub.rate_code)
    if sub.kind in (1, 2, 3):
        width = 4 if sub.kind == 1 else 6
        values = [eeg12_uv(v) for v in unpack_u12_le(sub.payload)]
        rows = _rows(values, width)
        return Reading("eeg", EEG_CHANNELS[:width], rows, sub.sequence, rate)
    if sub.kind == 4:
        values = [float(v) for v in unpack_u12_le(sub.payload)]
        return Reading("drl_ref", ("drl", "ref"), _rows(values, 2), sub.sequence, rate)
    if sub.kind == 5:
        rows = tuple(tuple(float(v) for v in row) for row in unpack_ppg(sub.payload))
        return Reading("ppg", PPG_CHANNELS, rows, sub.sequence, rate)
    if sub.kind == 6:
        v = _s16(sub.payload)
        row = tuple(x * G_PER_BIT for x in v[:3]) + tuple(
            x * DPS_PER_BIT for x in v[3:6]
        )
        channels = ("accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z")
        return Reading("imu", channels, (row,), sub.sequence, rate)
    if sub.kind == 7:
        values = [
            int.from_bytes(sub.payload[i : i + 2], "little") for i in range(0, 8, 2)
        ]
        return Reading(
            "battery", BATTERY_CHANNELS, (battery_fields(values),), sub.sequence, rate
        )
    if sub.kind == 8:
        raw = float(int.from_bytes(sub.payload[:3], "little"))
        return Reading("thermistor", ("raw",), ((raw,),), sub.sequence, rate)
    raise ValueError(f"no reading for sub-packet type {sub.kind}")


def _rows(values: list[float], width: int) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(values[i : i + width]) for i in range(0, len(values), width))


def _s16(payload: bytes) -> list[int]:
    return [
        int.from_bytes(payload[i : i + 2], "little", signed=True)
        for i in range(0, len(payload) - 1, 2)
    ]
