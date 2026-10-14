"""Scan, connect, read, and subscribe.

macOS Core Bluetooth has no explicit pair call. A read that needs encryption
makes the system show its pairing dialog. The scale command answers the
Lifesense A3 exchange on 8A81. Sonicare SACP writes stay unsent.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from philips_ble.identify import classify, matches_scale
from philips_ble.scale_link import ScaleStore, run_scale_handshake
from philips_ble.scale_packets import parse_scale_notification
from philips_ble.uuids import (
    BATTERY_LEVEL,
    BATTERY_SERVICE,
    CBT_CHARS,
    CONDOR_SCAN_SERVICE,
    DIS_CHARS,
    DIS_SERVICE,
    SCALE_CHARS,
    SCALE_SERVICES,
    short_of,
)
from philips_ble.values import interpret


@dataclass
class Sighting:
    address: str
    name: str
    rssi: int | None
    service_uuids: list[str]
    kinds: list[str]
    reasons: list[str]
    manufacturer: dict[str, str]
    device: BLEDevice


@dataclass
class Log:
    path: Path | None
    counts: dict[str, int] = field(default_factory=lambda: {"read": 0, "notify": 0, "info": 0})
    touched: float = 0.0
    _hinted: bool = False

    def event(self, kind: str, **payload: Any) -> None:
        self.touched = time.monotonic()
        self.counts[kind] = self.counts.get(kind, 0) + 1
        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": kind,
            **payload,
        }
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._print(record)

    def _print(self, record: dict) -> None:
        event = record["event"]
        if event == "info":
            message = record.get("message") or ""
            if message:
                print(message)
            return
        title = record.get("name") or record.get("uuid") or event
        print(f"\n[{event}] {title}")
        value = record.get("value") or {}
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, dict):
                    print(f"  {key}:")
                    for inner, inner_value in item.items():
                        print(f"    {inner}: {inner_value}")
                else:
                    print(f"  {key}: {item}")
        elif "hex" in record:
            print(f"  {record['hex']}")

    def encryption_hint(self, exc: BaseException) -> None:
        text = str(exc).lower()
        if self._hinted or not any(word in text for word in ("encrypt", "auth", "pair", "insufficient")):
            return
        self._hinted = True
        self.event(
            "info",
            message=(
                "macOS pairs when a read needs encryption. Accept the system dialog if it appears. "
                "This read will be tried once more."
            ),
        )


def _name_of(device: BLEDevice, adv) -> str:
    return (adv.local_name if adv is not None and adv.local_name else None) or device.name or ""


async def discover(seconds: float) -> list[Sighting]:
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    sightings: list[Sighting] = []
    pairs = found.values() if isinstance(found, dict) else ((device, None) for device in found)
    for device, adv in pairs:
        uuids = list(adv.service_uuids) if adv is not None else []
        name = _name_of(device, adv)
        kinds, reasons = classify(name, uuids)
        manufacturer = {}
        rssi = None
        if adv is not None:
            rssi = adv.rssi
            manufacturer = {f"{company:04x}": blob.hex(" ") for company, blob in adv.manufacturer_data.items()}
        sightings.append(
            Sighting(
                address=device.address,
                name=name,
                rssi=rssi,
                service_uuids=uuids,
                kinds=kinds,
                reasons=reasons,
                manufacturer=manufacturer,
                device=device,
            )
        )
    sightings.sort(key=lambda item: (not item.kinds, item.name.lower(), item.address))
    return sightings


def format_sighting(item: Sighting) -> str:
    label = item.name or "(no name)"
    rssi = f"{item.rssi} dBm" if item.rssi is not None else "rssi unknown"
    kind = ", ".join(item.kinds) if item.kinds else "other"
    lines = [f"{item.address}  {label}  {rssi}  {kind}"]
    if item.reasons:
        lines.append("  " + "; ".join(item.reasons))
    if item.service_uuids:
        lines.append("  services: " + ", ".join(item.service_uuids))
    if item.manufacturer:
        rendered = ", ".join(f"{key}:{value}" for key, value in item.manufacturer.items())
        lines.append("  manufacturer: " + rendered)
    return "\n".join(lines)


def _char_name(uuid: str) -> tuple[str, str] | None:
    short = short_of(uuid)
    if short in DIS_CHARS:
        return DIS_CHARS[short]
    if short == BATTERY_LEVEL:
        return ("battery", "battery")
    if short in CBT_CHARS and uuid.lower().startswith("477ea600"):
        return CBT_CHARS[short]
    if short in SCALE_CHARS:
        return (SCALE_CHARS[short], "hex")
    return None


def _scale_family(services) -> str:
    digits = set()
    for service in services:
        short = short_of(service.uuid)
        if short in SCALE_SERVICES:
            digits.add(SCALE_SERVICES[short])
    if "01" in digits:
        return "01"
    if "02" in digits:
        return "02"
    return ""


def _interesting(uuid: str, service_uuid: str, mode: str) -> bool:
    short = short_of(uuid)
    service_short = short_of(service_uuid)
    if short in DIS_CHARS or short == BATTERY_LEVEL:
        return True
    if mode == "scale":
        return service_short in SCALE_SERVICES or short in SCALE_CHARS
    if mode == "brush":
        if uuid.lower().startswith("477ea600"):
            return short in CBT_CHARS
        return service_uuid.lower() == CONDOR_SCAN_SERVICE or service_short in {DIS_SERVICE, BATTERY_SERVICE}
    return False


async def _read(client: BleakClient, uuid: str, log: Log) -> bytes | None:
    try:
        return bytes(await client.read_gatt_char(uuid))
    except Exception as exc:
        log.encryption_hint(exc)
        text = str(exc).lower()
        if any(word in text for word in ("encrypt", "auth", "pair", "insufficient")):
            await asyncio.sleep(8)
            try:
                return bytes(await client.read_gatt_char(uuid))
            except Exception as again:
                log.event("info", message=f"read {uuid} failed: {again}")
                return None
        log.event("info", message=f"read {uuid} failed: {exc}")
        return None


async def _collect(
    client: BleakClient,
    mode: str,
    log: Log,
    seconds: float,
    *,
    store: ScaleStore | None = None,
    user_number: int = 1,
    user_name: str = "User",
    password: bytes | None = None,
    address: str = "",
    age: int | None = None,
    height_cm: int | None = None,
    sex: str | None = None,
    idle_seconds: float | None = None,
) -> None:
    services = client.services
    family = _scale_family(services) if mode == "scale" else ""
    inventory = []
    readable = []
    subscribable = []
    for service in services:
        chars = []
        for char in service.characteristics:
            known = _char_name(char.uuid)
            label = known[0] if known else short_of(char.uuid)
            props = ",".join(char.properties)
            chars.append(f"{char.uuid} [{props}] {label}")
            if not _interesting(char.uuid, service.uuid, mode):
                continue
            if "read" in char.properties:
                readable.append((char, known))
            if "notify" in char.properties or "indicate" in char.properties:
                subscribable.append((char, known))
        inventory.append({"service": service.uuid, "characteristics": chars})
    log.event("info", message="Services:", services=inventory)
    for block in inventory:
        print(f"  {block['service']}")
        for line in block["characteristics"]:
            print(f"    {line}")

    if mode == "scale":
        digit = family or "unknown"
        log.event(
            "info",
            message=(
                f"Scale protocol digit from the advertised services: {digit}. "
                "Step on the scale barefoot and stay on it. "
                "Subscribing, then answering the A3 password or random indication on 8A82."
            ),
        )
    else:
        log.event(
            "info",
            message=(
                "Reading the Sonicare characteristics the manual names, then listening. "
                "SACP and other unresolved writes are not sent."
            ),
        )

    serial = ""
    for char, known in readable:
        data = await _read(client, char.uuid, log)
        if data is None:
            continue
        name, kind = known if known else (short_of(char.uuid), "hex")
        if short_of(char.uuid) == "2a25":
            serial = data.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()
        if mode == "scale" and short_of(char.uuid) in {"8a21", "8a22", "8a24", "a402"}:
            value = parse_scale_notification(short_of(char.uuid), data, family=family, previous=None)
        else:
            value = interpret(kind if known else "hex", data)
        log.event("read", name=name, uuid=char.uuid, value=value)

    previous: dict | None = None
    command_queue: asyncio.Queue[bytes] = asyncio.Queue()

    def on_notify(uuid: str, name: str, data: bytes) -> None:
        nonlocal previous
        if mode == "scale" and short_of(uuid) in {"8a21", "8a22", "8a24", "a402"}:
            value = parse_scale_notification(short_of(uuid), data, family=family, previous=previous)
            if "error" not in value and value.get("packet") in {"a2-weight", "a3-weight", "a2-fat", "a3-append"}:
                previous = value
        else:
            kind = "hex"
            known = _char_name(uuid)
            if known:
                kind = known[1]
            value = interpret(kind, data)
        if mode == "scale" and short_of(uuid) == "8a82" and data:
            command_queue.put_nowait(data)
        log.event("notify", name=name, uuid=uuid, value=value)

    subscribed: list[str] = []
    for char, known in subscribable:
        name = known[0] if known else short_of(char.uuid)
        uuid = char.uuid

        def callback(_sender, data: bytearray, uuid=uuid, name=name) -> None:
            on_notify(uuid, name, bytes(data))

        try:
            await client.start_notify(uuid, callback)
            subscribed.append(uuid)
            log.event("info", message=f"subscribed {name} {uuid}")
        except Exception as exc:
            log.event("info", message=f"subscribe {name} failed: {exc}")

    write_char = next((char for char, _known in subscribable if short_of(char.uuid) == "8a81"), None)
    if write_char is None and mode == "scale":
        for service in services:
            for char in service.characteristics:
                if short_of(char.uuid) == "8a81":
                    write_char = char

    async def write_command(payload: bytes) -> None:
        if write_char is None:
            raise BleakError("characteristic 8A81 is not on this scale")
        await client.write_gatt_char(write_char, payload, response=True)

    try:
        if mode == "scale" and store is not None and write_char is not None:
            await run_scale_handshake(
                write=write_command,
                queue=command_queue,
                store=store,
                device_key=serial or address or "scale",
                user_number=user_number,
                user_name=user_name,
                password_override=password,
                listen_seconds=seconds,
                log=log.event,
                age=age,
                height_cm=height_cm,
                sex=sex,
                release=idle_seconds is None,
            )
        elif mode == "scale":
            log.event("info", message="Characteristic 8A81 was not found, so no command was written.")
            if idle_seconds is None:
                await asyncio.sleep(seconds)
        else:
            if idle_seconds is None:
                await asyncio.sleep(seconds)
        if idle_seconds is not None:
            await _hold_open(client, log, idle_seconds)
    finally:
        for uuid in subscribed:
            try:
                await client.stop_notify(uuid)
            except Exception:
                pass


async def run_scan(seconds: float, show_all: bool) -> int:
    print(f"Scanning for {seconds:g}s.")
    try:
        sightings = await discover(seconds)
    except BleakError as exc:
        print(f"Scan failed: {exc}")
        print("Allow Bluetooth for this terminal in System Settings, Privacy & Security, Bluetooth.")
        return 1
    matches = [item for item in sightings if item.kinds]
    shown = sightings if show_all else matches
    if not shown:
        if show_all:
            print("No advertisements.")
        else:
            print("No scale or Sonicare advertisement in this window.")
            print(f"{len(sightings)} other advertisements were ignored. Re-run with --all to list them.")
        return 1
    for item in shown:
        print(format_sighting(item))
        print()
    if not show_all:
        print(f"{len(matches)} matching, {len(sightings) - len(matches)} other.")
    return 0 if matches or show_all else 1


async def run_collect(
    mode: str,
    address: str | None,
    seconds: float,
    scan_seconds: float,
    out: Path | None,
    *,
    store_path: Path | None = None,
    user_number: int = 1,
    user_name: str = "User",
    password: bytes | None = None,
    age: int | None = None,
    height_cm: int | None = None,
    sex: str | None = None,
) -> int:
    log = Log(out)
    print(f"Scanning for {scan_seconds:g}s to find the {mode}.")
    try:
        sightings = await discover(scan_seconds)
    except BleakError as exc:
        print(f"Scan failed: {exc}")
        print("Allow Bluetooth for this terminal in System Settings, Privacy & Security, Bluetooth.")
        return 1
    wanted = {"scale"} if mode == "scale" else {"toothbrush", "toothbrush-condor"}
    matches = [item for item in sightings if wanted & set(item.kinds)]
    chosen: Sighting | None = None
    if address:
        needle = address.lower()
        chosen = next((item for item in sightings if item.address.lower() == needle), None)
        if chosen is None:
            log.event("info", message=f"{address} was not in this scan. Connecting by address anyway.")
    elif len(matches) == 1:
        chosen = matches[0]
    elif not matches:
        print(f"No {mode} advertisement. Run `python -m philips_ble scan --all` and pass --address.")
        return 1
    else:
        print(f"Several {mode} advertisements. Pass --address.")
        for item in matches:
            print(format_sighting(item))
            print()
        return 1

    target: BLEDevice | str = chosen.device if chosen is not None else address  # type: ignore[assignment]
    label = chosen.address if chosen is not None else address
    log.event("info", message=f"Connecting to {label}.")
    try:
        store = ScaleStore(store_path) if mode == "scale" and store_path is not None else None
        async with BleakClient(target, timeout=40) as client:
            await _collect(
                client,
                mode,
                log,
                seconds,
                store=store,
                user_number=user_number,
                user_name=user_name,
                password=password,
                address=label or "",
                age=age,
                height_cm=height_cm,
                sex=sex,
            )
    except BleakError as exc:
        if log.counts.get("notify"):
            print(f"Link closed: {exc}")
        else:
            print(f"Connect failed: {exc}")
            return 1
    except Exception as exc:
        print(f"Session failed: {type(exc).__name__}: {exc!r}")
        return 1
    reads = log.counts.get("read", 0)
    notes = log.counts.get("notify", 0)
    print(f"\nDone. {reads} reads, {notes} notifications.")
    if out is not None:
        print(f"Wrote {out}")
    return 0


async def _hold_open(client: BleakClient, log: Log, idle_seconds: float) -> None:
    """Stay subscribed until the link drops or nothing new arrives."""
    log.touched = time.monotonic()
    while client.is_connected:
        await asyncio.sleep(1)
        if time.monotonic() - log.touched >= idle_seconds:
            log.event(
                "info",
                message=f"Quiet for {idle_seconds:g}s. Closing the link and watching for the next advertisement.",
            )
            return


def _sighting_from(device: BLEDevice, adv) -> Sighting:
    uuids = list(adv.service_uuids) if adv is not None and adv.service_uuids else []
    name = _name_of(device, adv)
    kinds, reasons = classify(name, uuids)
    manufacturer = {}
    rssi = None
    if adv is not None:
        rssi = adv.rssi
        manufacturer = {f"{company:04x}": blob.hex(" ") for company, blob in adv.manufacturer_data.items()}
    return Sighting(
        address=device.address,
        name=name,
        rssi=rssi,
        service_uuids=uuids,
        kinds=kinds,
        reasons=reasons,
        manufacturer=manufacturer,
        device=device,
    )


async def _wait_for_scale(address: str | None, log: Log) -> Sighting:
    """Return the first advertisement from the scale. Scan stays up until then."""
    loop = asyncio.get_running_loop()
    found: asyncio.Future[Sighting] = loop.create_future()

    def consider(device: BLEDevice, adv) -> None:
        if found.done():
            return
        sighting = _sighting_from(device, adv)
        if not matches_scale(sighting.name, sighting.service_uuids, sighting.address, address or ""):
            return
        found.set_result(sighting)

    def on_detect(device: BLEDevice, adv) -> None:
        loop.call_soon_threadsafe(consider, device, adv)

    scanner = BleakScanner(detection_callback=on_detect)
    await scanner.start()
    try:
        while not found.done():
            await asyncio.wait({found}, timeout=30)
            if not found.done():
                log.event("info", message="Still watching for the scale.")
        return found.result()
    finally:
        await scanner.stop()


async def run_watch(
    address: str | None,
    out: Path | None,
    idle_seconds: float,
    *,
    store_path: Path | None = None,
    user_number: int = 1,
    user_name: str = "User",
    password: bytes | None = None,
    age: int | None = None,
    height_cm: int | None = None,
    sex: str | None = None,
) -> int:
    """Scan until the scale advertises, connect, subscribe, and log every indication."""
    log = Log(out)
    store = ScaleStore(store_path) if store_path is not None else None
    target = address or "any Lifesense scale"
    log.event(
        "info",
        message=(
            f"Watching for {target}. "
            "The listener connects when the scale advertises, subscribes to its indications, "
            "and answers the A3 password or random. Step on whenever you are ready. Ctrl-C stops this."
        ),
    )
    while True:
        try:
            sighting = await _wait_for_scale(address, log)
        except BleakError as exc:
            log.event("info", message=f"Scan failed: {exc}")
            await asyncio.sleep(3)
            continue
        rendered = format_sighting(sighting)
        log.event("info", message=f"Scale advertised.\n{rendered}\nConnecting.")
        try:
            async with BleakClient(sighting.device, timeout=40) as client:
                await _collect(
                    client,
                    "scale",
                    log,
                    idle_seconds,
                    store=store,
                    user_number=user_number,
                    user_name=user_name,
                    password=password,
                    address=sighting.address,
                    age=age,
                    height_cm=height_cm,
                    sex=sex,
                    idle_seconds=idle_seconds,
                )
        except BleakError as exc:
            log.event("info", message=f"Link closed: {exc}")
        except Exception as exc:
            log.event("info", message=f"Session failed: {type(exc).__name__}: {exc!r}")
        notes = log.counts.get("notify", 0)
        log.event("info", message=f"Session ended with {notes} notifications so far. Watching again.")
