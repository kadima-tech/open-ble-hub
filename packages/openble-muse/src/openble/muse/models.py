"""Models, capability sets and presets from the app's libmuse.

The model comes from the first character of the serial number in the status
reply (``bridge::get_model_from_serial_number``). The capability set decides
which characteristics carry data (``DeviceCapability::get_characteristics``).
"""

from __future__ import annotations

from openble.muse import uuids

# MuseModel -> (product, capability set). Product names are the common public
# ones; "inferred" rows come from the capability set alone.
MODELS = {
    "MU_01": ("Muse 2014", "classic"),  # classic Bluetooth, not covered
    "MU_02": ("Muse 2016", "nevis"),
    "MU_03": ("Muse 2", "blackcomb"),
    "MU_06": ("Muse 2, later hardware (inferred)", "blackcomb"),
    "MU_04": ("Muse S", "aster"),
    "MU_05": ("Muse S, later hardware (inferred)", "aster"),
    "MS_03": ("Muse S Athena", "athena"),
    "GL_01": ("internal glasses device", "glasses"),
    "AMHL_01": ("internal, product unknown", "blackcomb"),
}

# cmd::get_default_preset. Public Athena clients use 1041, 1034 or 1045 instead.
DEFAULT_PRESETS = {
    "MU_01": "14",
    "MU_02": "21",
    "MU_03": "21",
    "MU_06": "21",
    "MU_04": "21",
    "MU_05": "21",
    "MS_03": "1021",
}

# Models that take the L1 / L0 indicator LED commands.
LED_MODELS = frozenset({"MU_04", "MU_05", "MS_03"})

_NEVIS = (0x0002, 0x0003, 0x0004, 0x0005, 0x0006, 0x0007, 0x0008, 0x000B)
_NEVIS += (0x000A, 0x0009)
_BLACKCOMB = _NEVIS + (0x000F, 0x0010, 0x0011)
CAPABILITIES = {
    "nevis": _NEVIS,
    "blackcomb": _BLACKCOMB,
    "aster": _BLACKCOMB + (0x0012,),
    "athena": (0x0013, 0x0014, 0x0015),
    "glasses": _NEVIS + (0x000C, 0x000D, 0x000E),
}

# PRESET_MAP in muse_command.cpp, without the Muse 2014 codes.
PRESETS = frozenset(
    {"20", "21", "22", "23", "31", "32", "50", "51", "52", "53", "54", "55"}
    | {"60", "61", "63"}
    | {f"102{c}" for c in "123456789A"}
    | {f"103{c}" for c in "123456"}
    | {f"104{c}" for c in "123456"}
)

# Hardware generation, byte 1 of the manufacturer data (LeDevice.getInfo).
GENERATIONS = {5: "aster", 6: "letto", 7: "athena"}


def model_from_serial(serial: str) -> str:
    """``MuseModel`` name for a serial number, e.g. ``"5031-…"`` -> ``"MU_04"``."""
    first = serial[:1]
    if first == "4":
        return "MU_03" if serial[1:2] <= "2" else "MU_06"
    model = {
        "1": "MU_01",
        "2": "MU_02",
        "3": "GL_01",
        "5": "MU_04",
        "6": "MU_05",
        "7": "MS_03",
        "9": "AMHL_01",
    }.get(first)
    if model is None:
        raise ValueError(f"unknown muse model from serial number {serial!r}")
    return model


def capability(model: str) -> str:
    """The capability set of a model, e.g. ``"MS_03"`` -> ``"athena"``."""
    try:
        return MODELS[model][1]
    except KeyError:
        raise ValueError(f"unknown model {model!r}") from None


def characteristics(model: str, protocol_version: int) -> tuple[str, ...]:
    """Data characteristic uuids the app maps for a model, ``SERIAL`` not included.

    Athena drops ``TIME_SYNC`` below protocol version 5.
    """
    suffixes = CAPABILITIES.get(capability(model))
    if suffixes is None:
        raise ValueError(f"{model} is not a BLE headband")
    if protocol_version < 5:
        suffixes = tuple(s for s in suffixes if s != 0x0015)
    return tuple(uuids.muse_uuid(s) for s in suffixes)


def default_preset(model: str) -> str:
    """The preset the app selects for a model."""
    try:
        return DEFAULT_PRESETS[model]
    except KeyError:
        raise ValueError(f"no default preset for {model}") from None


def layout(protocol_version: int) -> str:
    """``"per-sensor"`` (pv 1-2), ``"universal"`` (pv 3) or ``"ble4"`` (pv >= 4)."""
    if protocol_version < 1:
        raise ValueError(f"protocol version {protocol_version} is below 1")
    if protocol_version <= 2:
        return "per-sensor"
    if protocol_version == 3:
        return "universal"
    return "ble4"
