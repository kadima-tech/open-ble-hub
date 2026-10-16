"""Match an advertisement to a Bond Touch bracelet and pick its generation.

The app matches by name only: no scan filter uses a service UUID and the app
never parses manufacturer data. It then tells the generations apart from the
GATT table and one API version byte, not from the name.
"""

from __future__ import annotations

from collections.abc import Iterable

from openble.bondtouch import uuids

V1, V2, V3, V4, MINI = "v1", "v2", "v3", "v4", "mini"
GENERATIONS = (V1, V2, V3, V4, MINI)

# ff10 byte -> generation (p000/rb0). Any other value is V1.
API_VERSIONS = {0x42: V2, 0x44: V4, 0x45: MINI}

# The firmware each manager in app 11.2.0 targets. Older firmware gets an
# update offer before the app goes on to bonding.
TARGET_FIRMWARE = {
    V1: (1, 2, 96),
    V2: (2, 7, 9),
    V3: (3, 1, 1),
    V4: (2, 0, 3),
    MINI: (1, 2, 0),
}

# What each manager checks for before it starts; a missing one is a
# connection error in the app. V4 and Mini need BOND_TRIGGER only to bond.
REQUIRED = {
    V1: (
        uuids.V1_FIRMWARE,
        uuids.BATTERY,
        uuids.TOKEN,
        uuids.AUID,
        uuids.STATE,
        uuids.EVENT,
        uuids.COMMAND,
        uuids.V1_RESULT,
    ),
    V2: (
        uuids.BATTERY,
        uuids.TOKEN,
        uuids.AUID,
        uuids.STATE,
        uuids.EVENT,
        uuids.COMMAND,
        uuids.FIRMWARE_REVISION,
    ),
    V3: (uuids.V3_COMMAND, uuids.V3_TOUCH),
}
REQUIRED[V4] = REQUIRED[MINI] = REQUIRED[V2]


def classify(name: str, service_uuids: list[str]) -> tuple[list[str], list[str]]:
    """Return ``(["bracelet"], reasons)``, ``(["bracelet-dfu"], reasons)`` or empty lists.

    Names are matched exactly, as Android's name filter does. A Bond service
    UUID in the advertisement also counts, though the app never relies on one.
    """
    kinds: list[str] = []
    reasons: list[str] = []
    if name in uuids.NAMES:
        kinds.append("bracelet")
        reasons.append(f"name {name}")
    elif name in uuids.DFU_NAMES:
        kinds.append("bracelet-dfu")
        reasons.append(f"name {name} (bootloader)")
    for uuid in service_uuids:
        text = uuid.lower()
        if text.startswith("d3c0") and text.endswith(uuids.BOND_TAIL):
            if not kinds:
                kinds.append("bracelet")
            reasons.append(f"service {text}")
    return kinds, reasons


def is_v3(service_uuids: Iterable[str]) -> bool:
    """True when the GATT table has the Bond More service (step 4 of the lifecycle)."""
    return uuids.V3_SERVICE in {uuid.lower() for uuid in service_uuids}


def generation_of(api_version: bytes | int) -> str:
    """The generation for an ``ff10`` value: 0x42 V2, 0x44 V4, 0x45 Mini, else V1."""
    if isinstance(api_version, (bytes, bytearray)):
        if not api_version:
            raise ValueError("empty API version")
        api_version = api_version[0]
    return API_VERSIONS.get(api_version, V1)


def missing(generation: str, characteristic_uuids: Iterable[str]) -> list[str]:
    """The characteristics ``generation`` needs that the GATT table lacks."""
    present = {uuid.lower() for uuid in characteristic_uuids}
    return [uuid for uuid in REQUIRED[generation] if uuid not in present]


def parse_firmware(text: str | bytes) -> tuple[int, ...]:
    """``"2.7.9"`` (the DIS ``2a26`` string) -> ``(2, 7, 9)``."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    parts = text.strip().strip("\x00").lstrip("vV").split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        raise ValueError(f"not a firmware version: {text!r}") from None


def v1_firmware(data: bytes) -> tuple[int, int, int]:
    """The V1 ``ff03`` value ``[patch, minor]`` -> ``(1, minor, patch)``."""
    if len(data) < 2:
        raise ValueError(f"ff03 needs 2 bytes: {bytes(data).hex(' ')}")
    return (1, data[1], data[0])


def needs_update(generation: str, firmware: tuple[int, ...]) -> bool:
    """True when the app would offer a firmware update instead of going on to bond."""
    return tuple(firmware) < TARGET_FIRMWARE[generation]
