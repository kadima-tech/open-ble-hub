"""Drive the Bluetooth modules against bleak's real signatures, with no radio.

A Pi or Mac smoke test is still required when bleak itself changes.
See CONTRIBUTING.md.
"""

from __future__ import annotations

import asyncio
import inspect
import io
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import get_args
from unittest.mock import create_autospec, patch

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData, AdvertisementDataCallback
from bleak.backends.service import BleakGATTService, BleakGATTServiceCollection
from bleak.exc import BleakError

from bathroom_hub.db import Database
from bathroom_hub.hub import Hub
from bathroom_hub.listener import COMMAND_IN, COMMAND_OUT, ScaleListener
from ble_probe.session import run_collect, run_scan, run_watch
from openble.lifesense.link import ScaleStore
from openble.lifesense.uuids import sig

# Captured from the DL8780 on 2026-10-13 (same bytes as test_bathroom_hub).
WEIGHT_RAW = bytes.fromhex(
    "1f 16 26 00 fe 89 50 91 1f 00 00 00 00 17 13 00 ff 01 19 00"
)
APPEND_RAW = bytes.fromhex(
    "6d 89 50 91 1f 01 fc f0 32 f2 79 f1 26 f0 00 00 00 00 00 00"
)
SCALE_ADDRESS = "AA:BB:CC:DD:EE:FF"
PASSWORD = "010000A0"
BROADCAST_ID = "AABBCCDD"
RANDOM = bytes.fromhex("a10a000001")
USER_ACK = bytes.fromhex("c001020304")
PAIRING_REQUEST = bytes.fromhex("a0aabbccdd")
ENCRYPTION_HINT = (
    "macOS pairs when a read needs encryption. Accept the system dialog if it appears. "
    "This read will be tried once more."
)


class Connected:
    """Stand-in for BleakClient.is_connected that counts reads."""

    def __init__(self, value: bool):
        self.value = value
        self.reads = 0

    def __bool__(self) -> bool:
        self.reads += 1
        return self.value


def run(coro, seconds: float = 5):
    async def bounded():
        return await asyncio.wait_for(coro, seconds)

    return asyncio.run(bounded())


def uuid_of(char) -> str:
    if isinstance(char, str):
        return char.lower()
    return str(char.uuid).lower()


def add_char(
    service: BleakGATTService, handle: int, short: str, properties: list[str]
) -> None:
    service.add_characteristic(
        BleakGATTCharacteristic(
            None,
            handle,
            sig(short),
            properties,
            lambda: 20,
            service,
        )
    )


def scale_services() -> BleakGATTServiceCollection:
    """DIS plus the digit-02 scale service the listener and the client both use."""
    collection = BleakGATTServiceCollection()
    info = BleakGATTService(None, 16, sig("180a"))
    add_char(info, 17, "2a29", ["read"])
    add_char(info, 18, "2a25", ["read"])
    collection.add_service(info)
    scale = BleakGATTService(None, 32, sig("78a2"))
    add_char(scale, 33, "8a24", ["notify"])
    add_char(scale, 34, "8a22", ["notify"])
    add_char(scale, 35, "8a81", ["write"])
    add_char(scale, 36, "8a82", ["indicate"])
    collection.add_service(scale)
    return collection


def info_services() -> BleakGATTServiceCollection:
    collection = BleakGATTServiceCollection()
    info = BleakGATTService(None, 16, sig("180a"))
    add_char(info, 17, "2a29", ["read"])
    add_char(info, 18, "2a25", ["read"])
    collection.add_service(info)
    return collection


def weight_service() -> BleakGATTServiceCollection:
    collection = BleakGATTServiceCollection()
    scale = BleakGATTService(None, 32, sig("78a2"))
    add_char(scale, 33, "8a24", ["notify"])
    collection.add_service(scale)
    return collection


def ble_device(address: str, name: str | None) -> BLEDevice:
    return BLEDevice(address, name, None)


def advertisement(
    name: str | None,
    *,
    rssi: int = -50,
    uuids: list[str] | None = None,
    manufacturer: dict[int, bytes] | None = None,
) -> AdvertisementData:
    return AdvertisementData(
        local_name=name,
        manufacturer_data=manufacturer or {},
        service_data={},
        service_uuids=list(uuids or []),
        tx_power=None,
        rssi=rssi,
        platform_data=(),
    )


def scale_sighting(name: str = "0DL87801", rssi: int = -48):
    device = ble_device(SCALE_ADDRESS, name)
    adv = advertisement(
        name,
        rssi=rssi,
        uuids=[sig("78a2")],
        manufacturer={0x004C: bytes.fromhex("0102")},
    )
    return device, adv


