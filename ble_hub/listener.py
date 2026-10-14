"""Always-on Bluetooth listener for the Philips DL8780 scale.

Scans until the scale advertises, connects, answers the A3 handshake from
``philips_ble.scale_link`` and hands each measurement to the hub. A scale in
pairing mode (advertised name starting with ``1``, ``0xA0`` password packet)
is only paired while the pairing window opened from the UI is active.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date
from pathlib import Path
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from philips_ble.scale_link import ScaleStore, command_field, run_scale_handshake
from philips_ble.scale_packets import parse_a3_append, parse_a3_weight
from philips_ble.uuids import SCALE_SERVICES, sig

from ble_hub.bodycomp import age_on
from ble_hub.hub import Hub

SERIAL_CHAR = sig("2a25")
WEIGHT_CHAR = sig("8a24")
APPEND_CHAR = sig("8a22")
COMMAND_IN = sig("8a82")
COMMAND_OUT = sig("8a81")
SCALE_SERVICE_UUIDS = {sig(short) for short in SCALE_SERVICES}
IDLE_SECONDS = 45
NEARBY_SECONDS = 90
APPEND_WAIT_SECONDS = 3
HUB_USER_NAME = "Hub"


def looks_like_scale(name: str, service_uuids: list[str]) -> bool:
    lowered = {uuid.lower() for uuid in service_uuids}
    return "dl8780" in (name or "").lower() or bool(lowered & SCALE_SERVICE_UUIDS)


class ScaleListener:
    def __init__(self, hub: Hub, data_dir: Path):
        self.hub = hub
        self.store = ScaleStore(data_dir / "scale.json")
        self.state = "starting"
        self.last_seen: float | None = None
        self.last_error: str | None = None
        self.pairing_until: float = 0.0
        self.last_pair_result: str | None = None
        self.nearby: dict[str, dict[str, Any]] = {}
        self.pairing_request_at: float = 0.0

    # -- status / pairing --------------------------------------------------
    @property
    def address(self) -> str | None:
        return self.hub.db.get_setting("scale_address")

    def paired_record(self) -> dict[str, Any] | None:
        serial = self.hub.db.get_setting("scale_serial")
        record = self.store.get(serial) if serial else None
        return record if record and record.get("password") and record.get("broadcast_id") else None

    def pairing_active(self) -> bool:
        return time.time() < self.pairing_until

    def start_pairing(self, seconds: int = 180) -> None:
        self.pairing_until = time.time() + seconds
        self.last_pair_result = None
        self.hub.db.log(f"Pairing window open for {seconds} s. Hold the unit button on the scale for 3 s.")

    def forget(self) -> None:
        """Drop the stored pairing so the hub stops answering this scale until it is paired again."""
        serial = self.hub.db.get_setting("scale_serial")
        if serial:
            self.store.put(serial, {})
        self.hub.db.set_setting("scale_serial", None)
        self.hub.db.set_setting("scale_address", None)
        self.last_pair_result = None
        self.hub.db.log("Scale forgotten. Pair it again to receive weighs.")

    def nearby_devices(self) -> list[dict[str, Any]]:
        """Scales advertised in the last NEARBY_SECONDS, newest first."""
        cutoff = time.time() - NEARBY_SECONDS
        recent_request = time.time() - self.pairing_request_at < NEARBY_SECONDS
        found = []
        for entry in self.nearby.values():
            if entry["seen"] < cutoff:
                continue
            item = dict(entry)
            item["pairing_mode"] = entry["pairing_mode"] or (recent_request and entry["address"] == self.address)
            found.append(item)
        return sorted(found, key=lambda item: item["seen"], reverse=True)

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "address": self.address,
            "paired": self.paired_record() is not None,
            "pairing": self.pairing_active(),
            "pairing_seconds_left": max(0, int(self.pairing_until - time.time())),
            "last_pair_result": self.last_pair_result,
            "last_seen": self.last_seen,
            "last_error": self.last_error,
            "nearby": self.nearby_devices(),
        }

    def _scale_profile(self) -> tuple[int, int, str]:
        """Profile written to the scale's slot. The hub recomputes composition per person, so any valid one works."""
        profiles = self.hub.db.profiles()
        if profiles:
            first = profiles[0]
            age = min(100, max(18, age_on(date.fromisoformat(first["birth_date"]), date.today())))
            height = int(min(204, max(100, round(first["height_cm"]))))
            return age, height, first["sex"]
        return 35, 175, "male"

    # -- main loop -----------------------------------------------------------
    async def run(self) -> None:
        while True:
            try:
                self.state = "scanning"
                device = await self._wait_for_scale()
                self.last_seen = time.time()
                self.state = "connected"
                await self._session(device)
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except (BleakError, asyncio.TimeoutError, OSError) as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.hub.db.log(f"Bluetooth: {self.last_error}", "warn")
                await asyncio.sleep(3)
            except Exception as exc:  # keep listening whatever happens in one session
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.hub.db.log(f"Listener error: {self.last_error}", "error")
                await asyncio.sleep(5)
            finally:
                self.state = "scanning"

    async def _wait_for_scale(self) -> BLEDevice:
        loop = asyncio.get_running_loop()
        found: asyncio.Future[BLEDevice] = loop.create_future()
        known = (self.address or "").lower()

        def on_detect(device: BLEDevice, adv) -> None:
            if found.done():
                return
            name = (adv.local_name if adv else None) or device.name or ""
            uuids = list(adv.service_uuids) if adv and adv.service_uuids else []
            if (known and device.address.lower() == known) or looks_like_scale(name, uuids):
                # DL8780 advertises as 1DL87801 while it waits to be paired, 0DL87801 otherwise.
                self.nearby[device.address] = {
                    "address": device.address,
                    "name": name,
                    "model": "DL8780",
                    "rssi": getattr(adv, "rssi", None),
                    "seen": time.time(),
                    "pairing_mode": name.startswith("1"),
                }
                found.set_result(device)

        scanner = BleakScanner(detection_callback=lambda d, a: loop.call_soon_threadsafe(on_detect, d, a))
        await scanner.start()
        try:
            return await found
        finally:
            await scanner.stop()

    async def _session(self, device: BLEDevice) -> None:
        async with BleakClient(device, timeout=30) as client:
            if device.address != self.address:
                self.hub.db.set_setting("scale_address", device.address)
            serial = bytes(await client.read_gatt_char(SERIAL_CHAR)).split(b"\0", 1)[0].decode("ascii", "replace").strip()
            if serial:
                self.hub.db.set_setting("scale_serial", serial)

            loop = asyncio.get_running_loop()
            commands: asyncio.Queue[bytes] = asyncio.Queue()
            touched = [time.monotonic()]
            pending_weight: list[tuple[dict, bytes] | None] = [None]

            def on_command(_sender, data: bytearray) -> None:
                touched[0] = time.monotonic()
                commands.put_nowait(bytes(data))

            def on_weight(_sender, data: bytearray) -> None:
                touched[0] = time.monotonic()
                raw = bytes(data)
                parsed = parse_a3_weight(raw)
                if "error" in parsed:
                    self.hub.db.log(f"Unreadable weight packet {raw.hex(' ')}", "warn")
                    return
                if parsed.get("has_append_measurement"):
                    pending_weight[0] = (parsed, raw)
                    loop.call_later(APPEND_WAIT_SECONDS, flush_weight)
                else:
                    self.hub.ingest(parsed, None, raw, None)

            def flush_weight() -> None:
                if pending_weight[0] is not None:
                    parsed, raw = pending_weight[0]
                    pending_weight[0] = None
                    self.hub.ingest(parsed, None, raw, None)

            def on_append(_sender, data: bytearray) -> None:
                touched[0] = time.monotonic()
                raw = bytes(data)
                appended = parse_a3_append(raw)
                if pending_weight[0] is None:
                    return
                parsed, raw_weight = pending_weight[0]
                pending_weight[0] = None
                self.hub.ingest(parsed, appended if "error" not in appended else None, raw_weight, raw)

            await client.start_notify(WEIGHT_CHAR, on_weight)
            await client.start_notify(APPEND_CHAR, on_append)
            await client.start_notify(COMMAND_IN, on_command)

            first = await asyncio.wait_for(commands.get(), 12)
            kind = command_field(first)
            pairing = bool(kind and kind[0] == "password")
            if pairing and not self.pairing_active():
                self.pairing_request_at = time.time()
                self.hub.db.log("The scale is in pairing mode. Open the pairing window in the UI first.", "warn")
                return
            if not pairing and self.paired_record() is None:
                self.hub.db.log("The scale is paired to another app. Pair it with the hub from the UI.", "warn")
                return

            handshake_queue: asyncio.Queue[bytes] = asyncio.Queue()
            handshake_queue.put_nowait(first)
            while not commands.empty():
                handshake_queue.put_nowait(commands.get_nowait())

            def forward(_sender, data: bytearray) -> None:
                touched[0] = time.monotonic()
                handshake_queue.put_nowait(bytes(data))

            await client.stop_notify(COMMAND_IN)
            await client.start_notify(COMMAND_IN, forward)

            async def write(payload: bytes) -> None:
                await client.write_gatt_char(COMMAND_OUT, payload, response=True)

            messages: list[str] = []

            def log(kind_: str, **payload: Any) -> None:
                if payload.get("message"):
                    messages.append(payload["message"])

            age, height, sex = self._scale_profile()
            await run_scale_handshake(
                write=write,
                queue=handshake_queue,
                store=self.store,
                device_key=serial or device.address,
                user_number=1,
                user_name=HUB_USER_NAME,
                password_override=None,
                listen_seconds=0,
                log=log,
                age=age,
                height_cm=height,
                sex=sex,
                release=False,
            )
            if pairing:
                self.pairing_until = 0.0
                self.last_pair_result = "paired" if self.paired_record() else "failed"
                self.hub.db.log("Scale paired with the hub." if self.last_pair_result == "paired" else "Pairing did not complete: " + "; ".join(messages[-2:]),
                                "info" if self.last_pair_result == "paired" else "error")
                return
            if not any("recognised the user" in message for message in messages):
                self.hub.db.log("The scale did not recognise the hub. Pair it again from the UI.", "warn")

            touched[0] = time.monotonic()
            while client.is_connected and time.monotonic() - touched[0] < IDLE_SECONDS:
                await asyncio.sleep(1)
            flush_weight()
