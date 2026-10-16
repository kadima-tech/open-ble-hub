"""The BLE4 stream (protocol version 4 and up): current Muse S Athena firmware.

Read from Ble4DataHandler::handle, parse_subpackets and ParsedPacket::convert;
the tags and payload sizes match amused, OpenMuse and muse-rs.

    frame:      len | counter u16 LE | device clock u48 LE | sub-packets…
    sub-packet: tag | seq u8 | time offset s24 LE | payload

Frames arrive on ``UNIVERSAL`` and ``MUSE_DEBUG``. The app requires one frame
per notification; OpenMuse walks several by their length bytes, so
``parse_notification`` does both. Values are packed least-significant bit
first, and rows are time steps (sample-major), as amused, OpenMuse and
muse-rs decode them.
"""

from __future__ import annotations

from dataclasses import dataclass

from openble.muse.readings import DPS_PER_BIT, G_PER_BIT, Reading, eeg14_uv

HEADER = 9
EEG4, EEG8, DRL_REF, OPTICS4, OPTICS8, OPTICS16, IMU, BATTERY = range(1, 9)
RATES_HZ = {1: 256, 2: 128, 3: 64, 4: 52, 5: 32, 6: 16, 7: 10, 8: 1, 9: 0.1}
PAYLOAD = {1: 28, 2: 28, 3: 24, 4: 30, 5: 40, 6: 40, 7: 36, 8: 20}
BATTERY_TO_END = 0x88  # newer firmware: 188-230 bytes to the end of the frame

# Channel names are public (muse-rs); the app does not name them.
EEG_CHANNELS = ("TP9", "AF7", "AF8", "TP10", "FPZ", "AUX_RIGHT", "AUX_LEFT", "AUX")
IMU_CHANNELS = ("accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z")
OPTICS_CHANNELS = {OPTICS4: 4, OPTICS8: 8, OPTICS16: 16}


@dataclass(frozen=True)
class SubPacket:
    tag: int
    kind: int  # low nibble
    rate_code: int  # high nibble
    sequence: int  # per type; the app skips duplicates and logs gaps
    offset: int  # s24 LE; the app multiplies it by 100
    payload: bytes


@dataclass(frozen=True)
class Frame:
    counter: int  # u16 LE; the app reorders notifications by it
    clock: int  # u48 LE; muse-rs reads 256 kHz ticks
    subpackets: tuple[SubPacket, ...]
    unparsed: bytes  # from the first unknown or truncated sub-packet on


def parse_frame(data: bytes) -> Frame:
    """Split one frame. Byte 0 must equal its length."""
    data = bytes(data)
    if len(data) < HEADER or data[0] != len(data):
        raise ValueError(f"BLE4 frame length mismatch: {data.hex(' ')}")
    subpackets: list[SubPacket] = []
    i = HEADER
    while i + 5 <= len(data):
        tag = data[i]
        kind = tag & 0x0F
        size = len(data) - i - 5 if tag == BATTERY_TO_END else PAYLOAD.get(kind)
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
        counter=int.from_bytes(data[1:3], "little"),
        clock=int.from_bytes(data[3:9], "little"),
        subpackets=tuple(subpackets),
        unparsed=data[i:],
    )


def parse_notification(data: bytes) -> list[Frame]:
    """Every frame in a notification, walked by their length bytes."""
    data = bytes(data)
    frames = []
    i = 0
    while i < len(data):
        length = data[i]
        if length < HEADER or i + length > len(data):
            raise ValueError(
                f"BLE4 frame at {i} claims {length} bytes: {data.hex(' ')}"
            )
        frames.append(parse_frame(data[i : i + length]))
        i += length
    return frames


def unpack_lsb_first(payload: bytes, bits: int) -> list[int]:
    """Unsigned ``bits``-wide fields, least-significant bit first."""
    word = int.from_bytes(payload, "little")
    mask = (1 << bits) - 1
    return [(word >> (bits * i)) & mask for i in range(len(payload) * 8 // bits)]


def reading(sub: SubPacket, eeg_offset: int = 0) -> Reading:
    """Convert a sub-packet. EEG is in microvolts, optics stay raw.

    ``eeg_offset=EEG14_OFFSET_MUSE_RS`` centres EEG the way muse-rs does.
    """
    rate = RATES_HZ.get(sub.rate_code)
    if sub.kind in (EEG4, EEG8):
        width = 4 if sub.kind == EEG4 else 8
        values = [eeg14_uv(v, eeg_offset) for v in unpack_lsb_first(sub.payload, 14)]
        return Reading(
            "eeg", EEG_CHANNELS[:width], _rows(values, width), sub.sequence, rate
        )
    if sub.kind in OPTICS_CHANNELS:
        width = OPTICS_CHANNELS[sub.kind]
        values = [float(v) for v in unpack_lsb_first(sub.payload, 20)]
        channels = tuple(f"optics_{n}" for n in range(width))
        return Reading("optics", channels, _rows(values, width), sub.sequence, rate)
    if sub.kind == IMU:
        v = _s16(sub.payload)
        rows = tuple(
            tuple(x * G_PER_BIT for x in v[i : i + 3])
            + tuple(x * DPS_PER_BIT for x in v[i + 3 : i + 6])
            for i in range(0, 18, 6)
        )
        return Reading("imu", IMU_CHANNELS, rows, sub.sequence, rate)
    if sub.kind == DRL_REF:
        values = [float(x) for x in _s16(sub.payload)]
        return Reading("drl_ref", ("drl", "ref"), _rows(values, 2), sub.sequence, rate)
    if sub.kind == BATTERY:
        # Only the first field is known: charge percent as u16 LE / 256.
        percent = int.from_bytes(sub.payload[:2], "little") / 256
        return Reading("battery", ("percent",), ((percent,),), sub.sequence, rate)
    raise ValueError(f"no reading for sub-packet type {sub.kind}")


def readings(data: bytes, eeg_offset: int = 0) -> list[Reading]:
    """Every reading in a notification, in order."""
    return [
        reading(sub, eeg_offset)
        for frame in parse_notification(data)
        for sub in frame.subpackets
    ]


def _rows(values: list[float], width: int) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(values[i : i + width]) for i in range(0, len(values), width))


def _s16(payload: bytes) -> list[int]:
    return [
        int.from_bytes(payload[i : i + 2], "little", signed=True)
        for i in range(0, len(payload) - 1, 2)
    ]