class Radio:
    """Spec'd BleakScanner and BleakClient. Calls hit bleak's real signatures."""

    def __init__(self):
        self.scanner_cls = create_autospec(BleakScanner, spec_set=True)
        self.client_cls = create_autospec(BleakClient, spec_set=True)
        self.scanners = []
        self.clients = []
        self.ops: list[tuple] = []
        self.advertisements: list[tuple[BLEDevice, AdvertisementData]] = []
        self.discover_result: dict = {}
        self.discover_error: BleakError | None = None
        self.connect_error: BleakError | None = None
        self.exit_error: BleakError | None = None
        self.services: BleakGATTServiceCollection = BleakGATTServiceCollection()
        self.connected: Connected | bool = Connected(False)
        self.fail_starts = 0
        self.hang_on_start: int | None = None
        self.starts = 0
        self.notifications: dict[str, list[list[bytes]]] = {}
        self.reads: dict[str, list] = {}
        self.scanner_cls.side_effect = self._build_scanner
        self.scanner_cls.discover.side_effect = self._discover
        self.client_cls.side_effect = self._build_client

    def notify(self, short: str, *payloads: bytes) -> None:
        """Queue one start_notify delivery. Call again for the next subscription."""
        self.notifications.setdefault(sig(short), []).append(list(payloads))

    def stage_read(self, short: str, *items) -> None:
        self.reads.setdefault(sig(short), []).extend(items)

    def _build_scanner(self, *args, **kwargs):
        scanner = create_autospec(BleakScanner, instance=True, spec_set=True)
        callback = kwargs.get("detection_callback")

        async def start():
            self.starts += 1
            if self.starts <= self.fail_starts:
                raise BleakError("Bluetooth adapter not available")
            if self.hang_on_start is not None and self.starts >= self.hang_on_start:
                await asyncio.Event().wait()
            if callback is not None:
                for device, adv in self.advertisements:
                    callback(device, adv)

        scanner.start.side_effect = start
        self.scanners.append(scanner)
        return scanner

    async def _discover(self, *args, **kwargs):
        if self.discover_error is not None:
            raise self.discover_error
        return self.discover_result

    def _build_client(self, *args, **kwargs):
        client = create_autospec(BleakClient, instance=True, spec_set=True)
        if self.connect_error is not None:
            client.__aenter__.side_effect = self.connect_error
        else:
            client.__aenter__.return_value = client
        if self.exit_error is not None:
            client.__aexit__.side_effect = self.exit_error
        else:
            client.__aexit__.return_value = None
        client.is_connected = self.connected
        client.services = self.services

        async def read(char, *ignored, **ignored_kw):
            uuid = uuid_of(char)
            self.ops.append(("read", uuid))
            script = self.reads.get(uuid, [])
            if not script:
                raise BleakError(f"no read staged for {uuid}")
            item = script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        async def start_notify(char, callback, *ignored, **ignored_kw):
            uuid = uuid_of(char)
            self.ops.append(("start_notify", uuid))
            batches = self.notifications.get(uuid, [])
            if not batches:
                return
            for payload in batches.pop(0):
                callback(None, bytearray(payload))
            return

        async def stop_notify(char, *ignored, **ignored_kw):
            self.ops.append(("stop_notify", uuid_of(char)))

        async def write(char, data, *ignored, **ignored_kw):
            response = ignored_kw.get("response", ignored[0] if ignored else None)
            self.ops.append(("write", uuid_of(char), bytes(data), response))

        client.read_gatt_char.side_effect = read
        client.start_notify.side_effect = start_notify
        client.stop_notify.side_effect = stop_notify
        client.write_gatt_char.side_effect = write
        self.clients.append(client)
        return client


@contextmanager
def bluetooth(module: str, radio: Radio):
    with (
        patch(f"{module}.BleakScanner", radio.scanner_cls),
        patch(f"{module}.BleakClient", radio.client_cls),
    ):
        yield


def assert_real_param(test: unittest.TestCase, func, name: str) -> None:
    param = inspect.signature(func).parameters[name]
    test.assertNotIn(
        param.kind,
        (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL),
    )


