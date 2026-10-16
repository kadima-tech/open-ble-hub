"""UUIDs named in the Muse protocol manual.

One primary service, ``0xFE8D``. Every characteristic is
``273eXXXX-4c4d-454d-96be-f03bac821358``; the names are the app's
``CharacteristicId`` enum (CharacteristicMapperImpl). Comparison is
case-insensitive.
"""

from __future__ import annotations

SERVICE = "0000fe8d-0000-1000-8000-00805f9b34fb"
CCCD = "00002902-0000-1000-8000-00805f9b34fb"

_TAIL = "-4c4d-454d-96be-f03bac821358"


def muse_uuid(suffix: int) -> str:
    """``0x0001`` -> ``273e0001-4c4d-454d-96be-f03bac821358``."""
    return f"273e{suffix:04x}{_TAIL}"


def suffix_of(uuid: str) -> int | None:
    """The 16-bit suffix of a Muse characteristic, or None for any other uuid."""
    text = uuid.lower()
    if len(text) != 36 or not text.startswith("273e") or not text.endswith(_TAIL):
        return None
    try:
        return int(text[4:8], 16)
    except ValueError:
        return None


SERIAL = muse_uuid(0x0001)  # commands (write) and JSON replies (notify)
SIGNAL_AUX_LEFT = muse_uuid(0x0002)
SIGNAL_TP9 = muse_uuid(0x0003)
SIGNAL_FP1 = muse_uuid(0x0004)  # AF7
SIGNAL_FP2 = muse_uuid(0x0005)  # AF8
SIGNAL_TP10 = muse_uuid(0x0006)
SIGNAL_AUX_RIGHT = muse_uuid(0x0007)
DRL_REF = muse_uuid(0x0008)
GYRO = muse_uuid(0x0009)
ACCELEROMETER = muse_uuid(0x000A)
BATTERY = muse_uuid(0x000B)
MAGNETOMETER = muse_uuid(0x000C)
PRESSURE = muse_uuid(0x000D)
ULTRA_VIOLET = muse_uuid(0x000E)
PPG_AMBIENT = muse_uuid(0x000F)
PPG_IR = muse_uuid(0x0010)
PPG_RED = muse_uuid(0x0011)
THERMISTOR = muse_uuid(0x0012)
UNIVERSAL = muse_uuid(0x0013)  # multiplexed stream, pv >= 3
MUSE_DEBUG = muse_uuid(0x0014)  # Athena; BLE4 frames arrive here too (muse-rs)
TIME_SYNC = muse_uuid(0x0015)  # Athena, pv >= 5; message format still open

# Per-sensor EEG characteristic -> electrode, in the order muse-js streams them.
EEG_CHANNELS = {
    SIGNAL_TP9: "TP9",
    SIGNAL_FP1: "AF7",
    SIGNAL_FP2: "AF8",
    SIGNAL_TP10: "TP10",
    SIGNAL_AUX_RIGHT: "AUX_RIGHT",
    SIGNAL_AUX_LEFT: "AUX_LEFT",
}
