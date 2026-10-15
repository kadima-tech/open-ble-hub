"""Match an advertisement to a Sonicare toothbrush."""

from __future__ import annotations

from openble.sonicare.uuids import CONDOR_SCAN_SERVICE, SONICARE_SCAN_SERVICE


def classify(name: str, service_uuids: list[str]) -> tuple[list[str], list[str]]:
    """Return the kinds (``toothbrush``, ``toothbrush-condor``) and the reasons."""
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
    return kinds, reasons
