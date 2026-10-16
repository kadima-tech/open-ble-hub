"""UUIDs and names named in the Bond Touch protocol manual.

Every Bond UUID is ``d3c0XXXX-add3-1d4b-000Y-0000b5006bb1``. The fourth
group is ``0000`` for some characteristics and ``0001`` for others, so each
one is spelled out here (BleBondClientKt, BondBleConstants). Comparison is
case-insensitive.
"""

from __future__ import annotations

BOND_BASE = "d3c0{short}-add3-1d4b-{group}-0000b5006bb1"
BOND_TAIL = "-0000b5006bb1"
BLUETOOTH_BASE = "0000{short}-0000-1000-8000-00805f9b34fb"


def bond(short: str, group: str = "0000") -> str:
    return BOND_BASE.format(short=short.lower(), group=group)


def sig(short: str) -> str:
    return BLUETOOTH_BASE.format(short=short.lower())


# Services. V1, V2, V4 and Mini use INFO and CONTROL; V3 (Bond More) uses V3.
INFO_SERVICE = bond("0001")
CONTROL_SERVICE = bond("0002", "0001")
V3_SERVICE = bond("0003")
DEVICE_INFORMATION_SERVICE = sig("180a")
BATTERY_SERVICE = sig("180f")

# INFO_SERVICE
API_VERSION = bond("ff10")  # one byte; picks the generation
V1_FIRMWARE = bond("ff03")  # V1 only: [patch, minor] -> 1.minor.patch
BATTERY = bond("ff06")  # V1: u16 LE millivolts. Others: [percent, reserved]

# CONTROL_SERVICE
TOKEN = bond("ffa1", "0001")
AUID = bond("ffa2", "0001")
STATE = bond("ffa4", "0001")
EVENT = bond("ffa5", "0001")
COMMAND = bond("ffa6", "0001")
V1_RESULT = bond("ffa7", "0001")  # V1 only: per-command result
BOND_TRIGGER = bond("ffa8", "0001")  # V4, Mini: subscribing starts OS bonding

# V3_SERVICE
V3_COMMAND = bond("ffb1")  # commands and every V3 event
V3_TOUCH = bond("ffb2")  # touch patterns, both directions
V3_API_VERSION = bond("ffb3")  # logged by the app, otherwise unused

# Standard characteristics the app reads.
FIRMWARE_REVISION = sig("2a26")  # UTF-8, e.g. "2.7.9"
MODEL_NUMBER = sig("2a24")
BATTERY_LEVEL = sig("2a19")  # V3
CCCD = sig("2902")

# Advertised names the app's scan filters take (BleBondScanHelper), and the
# names a bracelet uses in its bootloader (BondBleConstants).
NAMES = ("BOND", "Bond More", "BOND 4", "BOND MINI")
DFU_NAMES = ("BOND_DFU", "BOND_M_DFU", "BOND_4_DFU", "BOND_MINI_DFU")
