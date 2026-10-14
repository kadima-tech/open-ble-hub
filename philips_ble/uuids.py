"""UUIDs named in the protocol manuals.

16-bit ids expand to the Bluetooth base. Sonicare suffixes are the last four
hex digits of 477ea600-a260-11e4-ae37-0002a5d5. Comparison is case-insensitive.
"""

from __future__ import annotations

BLUETOOTH_BASE = "0000{short}-0000-1000-8000-00805f9b34fb"
CBT_PREFIX = "477ea600-a260-11e4-ae37-0002a5d5"

SONICARE_SCAN_SERVICE = CBT_PREFIX + "0001"
CONDOR_SCAN_SERVICE = "e50ba3c0-af04-4564-92ad-fef019489de6"

# Digit 01 weight scale, then digit 02 fat-scale services. 78A2 is also stored
# beside the A4 cluster; the manual leaves that overlap open.
SCALE_SERVICES = {
    "7802": "01",
    "7892": "02",
    "7882": "02",
    "78a2": "02",
    "78d2": "02",
}

DIS_SERVICE = "180a"
BATTERY_SERVICE = "180f"

DIS_CHARS = {
    "2a29": ("manufacturer", "utf8"),
    "2a24": ("model", "utf8"),
    "2a25": ("serial", "utf8"),
    "2a27": ("hardware", "utf8"),
    "2a26": ("firmware", "utf8"),
    "2a28": ("software", "utf8"),
    "2a23": ("system id", "hex"),
    "2a2a": ("certification", "hex"),
    "2a50": ("pnp id", "hex"),
}

BATTERY_LEVEL = "2a19"

# suffix -> (name, value kind). Kinds: hex, int, utf8.
# int means the manual says the app parses an integer. Endianness is not recorded.
CBT_CHARS = {
    "4010": ("handle state", "hex"),
    "4050": ("handle time", "int"),
    "4020": ("available brushing routines", "hex"),
    "4022": ("routine ids", "hex"),
    "4040": ("cumulative motor runtime", "hex"),
    "4090": ("brushing time", "hex"),
    "4080": ("routine id", "hex"),
    "4091": ("routine length", "hex"),
    "4070": ("current session id", "hex"),
    "40b0": ("intensity", "hex"),
    "4082": ("routine state", "hex"),
    "40d0": ("latest session id", "int"),
    "40d5": ("session type", "hex"),
    "40e0": ("active session id", "hex"),
    "4110": ("sacp", "hex"),
    "4100": ("session data", "hex"),
    "40d2": ("available session count", "hex"),
    "4130": ("sensor notification", "hex"),
    "4120": ("selected sensor data", "hex"),
    "4210": ("brush head 4210", "hex"),
    "4230": ("brush head serial or nfc tag version", "hex"),
    "4220": ("factory mode", "hex"),
    "4280": ("lifetime limit", "hex"),
    "4290": ("lifetime usage", "hex"),
    "42c0": ("ring id", "hex"),
    "4310": ("error value persistent", "hex"),
    "4320": ("error value volatile", "hex"),
    "4330": ("proximity", "hex"),
    "4340": ("external flash", "hex"),
    "4350": ("pressure sensor", "hex"),
    "4360": ("invalid charger count", "hex"),
    "4370": ("debug information", "hex"),
    "4420": ("handle settings", "hex"),
}

SCALE_CHARS = {
    "8a21": "A2 weight",
    "8a22": "A2 fat or A3 append",
    "8a24": "A3 weight",
    "8a20": "declared beside 7802, role unresolved",
    "8a23": "declared beside 7802, role unresolved",
    "8a81": "command write",
    "8a82": "command indicate",
    "a402": "A4 notification, layout unresolved",
}


def sig(short: str) -> str:
    return BLUETOOTH_BASE.format(short=short.lower())


def cbt(suffix: str) -> str:
    return CBT_PREFIX + suffix.lower()


def short_of(uuid: str) -> str:
    """Return the 16-bit id, the Sonicare suffix, or the full uuid."""
    text = uuid.lower()
    if text.startswith("0000") and text.endswith("-0000-1000-8000-00805f9b34fb"):
        return text[4:8]
    if text.startswith(CBT_PREFIX):
        return text[-4:]
    return text
