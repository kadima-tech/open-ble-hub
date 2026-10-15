"""Model codes and function letters the app's Java code confirms.

The full code -> product -> range table is an encrypted config the app
downloads; it is not here. Ask the toy with ``GetCap;`` instead.
"""

from __future__ import annotations

# DeviceType code -> product, from com.wear.ext.j1 and k9.b (ToyCode).
MODELS = {
    "s": "Lush",
    "b": "Max",
    "w": "Domi",
    "q": "Tenera",
    "ba": "Solace Pro",
    "be": "B12A",  # internal name; retail name not confirmed
    "ca": "Mission 2",
    "wd": "Spinel",
    "qb": "Fizz",
    "kd": "Valor",
    "f": "Sex Machine",
    "fs": "Mini Sex Machine",
}

# Function letter -> (function, text command, highest level the command takes).
# Levels start at 0, which stops the function. Letters are the ones GetCap and
# the config use (OldToyBean.TOY_OPERATION). Depth takes 0..3 on the wire even
# though the config's default max is 20; see depth_level.
FUNCTIONS = {
    "v": ("vibrate", "Vibrate", 20),
    "v1": ("vibrate motor 1", "Vibrate1", 20),
    "v2": ("vibrate motor 2", "Vibrate2", 20),
    "v3": ("vibrate motor 3", "Vibrate3", 20),
    "r": ("rotate", "Rotate", 20),
    "p": ("air pump", "Air:Level", 3),
    "s": ("suction", "suck", 20),
    "t": ("thrusting", "Thrusting", 20),
    "f": ("fingering", "Finger", 20),
    "d": ("depth", "Depth", 3),
    "o": ("oscillate", "Slap", 20),
    "q": ("bumping", "Bumping", 20),
    "m": ("squirt", "Squirt", 20),
    "pos": ("stroke position", "FSetSite", 100),
}


def depth_level(ui_level: int) -> int:
    """Map a 0..20 level onto ``Depth``'s 0..3 the way the app does."""
    if not 0 <= ui_level <= 20:
        raise ValueError("level must be 0..20")
    if ui_level == 0:
        return 0
    if ui_level <= 7:
        return 1
    if ui_level <= 14:
        return 2
    return 3
