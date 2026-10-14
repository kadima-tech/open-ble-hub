"""A3 command exchange on characteristic 8A81.

Byte layouts are from dexdump of the Philips Health app's Lifesense SDK:

- ``Lcom/lifesense/ble/c/d`` builds the frames.
- ``Lcom/lifesense/ble/d/h.a(UUID, UUID, [B)`` classifies 8A82 byte 0:
  0xA0 copies packet bytes 1..4 as the password, 0xA1 copies them as the random.
- ``LsDeviceInfo.k(String)`` and ``o()`` are the same password field.
  ``Lcom/philips/pins/c/h`` saves that string as ``DEVICE_PASSWORD``.
- A fresh pair follows ``d/f.i``. A later sync follows ``d/f.g`` and needs the
  password captured during the pair. This module does not invent a password.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import struct
from datetime import datetime
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
EPOCH = datetime(2010, 1, 1, tzinfo=SHANGHAI)
LOCAL_EPOCH = datetime(2010, 1, 1)

# d/g.b(I, String) rejects 0, -1, a null name, and a name longer than 16 bytes.
DEFAULT_USER_NUMBER = 1
DEFAULT_USER_NAME = "User"


def hex_encode(blob: bytes) -> str:
    """``c/e.d``: uppercase hex, no separators."""
    return blob.hex().upper()


def hex_decode(text: str) -> bytes:
    """``c/e.a(String)``: decode ``0123456789ABCDEF`` pairs."""
    cleaned = text.strip().replace(" ", "")
    if len(cleaned) % 2 or any(ch not in "0123456789ABCDEF" for ch in cleaned.upper()):
        raise ValueError(f"password must be an even hex string, got {text!r}")
    return bytes.fromhex(cleaned)


def broadcast_frame(broadcast_id: bytes) -> bytes:
    """``c/d.a(String)``: ``[0x21]`` plus the 4 stored id bytes."""
    if len(broadcast_id) != 4:
        raise ValueError("broadcast id is 4 bytes")
    return bytes((0x21, *broadcast_id))


def xor_frame(password: bytes, random_bytes: bytes) -> bytes:
    """``c/d.a(String, byte[])``: ``[0x20]`` plus password XOR random, 4 bytes."""
    if len(password) != 4 or len(random_bytes) != 4:
        raise ValueError("password and random are 4 bytes")
    return bytes((0x20, *(left ^ right for left, right in zip(password, random_bytes))))


def bind_user_frame(user_number: int, name: str) -> bytes:
    """``c/d.a(int, String)``: 18 bytes, ``[0x03, user, name..., 0x20...]``."""
    if user_number in (-1, 0) or not 1 <= user_number <= 255:
        raise ValueError("user number must be 1..255")
    raw = name.encode("utf-8")
    if not raw or len(raw) > 16:
        raise ValueError("user name must be 1..16 UTF-8 bytes")
    out = bytearray(18)
    out[0] = 0x03
    out[1] = user_number & 0xFF
    out[2 : 2 + len(raw)] = raw
    for index in range(2 + len(raw), 18):
        out[index] = 0x20
    return bytes(out)


def user_info_fallback(user_number: int) -> bytes:
    """``d/f.i`` when ``d/f.a("02")`` returns null.

    Allocates ``byte[15]``, stores 0x51 at index 0 and 0 at index 1.
    ``d/g`` then writes the user number at index 2 when that number is not 0.
    """
    if user_number in (-1, 0):
        raise ValueError("user number must be non-zero")
    out = bytearray(15)
    out[0] = 0x51
    out[2] = user_number & 0xFF
    return bytes(out)


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def height_centimetres_bytes(height_cm: int) -> bytes:
    """Two bytes from ``c/f.b(F)`` after ``pins/c/i`` divides centimetres by 100f.

    ``SHNLSUserConfigurationConverter`` keeps height as a whole number of
    centimetres, converts it with ``int-to-float`` and ``div-float`` by
    ``100.0f``, and stores that in ``bean/l.f``. ``c/f.b(F)`` formats that
    float with ``DecimalFormat("0.00")``, multiplies by ``100.0f``, and
    truncates toward zero. A result outside -2048..2047 becomes the sentinel
    ``01 00``. A value that fits is packed as ``0xE000 + magnitude`` and
    written little-endian by ``c/f.a(I)``. For a positive magnitude the high
    nibble ``0xE`` is the exponent tag that ``c/f.n`` decodes as 10^-2.
    """
    if not 100 <= height_cm <= 204:
        raise ValueError("height must be 100..204 cm, the range pins/c/i accepts")
    metres = _f32(_f32(height_cm) / _f32(100.0))
    text = format(Decimal(metres).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN), "f")
    parsed = _f32(float(text))
    magnitude = int(_f32(parsed * _f32(100.0)))
    if not -2048 <= magnitude <= 2047:
        raise ValueError(f"height {height_cm} cm does not fit the 11-bit scale field")
    word = 0xE000 + magnitude
    return bytes((word & 0xFF, (word >> 8) & 0xFF))


def sex_code(sex: str) -> int:
    """``bean/l.a(bean/i, boolean)`` with ``isAthlete`` false.

    ``bean/i.b`` is MALE and encodes as 1. ``bean/i.a`` is FEMALE and encodes as 2.
    """
    key = sex.strip().lower()
    if key == "male":
        return 1
    if key == "female":
        return 2
    raise ValueError("sex must be male or female")


def goal_weight_bytes(kg: float) -> bytes:
    """``c/f.a(F)``: digits of ``Float.toString`` as a 3-byte little-endian mantissa, then the decimal exponent."""
    text = f"{float(kg):.1f}"
    mantissa = int(text.replace(".", ""))
    exponent = -(len(text) - 1 - text.index("."))
    return bytes((mantissa & 0xFF, (mantissa >> 8) & 0xFF, (mantissa >> 16) & 0xFF, exponent & 0xFF))


def user_info_frame(
    *,
    user_number: int,
    age: int,
    height_cm: int,
    sex: str,
    activity_level: int = 0,
    goal_kg: float = 0.0,
) -> bytes:
    """``bean/l.a()[B]``, with the user number ``d/g`` writes at index 2.

    Byte 0 is 0x51. Byte 1 is the constant 0xDF from the writer (the same
    value the constructor stores in the flags field). Byte 3 is the sex code.
    Byte 4 is age. Bytes 5..6 are the height. Byte 7 is athlete activity
    level (constructor default 0). Byte 8 is the unit: a null unit
    takes the ``else`` arm of ``bean/l.b(j)`` and encodes as 0, which is
    UNIT_KG. Bytes 9..12 are goal weight. The field defaults to 0.0f, and
    ``c/f.a(F)`` turns ``Float.toString(0.0f)`` (``"0.0"``) into
    ``00 00 00 ff``. Bytes 13..14 stay 0. Waistline is not in this frame.
    Philips ``pins/c/i`` accepts ages 18..100.
    """
    if user_number in (-1, 0) or not 1 <= user_number <= 255:
        raise ValueError("user number must be 1..255")
    if not 18 <= age <= 100:
        raise ValueError("age must be 18..100, the range pins/c/i accepts")
    out = bytearray(15)
    out[0] = 0x51
    out[1] = 0xDF
    out[2] = user_number & 0xFF
    out[3] = sex_code(sex)
    out[4] = age & 0xFF
    out[5:7] = height_centimetres_bytes(height_cm)
    out[7] = activity_level & 0xFF
    out[9:13] = goal_weight_bytes(goal_kg)
    return bytes(out)


def utc_frame(moment: datetime | None = None) -> bytes:
    """``c/d.b()``: ``[0x02]`` plus ``c/f.a(J)`` little-endian seconds.

    The payload is seconds from 2010-01-01 00:00:00 to the phone's local
    wall-clock time, both read as naive times. The SDK formats the wall-clock
    fields and parses them as Asia/Shanghai, so the zone cancels out. A Pixel
    HCI capture of PHS Health (2026-10-13) wrote ``02 75 50 91 1f`` at 19:50:20
    CEST, which is this value to within the capture delay.
    """
    when = moment or datetime.now()
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    seconds = int((when - LOCAL_EPOCH).total_seconds())
    if seconds < 0:
        seconds = 0
    return bytes((0x02, seconds & 0xFF, (seconds >> 8) & 0xFF, (seconds >> 16) & 0xFF, (seconds >> 24) & 0xFF))


def disconnect_frame() -> bytes:
    """``c/d.c()``."""
    return bytes((0x22,))


def command_field(packet: bytes) -> tuple[str, bytes] | None:
    """Return ``("password"|"random", 4 bytes)`` for an 8A82 indication."""
    if len(packet) < 5:
        return None
    if packet[0] == 0xA0:
        return ("password", bytes(packet[1:5]))
    if packet[0] == 0xA1:
        return ("random", bytes(packet[1:5]))
    return None


class ScaleStore:
    """Local stand-in for the Philips ``DEVICE_PASSWORD`` preference."""

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, Any] = {"devices": {}}
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("devices"), dict):
                self._data = loaded

    def get(self, key: str) -> dict[str, Any] | None:
        item = self._data["devices"].get(key)
        return dict(item) if isinstance(item, dict) else None

    def put(self, key: str, record: dict[str, Any]) -> None:
        self._data["devices"][key] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2) + "\n", encoding="utf-8")


def new_broadcast_id() -> bytes:
    """Same role as ``c/d.a()``: 4 bytes from ``Random.nextInt()``, big-endian there."""
    return secrets.token_bytes(4)


async def _take(queue: asyncio.Queue[bytes], opcode: int, timeout: float) -> bytes | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None
        try:
            packet = await asyncio.wait_for(queue.get(), remaining)
        except TimeoutError:
            return None
        if packet and packet[0] == opcode and len(packet) >= 5:
            return bytes(packet)
    return None


async def run_scale_handshake(
    *,
    write,
    queue: asyncio.Queue[bytes],
    store: ScaleStore,
    device_key: str,
    user_number: int,
    user_name: str,
    password_override: bytes | None,
    listen_seconds: float,
    log: Callable[..., None],
    sleep=asyncio.sleep,
    age: int | None = None,
    height_cm: int | None = None,
    sex: str | None = None,
    release: bool = True,
) -> None:
    """Answer the scale, then keep the connection open so a weigh can arrive.

    ``write`` sends one command to 8A81 and returns when the write completes.
    ``log`` is ``Log.event``.
    """
    try:
        first = await asyncio.wait_for(queue.get(), 12)
    except TimeoutError:
        log(
            "info",
            message=(
                "No command indication on 8A82. Wake the scale and run this again. "
                "Hold the unit button for 3 seconds to enter pairing."
            ),
        )
        return

    kind = command_field(first)
    saved = store.get(device_key) or {}
    password = password_override or (hex_decode(saved["password"]) if saved.get("password") else None)
    profile = _profile(age, height_cm, sex) or _profile(
        saved.get("age"), saved.get("height_cm"), saved.get("sex")
    )

    answered = False
    if kind and kind[0] == "password":
        password = kind[1]
        log("info", message=f"Scale sent a pairing password ({hex_encode(password)}). Starting the A3 pair queue.")
        answered = await _pair(
            write=write,
            queue=queue,
            store=store,
            device_key=device_key,
            saved=saved,
            password=password,
            user_number=user_number,
            user_name=user_name,
            profile=profile,
            log=log,
        )
    elif kind and kind[0] == "random":
        if password is None:
            log(
                "info",
                message=(
                    "The scale sent a sync random and no password. It is already paired, "
                    "and the password is the one the Philips app stored as DEVICE_PASSWORD. "
                    "This Mac does not have it, so no command was written. "
                    "Hold the measurement-unit button on the scale for 3 seconds until the "
                    "pairing symbols show, then run this command again. "
                    "The scale then sends the password and this client can finish the exchange. "
                    "Or pass --password with the 8 hex digits from the phone."
                ),
            )
            return
        log("info", message="Scale sent a sync random. Answering with the stored password.")
        await _sync(
            write=write,
            queue=queue,
            random_bytes=kind[1],
            broadcast_id=hex_decode(saved["broadcast_id"]) if saved.get("broadcast_id") else None,
            password=password,
            user_number=saved.get("user_number", user_number),
            profile=profile,
            log=log,
            saved=saved,
        )
        if profile is not None:
            store.put(device_key, {**saved, **_profile_record(*profile), "user_number": user_number, "user_name": user_name})
        answered = True
    else:
        log("info", message=f"8A82 indication was not a password or random packet: {first.hex(' ')}")
        return

    if not answered:
        if not release:
            log("info", message="Link stays open. Indications will be logged until the scale drops it.")
        return
    if kind and kind[0] == "password":
        # d/g.i: once UTC is acknowledged, only the blood-pressure protocol
        # (d/a.d) parks before the disconnect step. A3 writes 0x22 straight
        # away, and the link drop that follows is "Done!the pairing is successful."
        try:
            await _send(write, disconnect_frame(), "disconnect", log)
        except Exception as exc:
            log("info", message=f"Disconnect write ended the link: {exc}")
        log(
            "info",
            message=(
                "Pairing finished with 0x22. The scale drops the link and reconnects in sync mode. "
                "Step on barefoot for the first weigh."
            ),
        )
        return
    if not release:
        # PHS Health writes 0x22 right after the 0xC0 exchange. The scale keeps
        # the link and sends the measurement later, so the caller holds the link.
        try:
            await _send(write, disconnect_frame(), "disconnect", log)
        except Exception as exc:
            log("info", message=f"Disconnect write ended the link: {exc}")
        return
    log("info", message="Handshake sent. Step on the scale barefoot. Listening for weight.")
    await sleep(listen_seconds)
    try:
        await _send(write, disconnect_frame(), "disconnect", log)
    except Exception as exc:
        log("info", message=f"Disconnect write ended the link: {exc}")


def _profile(age: Any, height_cm: Any, sex: Any) -> tuple[int, int, str] | None:
    if age is None and height_cm is None and sex is None:
        return None
    if age is None or height_cm is None or sex is None:
        raise ValueError("age, height, and sex are set together")
    return (int(age), int(height_cm), str(sex))


def _profile_record(age: int, height_cm: int, sex: str) -> dict[str, Any]:
    return {"age": age, "height_cm": height_cm, "sex": sex.strip().lower()}


def _user_info(user_number: int, profile: tuple[int, int, str] | None, saved: dict[str, Any] | None = None) -> bytes:
    if profile is None:
        return user_info_fallback(user_number)
    age, height_cm, sex = profile
    extra = saved or {}
    return user_info_frame(
        user_number=user_number,
        age=age,
        height_cm=height_cm,
        sex=sex,
        activity_level=int(extra.get("activity_level", 0)),
        goal_kg=float(extra.get("goal_kg", 0.0)),
    )


async def _pair(*, write, queue, store, device_key, saved, password, user_number, user_name, profile, log) -> bool:
    broadcast = hex_decode(saved["broadcast_id"]) if saved.get("broadcast_id") else new_broadcast_id()
    record = {
        **saved,
        "password": hex_encode(password),
        "broadcast_id": hex_encode(broadcast),
        "user_number": user_number,
        "user_name": user_name,
    }
    if profile is not None:
        record.update(_profile_record(*profile))
    store.put(device_key, record)
    await _send(write, broadcast_frame(broadcast), "broadcast id", log)
    random_packet = await _take(queue, 0xA1, 10)
    if random_packet is None:
        log("info", message="Pairing stopped: no random indication after the broadcast id.")
        return False
    random_bytes = random_packet[1:5]
    await _send(write, xor_frame(password, random_bytes), "xor", log)
    # d/g.i stops after the XOR ("waiting for write user id...") until the app
    # binds a slot. d/g.d collects one 0x83 per slot and hands the list over
    # once maxUserNumber entries have arrived. d/g.c(I) only accepts a bind
    # for a user number that is in that list.
    slots = await _user_list(queue, log)
    if slots and user_number not in slots:
        log("info", message=f"User {user_number} is not in the scale's slot list {sorted(slots)}. Bind not sent.")
        return False
    await _send(write, bind_user_frame(user_number, user_name), "bind user", log)
    await _send(write, _user_info(user_number, profile, saved), "user info", log)
    await _send(write, utc_frame(), "utc", log)
    log(
        "info",
        message=(f"Saved password and broadcast id for {device_key} in the local store."),
    )
    return True


MAX_USERS = 8
USER_INFO_WAIT_SECONDS = 3.0


def user_slot(packet: bytes) -> tuple[int, str] | None:
    """``c/f.g`` / ``c/f.h`` on a ``0x83`` packet: slot at index 1, name from index 2, spaces trimmed."""
    if len(packet) < 2 or packet[0] != 0x83:
        return None
    name = bytes(packet[2:18]).split(b"\x00", 1)[0].decode("utf-8", "replace").strip()
    return packet[1], name


async def _user_list(queue: asyncio.Queue[bytes], log, quiet: float = 3.0) -> dict[int, str]:
    """Collect ``0x83`` slots until all of them arrived or the scale goes quiet."""
    slots: dict[int, str] = {}
    while len(slots) < MAX_USERS:
        try:
            packet = await asyncio.wait_for(queue.get(), quiet)
        except TimeoutError:
            break
        slot = user_slot(packet)
        if slot is not None:
            slots[slot[0]] = slot[1]
    if slots:
        rendered = ", ".join(f"{number}:{name or '-'}" for number, name in sorted(slots.items()))
        log("info", message=f"Scale user slots: {rendered}")
    else:
        log("info", message="No 0x83 user list after the XOR. Binding anyway.")
    return slots


async def _sync(*, write, queue, random_bytes, password, broadcast_id, user_number, profile, log, saved=None) -> None:
    """Sync as PHS Health does it on the wire (Pixel HCI capture, 2026-10-13).

    XOR, broadcast id (``OPERATING_WRITE_BROADCAST_ID_ON_SYNC``), UTC. A scale
    that knows the broadcast id answers with a ``0xC0`` user-info indication
    and lights its Bluetooth symbol. The app then writes the profile and
    ``0x22``. The scale keeps the link up after that ``0x22`` and sends the
    measurement on 8A24 / 8A22 once the weigh finishes.
    """
    await _send(write, xor_frame(password, random_bytes), "xor", log)
    if broadcast_id is not None:
        await _send(write, broadcast_frame(broadcast_id), "broadcast id", log)
    await _send(write, utc_frame(), "utc", log)
    reply = await _take(queue, 0xC0, USER_INFO_WAIT_SECONDS)
    if reply is None:
        log("info", message="No 0xC0 user info after the UTC. The scale did not recognise this broadcast id.")
    else:
        log("info", message=f"Scale recognised the user: {reply[:7].hex(' ')}")
        if profile is not None:
            await _send(write, _user_info(user_number, profile, saved), "user info", log)


async def _send(write, payload: bytes, label: str, log) -> None:
    log("info", message=f"Write {label} to 8A81: {payload.hex(' ')}")
    await write(payload)
