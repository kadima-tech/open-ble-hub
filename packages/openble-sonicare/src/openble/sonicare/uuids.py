"""UUIDs named in the Sonicare protocol manual.

Sonicare suffixes are the last four hex digits of
477ea600-a260-11e4-ae37-0002a5d5. Comparison is case-insensitive.
"""

from __future__ import annotations

CBT_PREFIX = "477ea600-a260-11e4-ae37-0002a5d5"

SONICARE_SCAN_SERVICE = CBT_PREFIX + "0001"
CONDOR_SCAN_SERVICE = "e50ba3c0-af04-4564-92ad-fef019489de6"

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


def cbt(suffix: str) -> str:
    return CBT_PREFIX + suffix.lower()


def cbt_suffix(uuid: str) -> str | None:
    """Return the four-digit Sonicare suffix, or None for any other uuid."""
    text = uuid.lower()
    if text.startswith(CBT_PREFIX):
        return text[-4:]
    return None
