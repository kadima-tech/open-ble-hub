"""Per-sensor data packets (protocol versions 1-2): Muse 2016, Muse 2, Muse S.

Every notification is 20 bytes: a big-endian u16 counter, then big-endian
samples (DataHandlerImpl::handle_legacy, parse_packet12/16/24/32). The
counter goes up by one per notification on that characteristic.
"""

from __future__ import annotations

from openble.muse import uuids
from openble.muse.readings import (
    BATTERY_CHANNELS,
    DPS_PER_BIT,
    G_PER_BIT,
    Reading,
    battery_fields,
    eeg12_uv,
    thermistor_c,
)

EEG_HZ = 256
IMU_HZ = 52
PPG_HZ = 64


def unpack_u12(data: bytes) -> tuple[int, list[int]]:
    """``(counter, 12 values)``; two values per three bytes, high nibble first."""
    data = _check(data)
    values = []
    for i in range(12):
        o = 2 + 3 * i // 2
        if i % 2 == 0:
            values.append(data[o] << 4 | data[o + 1] >> 4)
        else:
            values.append((data[o] & 0x0F) << 8 | data[o + 1])
    return _counter(data), values


def unpack_s16(data: bytes) -> tuple[int, list[int]]:
    """``(counter, 9 signed values)``; the IMU layout."""
    data = _check(data)
    return _counter(data), [
        int.from_bytes(data[2 + 2 * i : 4 + 2 * i], "big", signed=True)
        for i in range(9)
    ]


def unpack_u16(data: bytes, count: int = 9) -> tuple[int, list[int]]:
    data = _check(data)
    return _counter(data), [
        int.from_bytes(data[2 + 2 * i : 4 + 2 * i], "big") for i in range(count)
    ]


def unpack_u24(data: bytes) -> tuple[int, list[int]]:
    """``(counter, 6 values)``; the PPG layout."""
    data = _check(data)
    return _counter(data), [
        int.from_bytes(data[2 + 3 * i : 5 + 3 * i], "big") for i in range(6)
    ]


def unpack_u32(data: bytes) -> tuple[int, list[int]]:
    data = _check(data)
    return _counter(data), [
        int.from_bytes(data[2 + 4 * i : 6 + 4 * i], "big") for i in range(4)
    ]


def eeg(data: bytes, channel: str = "EEG") -> Reading:
    """12 samples of one electrode, in microvolts (muse-js scale and offset)."""
    counter, values = unpack_u12(data)
    return Reading(
        "eeg", (channel,), tuple((eeg12_uv(v),) for v in values), counter, EEG_HZ
    )


def accelerometer(data: bytes) -> Reading:
    """3 samples of x, y, z in g."""
    counter, values = unpack_s16(data)
    return Reading(
        "accelerometer", ("x", "y", "z"), _xyz(values, G_PER_BIT), counter, IMU_HZ
    )


def gyro(data: bytes) -> Reading:
    """3 samples of x, y, z in degrees per second, with the app's sign."""
    counter, values = unpack_s16(data)
    return Reading("gyro", ("x", "y", "z"), _xyz(values, DPS_PER_BIT), counter, IMU_HZ)


def battery(data: bytes) -> Reading:
    """Charge percent, fuel gauge mV, ADC mV and temperature C."""
    counter, values = unpack_u16(data, 4)
    return Reading(
        "battery", BATTERY_CHANNELS, (battery_fields(values),), counter, None
    )


def ppg(data: bytes, channel: str = "PPG") -> Reading:
    """6 raw samples of one wavelength."""
    counter, values = unpack_u24(data)
    return Reading(
        "ppg", (channel,), tuple((float(v),) for v in values), counter, PPG_HZ
    )


def drl_ref(data: bytes) -> Reading:
    """6 raw samples of DRL and REF, interleaved on the wire."""
    counter, values = unpack_u12(data)
    rows = tuple((float(values[i]), float(values[i + 1])) for i in range(0, 12, 2))
    return Reading("drl_ref", ("drl", "ref"), rows, counter, None)


def thermistor(data: bytes) -> Reading:
    """12 skin temperature samples in degrees C."""
    counter, values = unpack_u12(data)
    rows = tuple((thermistor_c(v),) for v in values)
    return Reading("thermistor", ("temperature_c",), rows, counter, None)


_PPG_CHANNELS = {
    uuids.PPG_AMBIENT: "ambient",
    uuids.PPG_IR: "infrared",
    uuids.PPG_RED: "red",
}


def decode(uuid: str, data: bytes) -> Reading | None:
    """Decode a notification by its characteristic, or None for one not covered.

    The glasses-only magnetometer, pressure and UV characteristics are not
    decoded; ``unpack_*`` reads their raw values.
    """
    uuid = uuid.lower()
    if uuid in uuids.EEG_CHANNELS:
        return eeg(data, uuids.EEG_CHANNELS[uuid])
    if uuid in _PPG_CHANNELS:
        return ppg(data, _PPG_CHANNELS[uuid])
    handler = {
        uuids.ACCELEROMETER: accelerometer,
        uuids.GYRO: gyro,
        uuids.BATTERY: battery,
        uuids.DRL_REF: drl_ref,
        uuids.THERMISTOR: thermistor,
    }.get(uuid)
    return handler(data) if handler else None


def _xyz(values: list[int], scale: float) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(v * scale for v in values[i : i + 3]) for i in range(0, 9, 3))


def _check(data: bytes) -> bytes:
    data = bytes(data)
    if len(data) < 20:
        raise ValueError(f"per-sensor packet needs 20 bytes: {data.hex(' ')}")
    return data


def _counter(data: bytes) -> int:
    return data[0] << 8 | data[1]
