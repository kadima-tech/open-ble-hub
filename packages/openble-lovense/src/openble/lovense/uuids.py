"""UUIDs named in the Lovense protocol manual.

Most toys have no fixed control UUID: ``link.pick_channels`` chooses them by
characteristic properties. Comparison is case-insensitive.
"""

from __future__ import annotations

# Every identity UUID ends in this. r9.b (UuidDeviceUtils) and ToyBtDXManager
# accept a scan result whose 128-bit service UUID ends with it.
IDENTITY_SUFFIX = "-bbd5-a6920e4c5653"
# The full tail of the identity layout XXYY00PP-VVVV-4BD4-BBD5-A6920E4C5653.
IDENTITY_TAIL = "-4bd4" + IDENTITY_SUFFIX

CCCD = "00002902-0000-1000-8000-00805f9b34fb"

# Model code -> (service, TX, RX) the app pins instead of the property rule
# (k9.b.c.f51075i). Only "be" (internal name B12A) is pinned in 8.10.1.
PINNED_CHANNELS = {
    "be": (
        "42450001-0023-4bd4-bbd5-a6920e4c5653",
        "42450002-0023-4bd4-bbd5-a6920e4c5653",
        "42450003-0023-4bd4-bbd5-a6920e4c5653",
    ),
}


def swap_halves(uuid: str) -> str:
    """Swap the two 64-bit halves of a UUID string.

    The app's scan-record parser (r9.b.g) reads a 128-bit UUID as two
    little-endian 64-bit words, the first taken as the most-significant half.
    A standard decoder, bleak included, reverses all 16 bytes. The two results
    differ by exactly this swap, so match both.
    """
    digits = uuid.replace("-", "").lower()
    if len(digits) != 32:
        raise ValueError(f"not a 128-bit uuid: {uuid!r}")
    swapped = digits[16:] + digits[:16]
    return "-".join(
        (swapped[:8], swapped[8:12], swapped[12:16], swapped[16:20], swapped[20:])
    )
