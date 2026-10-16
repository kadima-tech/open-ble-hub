"""Colours as ``(red, green, blue)`` tuples, and the ARGB ints the app sends.

The app keeps colours as Android ARGB ints. V2 config writes send them as a
big-endian u32 (``AA RR GG BB``); V1 writes them little-endian.
"""

from __future__ import annotations

RGB = tuple[int, int, int]

BLACK: RGB = (0, 0, 0)
RED: RGB = (0xFF, 0, 0)
GREEN: RGB = (0, 0xFF, 0)


def rgb(value: str | int | tuple[int, int, int]) -> RGB:
    """``"#23E0E8"``, ``"23e0e8"``, ``0x23E0E8`` or ``(0x23, 0xE0, 0xE8)`` -> a tuple."""
    if isinstance(value, str):
        text = value.removeprefix("#")
        if len(text) != 6:
            raise ValueError(f"not an RRGGBB colour: {value!r}")
        value = int(text, 16)
    if isinstance(value, int):
        if not 0 <= value <= 0xFFFFFF:
            raise ValueError(f"not an RRGGBB colour: {value:#x}")
        return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
    red, green, blue = value
    for channel in (red, green, blue):
        if not 0 <= channel <= 0xFF:
            raise ValueError(f"colour channels are 0..255, got {value!r}")
    return (red, green, blue)


def argb(colour: RGB, alpha: int = 0xFF) -> int:
    """The Android colour int, opaque by default."""
    red, green, blue = rgb(colour)
    return alpha << 24 | red << 16 | green << 8 | blue


def blend(start: RGB, end: RGB, fraction: float) -> RGB:
    """Linear blend from ``start`` (0.0) to ``end`` (1.0)."""
    fraction = min(max(fraction, 0.0), 1.0)
    red, green, blue = (
        round(a + (b - a) * fraction) for a, b in zip(start, end, strict=True)
    )
    return (red, green, blue)