class BleakSignatureTests(unittest.TestCase):
    """Keyword names our calls pass through. Autospec misses a removal when **kwargs remains."""

    def test_called_parameters_are_declared(self):
        assert_real_param(self, BleakScanner.__init__, "detection_callback")
        assert_real_param(self, BleakScanner.discover, "timeout")
        assert_real_param(self, BleakScanner.discover, "return_adv")
        assert_real_param(self, BleakClient.__init__, "timeout")
        assert_real_param(self, BleakClient.read_gatt_char, "char_specifier")
        assert_real_param(self, BleakClient.write_gatt_char, "data")
        assert_real_param(self, BleakClient.write_gatt_char, "response")
        assert_real_param(self, BleakClient.start_notify, "callback")
        assert_real_param(self, BleakClient.stop_notify, "char_specifier")
        for func in (
            BleakScanner.discover,
            BleakScanner.start,
            BleakScanner.stop,
            BleakClient.__aenter__,
            BleakClient.__aexit__,
            BleakClient.read_gatt_char,
            BleakClient.write_gatt_char,
            BleakClient.start_notify,
            BleakClient.stop_notify,
        ):
            self.assertTrue(inspect.iscoroutinefunction(func), func)
        self.assertIsInstance(
            inspect.getattr_static(BleakClient, "is_connected"), property
        )
        self.assertIsInstance(inspect.getattr_static(BleakClient, "services"), property)
        callback_args = get_args(AdvertisementDataCallback)[0]
        self.assertEqual(list(callback_args), [BLEDevice, AdvertisementData])
        self.assertIn(
            "insufficient", str(BleakError("Insufficient Encryption")).lower()
        )


class ListenerBluetoothTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "hub.db")
        self.hub = Hub(self.db)
        self.listener = ScaleListener(self.hub, Path(self.tmp.name))

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_detection_callback_keeps_the_scale_and_stops_the_scanner(self):
        radio = Radio()
        phone = ble_device("11:22:33:44:55:66", "Keyboard")
        scale, scale_adv = scale_sighting("1DL87801", rssi=-42)
        radio.advertisements = [
            (phone, advertisement("Keyboard", rssi=-80)),
            (scale, scale_adv),
        ]

        async def scenario():
            with bluetooth("bathroom_hub.listener", radio):
                return await self.listener._wait_for_scale()

        found = run(scenario())
        self.assertIs(found, scale)
        self.assertIn("detection_callback", radio.scanner_cls.call_args.kwargs)
        scanner = radio.scanners[0]
        self.assertEqual(scanner.start.await_count, 1)
        self.assertEqual(scanner.stop.await_count, 1)
        nearby = self.listener.nearby_devices()
        self.assertEqual([item["address"] for item in nearby], [SCALE_ADDRESS])
        self.assertEqual(nearby[0]["name"], "1DL87801")
        self.assertTrue(nearby[0]["pairing_mode"])
        self.assertEqual(nearby[0]["rssi"], -42)
        self.assertNotIn("11:22:33:44:55:66", self.listener.nearby)

    def test_session_resubscribes_8a82_writes_with_response_and_ingests(self):
        self.assertEqual(COMMAND_IN, sig("8a82"))
        self.assertEqual(COMMAND_OUT, sig("8a81"))
        radio = Radio()
        radio.services = scale_services()
        radio.connected = Connected(False)
        radio.stage_read("2a25", bytearray(b"SN1\x00rest"))
        radio.notify("8a24", WEIGHT_RAW)
        radio.notify("8a22", APPEND_RAW)
        radio.notify("8a82", RANDOM)
        radio.notify("8a82", USER_ACK)
        self.listener.store.put(
            "SN1", {"password": PASSWORD, "broadcast_id": BROADCAST_ID}
        )
        device, _adv = scale_sighting()

        async def scenario():
            loop = asyncio.get_running_loop()
            original = loop.call_later
            handles = []

            def capture(delay, callback, *args):
                handle = original(delay, callback, *args)
                handles.append(handle)
                return handle

            loop.call_later = capture
            try:
                with bluetooth("bathroom_hub.listener", radio):
                    await self.listener._session(device)
            finally:
                for handle in handles:
                    handle.cancel()
                loop.call_later = original
            return handles

        handles = run(scenario())
        client = radio.clients[0]
        self.assertEqual(radio.client_cls.call_args.args[0], device)
        self.assertEqual(radio.client_cls.call_args.kwargs["timeout"], 30)
        self.assertEqual(client.__aenter__.await_count, 1)
        self.assertEqual(client.__aexit__.await_count, 1)
        self.assertGreaterEqual(radio.connected.reads, 1)
        self.assertFalse(radio.connected.value)
        self.assertEqual(
            [op for op in radio.ops if op[1] == COMMAND_IN],
            [
                ("start_notify", COMMAND_IN),
                ("stop_notify", COMMAND_IN),
                ("start_notify", COMMAND_IN),
            ],
        )
        writes = [op for op in radio.ops if op[0] == "write"]
        self.assertTrue(writes)
        self.assertTrue(all(op[1] == COMMAND_OUT and op[3] is True for op in writes))
        self.assertTrue(any(op[2][0] == 0x20 for op in writes))
        for call in client.write_gatt_char.await_args_list:
            self.assertIs(call.kwargs["response"], True)
        self.assertGreaterEqual(len(handles), 1)
        self.assertEqual(self.hub.db.get_setting("scale_serial"), "SN1")
        self.assertEqual(self.listener.address, SCALE_ADDRESS)
        rows = self.db.measurements()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["weight_kg"], 97.5)
        self.assertAlmostEqual(rows[0]["scale_fat_pct"], 25.2)
        messages = [row["message"] for row in self.db.events()]
        self.assertTrue(
            any(message.startswith("Weigh received:") for message in messages)
        )
        self.assertFalse(any("did not recognise" in message for message in messages))

    def test_pairing_request_outside_the_window_does_not_resubscribe(self):
        radio = self._command_radio(PAIRING_REQUEST)
        device, _adv = scale_sighting("1DL87801")

        async def scenario():
            with bluetooth("bathroom_hub.listener", radio):
                await self.listener._session(device)

        run(scenario())
        self.assertNotIn("stop_notify", [op[0] for op in radio.ops])
        messages = [row["message"] for row in self.db.events()]
        self.assertTrue(any("pairing window" in message for message in messages))

    def test_sync_without_a_stored_pair_does_not_resubscribe(self):
        radio = self._command_radio(RANDOM)
        device, _adv = scale_sighting()

        async def scenario():
            with bluetooth("bathroom_hub.listener", radio):
                await self.listener._session(device)

        run(scenario())
        self.assertNotIn("stop_notify", [op[0] for op in radio.ops])
        messages = [row["message"] for row in self.db.events()]
        self.assertTrue(any("paired to another app" in message for message in messages))

    def test_run_records_bleakerror_and_returns_to_scanning(self):
        radio = Radio()
        radio.fail_starts = 5

        # bathroom_hub.listener.asyncio is the process-wide asyncio module.
        # Save sleep before the patch so a zero delay still yields.
        original_sleep = asyncio.sleep

        async def park(seconds):
            if seconds == 0:
                await original_sleep(0)
                return
            await asyncio.Event().wait()

        async def scenario():
            with (
                bluetooth("bathroom_hub.listener", radio),
                patch("bathroom_hub.listener.asyncio.sleep", park),
            ):
                task = asyncio.create_task(self.listener.run())
                try:
                    for _ in range(50):
                        await original_sleep(0)
                        if self.listener.last_error:
                            break
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task

        run(scenario())
        self.assertEqual(
            self.listener.last_error,
            "BleakError: Bluetooth adapter not available",
        )
        self.assertEqual(self.listener.state, "scanning")
        messages = [row["message"] for row in self.db.events()]
        self.assertIn(
            "Bluetooth: BleakError: Bluetooth adapter not available", messages
        )
        self.assertIn("detection_callback", radio.scanner_cls.call_args.kwargs)

    def _command_radio(self, packet: bytes) -> Radio:
        radio = Radio()
        radio.connected = Connected(False)
        radio.stage_read("2a25", bytearray(b"SN1\x00"))
        radio.notify("8a82", packet)
        return radio


