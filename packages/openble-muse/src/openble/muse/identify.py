"""Match an advertisement to a Muse headband (MuseManagerAndroid, LeDevice)."""

from __future__ import annotations

from collections.abc import Mapping

from openble.muse.models import GENERATIONS
from openble.muse.uuids import SERVICE


def classify(name: str, service_uuids: list[str]) -> tuple[list[str], list[str]]:
    """Return ``(["headband"], reasons)`` for a Muse headband, else empty lists.

    The app scans for service ``0xFE8D``; a name starting ``Muse`` also counts.
    """
    reasons: list[str] = []
    if SERVICE in {uuid.lower() for uuid in service_uuids}:
        reasons.append("service fe8d")
    if name.startswith("Muse"):
        reasons.append(f"name {name}")
    return (["headband"] if reasons else []), reasons


def generation(manufacturer_data: Mapping[int, bytes]) -> str | None:
    """Hardware generation from byte 1 of the first manufacturer data entry.

    Any company ID is accepted. Android and bleak both hand over the value
    without the two company ID bytes. Returns ``aster``, ``letto``,
    ``athena``, or None when absent or unknown.
    """
    for value in manufacturer_data.values():
        return GENERATIONS.get(value[1]) if len(value) > 1 else None
    return None


def fallback_name(address: str, hardware: str | None = None) -> str:
    """The name the app shows when the OS reports none.

    ``Muse-`` (``MuseS-`` for generations 5-7) plus the last four hex digits
    of the address. The status reply's ``hn`` replaces it after connecting.
    """
    digits = address.replace(":", "").replace("-", "").upper()[-4:]
    return ("MuseS-" if hardware in GENERATIONS.values() else "Muse-") + digits
