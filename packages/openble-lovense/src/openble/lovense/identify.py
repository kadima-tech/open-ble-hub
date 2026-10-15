"""Read the identity UUID and match an advertisement to a Lovense toy."""

from __future__ import annotations

from dataclasses import dataclass

from openble.lovense.uuids import IDENTITY_SUFFIX, IDENTITY_TAIL, swap_halves


@dataclass(frozen=True)
class Identity:
    """What the advertised identity UUID ``XXYY00PP-VVVV-4BD4-BBD5-A6920E4C5653`` says."""

    model: str  # lower case, the key the app's catalogue uses
    # The VVVV group. The app reads it as the firmware version, but a Max on
    # firmware 223 advertises 0x0023, so ask ``DeviceType;`` for the firmware.
    uuid_version: int
    pin_set: bool


def parse_identity(uuid: str) -> Identity | None:
    """Decode an identity UUID as the app does (r9.b), or None for any other uuid.

    Model = chr(XX) + chr(YY) unless YY is ``0``. ``uuid_version`` =
    int(VVVV, 16). PP ``11`` means the owner set a PIN.
    """
    text = uuid.lower()
    if len(text) != 36 or not text.endswith(IDENTITY_TAIL):
        return None
    try:
        first, second = int(text[0:2], 16), int(text[2:4], 16)
        version = int(text[9:13], 16)
    except ValueError:
        return None
    if not chr(first).isalnum():
        return None
    model = chr(first)
    if chr(second) != "0":
        if not chr(second).isalnum():
            return None
        model += chr(second)
    return Identity(
        model=model.lower(), uuid_version=version, pin_set=text[6:8] == "11"
    )


def identity_of(service_uuids: list[str]) -> Identity | None:
    """The first identity found among the advertised uuids, in either half order."""
    for uuid in service_uuids:
        for candidate in (uuid, _swapped(uuid)):
            if candidate and (identity := parse_identity(candidate)):
                return identity
    return None


def classify(name: str, service_uuids: list[str]) -> tuple[list[str], list[str]]:
    """Return ``(["toy"], reasons)`` for a Lovense toy, else empty lists.

    An identity UUID in either half order is enough; a Max sends it in the
    standard order. Failing that, the app accepts a name starting ``lvs``.
    Bootloader names (``dfu``, ``new``) are not matched: other devices use
    them too.
    """
    reasons: list[str] = []
    for uuid in service_uuids:
        for candidate in (uuid, _swapped(uuid)):
            if candidate and candidate.lower().endswith(IDENTITY_SUFFIX):
                identity = parse_identity(candidate)
                label = f"model {identity.model}" if identity else candidate.lower()
                reasons.append(f"service …{IDENTITY_SUFFIX} ({label})")
                break
    if name.lower().startswith("lvs"):
        reasons.append(f"name {name}")
    return (["toy"] if reasons else []), reasons


def _swapped(uuid: str) -> str:
    try:
        return swap_halves(uuid)
    except ValueError:
        return ""