class SessionBluetoothTests(unittest.TestCase):
    def test_discover_uses_return_adv_and_lists_the_scale(self):
        radio = Radio()
        device, adv = scale_sighting()
        other = ble_device("11:22:33:44:55:66", "Keyboard")
        radio.discover_result = {
            other.address: (other, advertisement("Keyboard", rssi=-80)),
            device.address: (device, adv),
        }
        output = io.StringIO()

        async def scenario():
            with bluetooth("ble_probe.session", radio), redirect_stdout(output):
                matched = await run_scan(0.2, False)
                shown = await run_scan(0.2, True)
                empty_radio_result = dict(radio.discover_result)
                radio.discover_result = {}
                missing = await run_scan(0.2, False)
                radio.discover_result = empty_radio_result
            return matched, shown, missing

        matched, shown, missing = run(scenario())
        text = output.getvalue()
        self.assertEqual((matched, shown, missing), (0, 0, 1))
        for call in radio.scanner_cls.discover.await_args_list:
            self.assertIs(call.kwargs["return_adv"], True)
            self.assertEqual(call.kwargs["timeout"], 0.2)
        self.assertIn(SCALE_ADDRESS, text)
        self.assertIn("004c:01 02", text)
        self.assertIn("-48 dBm", text)
        self.assertIn("1 matching", text)
        self.assertIn("Keyboard", text)
        self.assertIn("No scale or Sonicare", text)
        self.assertFalse(radio.client_cls.called)

    def test_discover_bleakerror_is_reported(self):
        radio = Radio()
        radio.discover_error = BleakError("powered off")
        output = io.StringIO()

        async def scenario():
            with bluetooth("ble_probe.session", radio), redirect_stdout(output):
                scan = await run_scan(1, False)
                collect = await run_collect("scale", None, 0, 1, None)
            return scan, collect

        scan, collect = run(scenario())
        text = output.getvalue()
        self.assertEqual((scan, collect), (1, 1))
        self.assertIn("Scan failed: powered off", text)
        self.assertIn("Privacy & Security", text)
        self.assertFalse(radio.client_cls.called)

    def test_several_scales_do_not_connect(self):
        radio = Radio()
        first, first_adv = scale_sighting("0DL87801")
        second = ble_device("BB:BB:BB:BB:BB:BB", "0DL87802")
        radio.discover_result = {
            first.address: (first, first_adv),
            second.address: (second, advertisement("0DL87802", uuids=[sig("78a2")])),
        }
        output = io.StringIO()

        async def scenario():
            with bluetooth("ble_probe.session", radio), redirect_stdout(output):
                return await run_collect("scale", None, 0, 0.1, None)

        code = run(scenario())
        self.assertEqual(code, 1)
        self.assertIn("Several scale advertisements", output.getvalue())
        self.assertFalse(radio.client_cls.called)

    def test_collect_enumerates_reads_writes_and_notifies(self):
        radio, store = self._paired_radio()
        output = io.StringIO()

        async def scenario():
            with bluetooth("ble_probe.session", radio), redirect_stdout(output):
                return await run_collect("scale", None, 0, 0.25, None, store_path=store)

        code = run(scenario())
        text = output.getvalue()
        client = radio.clients[0]
        self.assertEqual(code, 0)
        self.assertIs(radio.scanner_cls.discover.await_args.kwargs["return_adv"], True)
        self.assertIsInstance(radio.client_cls.call_args.args[0], BLEDevice)
        self.assertEqual(radio.client_cls.call_args.kwargs["timeout"], 40)
        self.assertEqual(client.__aenter__.await_count, 1)
        self.assertEqual(client.__aexit__.await_count, 1)
        self.assertIn(sig("78a2"), text)
        self.assertIn(sig("8a24"), text)
        self.assertIn("notify", text)
        self.assertIn("SN1", text)
        self.assertIn("subscribed", text)
        self.assertEqual(
            [op for op in radio.ops if op[1] == sig("8a82")],
            [("start_notify", sig("8a82")), ("stop_notify", sig("8a82"))],
        )
        writes = [op for op in radio.ops if op[0] == "write"]
        self.assertTrue(writes)
        self.assertTrue(all(op[1] == sig("8a81") and op[3] is True for op in writes))
        for call in client.write_gatt_char.await_args_list:
            self.assertIs(call.kwargs["response"], True)
        self.assertIn("Done.", text)

    def test_address_connects_when_the_scan_missed_it(self):
        radio = Radio()
        output = io.StringIO()

        async def scenario():
            with bluetooth("ble_probe.session", radio), redirect_stdout(output):
                return await run_collect("scale", SCALE_ADDRESS, 0, 0.1, None)

        code = run(scenario())
        self.assertEqual(code, 0)
        self.assertEqual(radio.client_cls.call_args.args[0], SCALE_ADDRESS)
        self.assertEqual(radio.client_cls.call_args.kwargs["timeout"], 40)
        self.assertEqual(radio.clients[0].__aenter__.await_count, 1)
        self.assertIn("was not in this scan", output.getvalue())
        self.assertIn("8A81 was not found", output.getvalue())

    def test_connect_bleakerror_fails_the_session(self):
        radio = Radio()
        device, adv = scale_sighting()
        radio.discover_result = {device.address: (device, adv)}
        radio.connect_error = BleakError("device not found")
        output = io.StringIO()

        async def scenario():
            with bluetooth("ble_probe.session", radio), redirect_stdout(output):
                return await run_collect("scale", None, 0, 0.1, None)

        code = run(scenario())
        self.assertEqual(code, 1)
        self.assertIn("Connect failed: device not found", output.getvalue())
        self.assertNotIn("Link closed", output.getvalue())

    def test_link_loss_after_notify_is_not_a_connect_failure(self):
        radio = Radio()
        device, adv = scale_sighting()
        radio.discover_result = {device.address: (device, adv)}
        radio.services = weight_service()
        radio.notify("8a24", WEIGHT_RAW)
        radio.exit_error = BleakError("link lost")
        output = io.StringIO()

        async def scenario():
            with bluetooth("ble_probe.session", radio), redirect_stdout(output):
                return await run_collect("scale", None, 0, 0.1, None)

        code = run(scenario())
        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Link closed: link lost", text)
        self.assertNotIn("Connect failed", text)
        self.assertIn(
            ("stop_notify", sig("8a24")), [(op[0], op[1]) for op in radio.ops]
        )

    def test_insufficient_encryption_retries_once_and_other_errors_do_not(self):
        radio = Radio()
        device, adv = scale_sighting()
        radio.discover_result = {device.address: (device, adv)}
        radio.services = info_services()
        radio.stage_read("2a29", BleakError("not permitted"))
        radio.stage_read(
            "2a25",
            BleakError("Insufficient Encryption"),
            bytearray(b"SN1\x00"),
        )
        delays = []

        original_sleep = asyncio.sleep

        async def fast(seconds):
            delays.append(seconds)
            await original_sleep(0)

        output = io.StringIO()

        async def scenario():
            with (
                bluetooth("ble_probe.session", radio),
                patch("ble_probe.session.asyncio.sleep", fast),
                redirect_stdout(output),
            ):
                return await run_collect("scale", None, 0, 0.1, None)

        code = run(scenario())
        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertEqual(delays, [8, 0])
        self.assertEqual(text.count(ENCRYPTION_HINT), 1)
        self.assertIn(f"read {sig('2a29')} failed: not permitted", text)
        self.assertIn("SN1", text)
        serial_reads = [op for op in radio.ops if op == ("read", sig("2a25"))]
        self.assertEqual(len(serial_reads), 2)
        self.assertEqual(radio.clients[0].read_gatt_char.await_count, 3)

    def test_watch_retries_a_failed_scan_then_uses_is_connected(self):
        radio = Radio()
        radio.fail_starts = 1
        radio.hang_on_start = 3
        radio.connected = Connected(True)
        radio.advertisements = [scale_sighting("0DL87801")]
        delays = []

        original_sleep = asyncio.sleep

        async def fast(seconds):
            delays.append(seconds)
            await original_sleep(0)

        output = io.StringIO()

        async def scenario():
            with (
                bluetooth("ble_probe.session", radio),
                patch("ble_probe.session.asyncio.sleep", fast),
                redirect_stdout(output),
            ):
                task = asyncio.create_task(run_watch(None, None, 0))
                finished = False
                try:
                    for _ in range(100):
                        await original_sleep(0)
                        if "Watching again" in output.getvalue():
                            finished = True
                            break
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                return finished

        finished = run(scenario())
        text = output.getvalue()
        self.assertTrue(finished, text)
        self.assertIn("Scan failed: Bluetooth adapter not available", text)
        self.assertIn("Closing the link", text)
        self.assertIn("Watching again", text)
        self.assertGreaterEqual(radio.connected.reads, 1)
        self.assertIn(3, delays)
        self.assertIn(1, delays)
        self.assertEqual(radio.client_cls.call_args.kwargs["timeout"], 40)
        self.assertIsInstance(radio.client_cls.call_args.args[0], BLEDevice)
        self.assertIn("detection_callback", radio.scanner_cls.call_args.kwargs)

    def _paired_radio(self) -> tuple[Radio, Path]:
        radio = Radio()
        radio.services = scale_services()
        radio.connected = Connected(False)
        device, adv = scale_sighting()
        radio.discover_result = {device.address: (device, adv)}
        radio.stage_read("2a29", bytearray(b"Philips\x00"))
        radio.stage_read("2a25", bytearray(b"SN1\x00"))
        radio.notify("8a24", WEIGHT_RAW)
        radio.notify("8a22", APPEND_RAW)
        radio.notify("8a82", RANDOM, USER_ACK)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "scale.json"
        ScaleStore(path).put(
            "SN1", {"password": PASSWORD, "broadcast_id": BROADCAST_ID}
        )
        return radio, path
