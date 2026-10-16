"""The decoded form every data layout produces, and the unit conversions.

Constants are the app's (``PacketConverter::convert_packet`` and
``ParsedPacket::convert``) unless named after a public project. Where the two
disagree the default follows the public projects that have run on hardware,
and the app's value is kept beside it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Per-sensor and universal v3 EEG, 12-bit. muse-js and muse-rs centre on 2048
# at 1000/2048 uV per bit; the app scales by 1650/4095 with no offset.
EEG12_OFFSET = 2048
EEG12_UV_PER_BIT = 0.48828125
EEG12_UV_PER_BIT_APP = 1650 / 4095

# BLE4 EEG, 14-bit. The app, amused and muse-lsl agree on the scale and the
# app subtracts no offset; muse-rs subtracts 8192.
EEG14_UV_PER_BIT = 1450 / 16383
EEG14_OFFSET_MUSE_RS = 8192

G_PER_BIT = 1 / 16384  # accelerometer
# Gyro. The app and the Athena projects use a negative factor; muse-js has +.
DPS_PER_BIT = -0.0074768
OPTICS_PER_BIT_APP = 3.0517607e-5  # BLE4 optics; readings stay raw


@dataclass(frozen=True)
class Reading:
    """One packet or sub-packet, converted.

    ``samples`` has one row per time step and one column per entry of
    ``channels``. ``sequence`` is the per-sensor packet counter (u16) or the
    sub-packet sequence number (u8). ``rate_hz`` is None when not known.
    """

    # eeg, accelerometer, gyro, imu, ppg, optics, drl_ref, battery or thermistor
    kind: str
    channels: tuple[str, ...]
    samples: tuple[tuple[float, ...], ...]
    sequence: int
    rate_hz: float | None


def eeg12_uv(
    raw: int, offset: int = EEG12_OFFSET, scale: float = EEG12_UV_PER_BIT
) -> float:
    """12-bit EEG in microvolts. The app's form is ``offset=0, scale=EEG12_UV_PER_BIT_APP``."""
    return (raw - offset) * scale


def eeg14_uv(raw: int, offset: int = 0) -> float:
    """14-bit BLE4 EEG in microvolts."""
    return (raw - offset) * EEG14_UV_PER_BIT


def thermistor_c(raw: int) -> float:
    """12-bit skin thermistor to degrees C (NaN at the rails).

    V = raw / 4096 * 2.9; R = 62000 V / (2.9 - V); Beta 4700 at 100 kOhm, 25 C.
    """
    volts = raw / 4096 * 2.9
    if volts <= 0 or volts >= 2.9:
        return math.nan
    ohms = 62000 * volts / (2.9 - volts)
    return 1 / (1 / 298.15 + math.log(ohms / 100000) / 4700) - 273.15


def battery_fields(values: tuple[int, ...] | list[int]) -> tuple[float, ...]:
    """Per-sensor and universal v3 battery: percent, fuel gauge mV, ADC mV, C."""
    charge, gauge, adc, temperature = values[:4]
    return (charge / 512, gauge * 2.2, adc * 4.4, float(temperature))


BATTERY_CHANNELS = ("percent", "fuel_gauge_mv", "adc_mv", "temperature_c")
