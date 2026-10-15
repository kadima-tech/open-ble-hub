"""Standard GATT services the probe reads, and uuid shortening for both devices."""

from __future__ import annotations

from openble.lifesense.uuids import short_of as _sig_short_of
from openble.sonicare.uuids import cbt_suffix

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


def short_of(uuid: str) -> str:
    """Return the 16-bit id, the Sonicare suffix, or the full uuid."""
    return cbt_suffix(uuid) or _sig_short_of(uuid)
