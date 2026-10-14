"""Match an advertisement to the scale or the toothbrush."""

from __future__ import annotations

from philips_ble.uuids import CONDOR_SCAN_SERVICE, SCALE_SERVICES, SONICARE_SCAN_SERVICE, sig


def matches_scale(name: str, service_uuids: list[str], address: str = "", wanted_address: str = "") -> bool:
    """True when an advertisement is the scale this listener should take.

    A requested address has to match. Without one, a Lifesense scale service
    or a DL8780 name is enough.
    """
    if wanted_address:
        return address.lower() == wanted_address.lower()
    kinds, _reasons = classify(name, service_uuids)
    if "scale" in kinds:
        return True
    return "dl8780" in name.lower()


def classify(name: str, service_uuids: list[str]) -> tuple[list[str], list[str]]:
    kinds: list[str] = []
    reasons: list[str] = []
    lowered = {item.lower() for item in service_uuids}
    if SONICARE_SCAN_SERVICE in lowered:
        kinds.append("toothbrush")
        reasons.append("service 477ea600-…0001")
    if "philips sonicare" in name.lower():
        if "toothbrush" not in kinds:
            kinds.append("toothbrush")
        reasons.append("name Philips Sonicare")
    if CONDOR_SCAN_SERVICE in lowered:
        kinds.append("toothbrush-condor")
        reasons.append("service e50ba3c0-…")
    for short, digit in SCALE_SERVICES.items():
        if sig(short) in lowered:
            if "scale" not in kinds:
                kinds.append("scale")
            reasons.append(f"service {short} (digit {digit})")
    return kinds, reasons
