"""Match an advertisement or a GATT table to a Lifesense scale."""

from __future__ import annotations

from openble.lifesense.uuids import SCALE_SERVICES, short_of, sig


def matches_scale(
    name: str, service_uuids: list[str], address: str = "", wanted_address: str = ""
) -> bool:
    """True when an advertisement is the scale this listener should take.

    A requested address has to match. Without one, a Lifesense scale service
    or a DL8780 name is enough.
    """
    if wanted_address:
        return address.lower() == wanted_address.lower()
    if classify(name, service_uuids)[0]:
        return True
    return "dl8780" in name.lower()


def classify(name: str, service_uuids: list[str]) -> tuple[list[str], list[str]]:
    """Return ``(["scale"], reasons)`` for a Lifesense scale service, else empty lists."""
    kinds: list[str] = []
    reasons: list[str] = []
    lowered = {item.lower() for item in service_uuids}
    for short, digit in SCALE_SERVICES.items():
        if sig(short) in lowered:
            if "scale" not in kinds:
                kinds.append("scale")
            reasons.append(f"service {short} (digit {digit})")
    return kinds, reasons


def protocol_digit(service_uuids: list[str]) -> str:
    """The ``family`` for ``parse_scale_notification``: "01", "02", or "" when unknown.

    Pass the service uuids from the connected GATT table.
    """
    digits = set()
    for uuid in service_uuids:
        short = short_of(uuid)
        if short in SCALE_SERVICES:
            digits.add(SCALE_SERVICES[short])
    if "01" in digits:
        return "01"
    if "02" in digits:
        return "02"
    return ""
