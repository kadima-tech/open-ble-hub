"""UUIDs of the Lifesense scale services and characteristics.

16-bit ids expand to the Bluetooth base. Comparison is case-insensitive.
"""

from __future__ import annotations

BLUETOOTH_BASE = "0000{short}-0000-1000-8000-00805f9b34fb"

# Digit 01 weight scale, then digit 02 fat-scale services. 78A2 is also stored
# beside the A4 cluster; the manual leaves that overlap open.
SCALE_SERVICES = {
    "7802": "01",
    "7892": "02",
    "7882": "02",
    "78a2": "02",
    "78d2": "02",
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

# Characteristics whose packets parse_scale_notification understands.
MEASUREMENT_CHARS = {"8a21", "8a22", "8a24", "a402"}


def sig(short: str) -> str:
    return BLUETOOTH_BASE.format(short=short.lower())


def short_of(uuid: str) -> str:
    """Return the 16-bit id, or the full uuid when it is not on the Bluetooth base."""
    text = uuid.lower()
    if text.startswith("0000") and text.endswith("-0000-1000-8000-00805f9b34fb"):
        return text[4:8]
    return text
