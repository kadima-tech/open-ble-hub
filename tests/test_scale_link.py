"""Frame builders for the A3 command exchange."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from philips_ble.scale_link import (
    ScaleStore,
    bind_user_frame,
    broadcast_frame,
    command_field,
    disconnect_frame,
    height_centimetres_bytes,
    run_scale_handshake,
    user_info_fallback,
    goal_weight_bytes,
    user_info_frame,
    user_slot,
    utc_frame,
    xor_frame,
)


class FrameTests(unittest.TestCase):
    def test_broadcast_and_xor(self):
        self.assertEqual(broadcast_frame(bytes.fromhex("01020304")), bytes.fromhex("21 01 02 03 04"))
        # password 01 00 00 a0 XOR random 0a 00 00 01 -> 0b 00 00 a1
        self.assertEqual(
            xor_frame(bytes.fromhex("010000a0"), bytes.fromhex("0a000001")),
            bytes.fromhex("20 0b 00 00 a1"),
        )

    def test_bind_user_pads_with_spaces(self):
        frame = bind_user_frame(1, "User")
        self.assertEqual(len(frame), 18)
        self.assertEqual(frame[0], 0x03)
        self.assertEqual(frame[1], 1)
        self.assertEqual(frame[2:6], b"User")
        self.assertEqual(frame[6:], b" " * 12)

    def test_user_info_fallback_pokes_user_number(self):
        frame = user_info_fallback(1)
        self.assertEqual(frame, bytes([0x51, 0x00, 0x01]) + bytes(12))

    def test_user_info_frame_for_male_36_183cm(self):
        # Java DecimalFormat round-trip of 183 / 100f, then c/f.b, is magnitude 183.
        self.assertEqual(height_centimetres_bytes(183), bytes.fromhex("b7 e0"))
        self.assertEqual(height_centimetres_bytes(100), bytes.fromhex("64 e0"))
        self.assertEqual(height_centimetres_bytes(204), bytes.fromhex("cc e0"))
        frame = user_info_frame(user_number=1, age=36, height_cm=183, sex="male")
        self.assertEqual(frame, bytes.fromhex("51 df 01 01 24 b7 e0 00 00 00 00 00 ff 00 00"))
        female = user_info_frame(user_number=1, age=36, height_cm=183, sex="female")
        self.assertEqual(female[3], 2)

    def test_utc_is_local_wall_clock_since_2010(self):
        self.assertEqual(utc_frame(datetime(2010, 1, 1, 0, 0, 1)), bytes.fromhex("02 01 00 00 00"))
        # PHS Health on a Pixel at 19:50:13 CEST, from the HCI capture.
        self.assertEqual(utc_frame(datetime(2026, 10, 13, 19, 50, 13)), bytes.fromhex("02 75 50 91 1f"))

    def test_disconnect_and_command_classifier(self):
        self.assertEqual(disconnect_frame(), bytes((0x22,)))
        packet = bytes.fromhex("a1 01 00 00 a0") + bytes(15)
        self.assertEqual(command_field(packet), ("random", bytes.fromhex("01 00 00 a0")))
        self.assertEqual(command_field(bytes.fromhex("a0 aa bb cc dd")), ("password", bytes.fromhex("aa bb cc dd")))

    def test_already_paired_without_password_writes_nothing(self):
        writes: list[bytes] = []

        async def write(payload: bytes) -> None:
            writes.append(payload)

        async def scenario():
            queue: asyncio.Queue[bytes] = asyncio.Queue()
            queue.put_nowait(bytes.fromhex("a1 01 00 00 a0") + bytes(15))
            notes: list[str] = []
            with TemporaryDirectory() as tmp:
                store = ScaleStore(Path(tmp) / "store.json")
                await run_scale_handshake(
                    write=write,
                    queue=queue,
                    store=store,
                    device_key="21CED90074C9",
                    user_number=1,
                    user_name="User",
                    password_override=None,
                    listen_seconds=30,
                    log=lambda *_args, **kwargs: notes.append(kwargs.get("message", "")),
                    sleep=_asleep,
                )
            self.assertEqual(writes, [])
            self.assertTrue(any("no command was written" in note for note in notes))

        asyncio.run(scenario())

    @mock.patch("philips_ble.scale_link.USER_INFO_WAIT_SECONDS", 0.01)
    def test_held_link_answers_the_random_then_disconnects(self):
        writes: list[bytes] = []

        async def write(payload: bytes) -> None:
            writes.append(payload)

        async def scenario():
            queue: asyncio.Queue[bytes] = asyncio.Queue()
            queue.put_nowait(bytes.fromhex("a1 01 00 00 a0") + bytes(15))
            with TemporaryDirectory() as tmp:
                store = ScaleStore(Path(tmp) / "store.json")
                store.put("21CED90074C9", {"password": "010000A0"})
                await run_scale_handshake(
                    write=write,
                    queue=queue,
                    store=store,
                    device_key="21CED90074C9",
                    user_number=1,
                    user_name="User",
                    password_override=None,
                    listen_seconds=30,
                    log=lambda *_args, **kwargs: None,
                    sleep=_asleep,
                    release=False,
                )
            self.assertEqual(writes[0], xor_frame(bytes.fromhex("010000a0"), bytes.fromhex("010000a0")))
            self.assertEqual(writes[1][0], 0x02)
            self.assertEqual([item[0] for item in writes], [0x20, 0x02, 0x22])

        asyncio.run(scenario())

    def test_sync_writes_broadcast_id_and_profile_after_c0(self):
        writes: list[bytes] = []

        async def write(payload: bytes) -> None:
            writes.append(payload)

        async def scenario():
            queue: asyncio.Queue[bytes] = asyncio.Queue()
            queue.put_nowait(bytes.fromhex("a1 01 00 00 a0") + bytes(15))
            queue.put_nowait(bytes.fromhex("c0 17 01 01 24 26 d7") + bytes(13))
            with TemporaryDirectory() as tmp:
                store = ScaleStore(Path(tmp) / "store.json")
                store.put(
                    "21CED90074C9",
                    {
                        "password": "010000A0",
                        "broadcast_id": "E58FCA70",
                        "age": 36,
                        "height_cm": 183,
                        "sex": "male",
                    },
                )
                await run_scale_handshake(
                    write=write,
                    queue=queue,
                    store=store,
                    device_key="21CED90074C9",
                    user_number=1,
                    user_name="User",
                    password_override=None,
                    listen_seconds=0,
                    log=lambda *_args, **kwargs: None,
                    sleep=_asleep,
                    release=False,
                )
            self.assertEqual(writes[1], bytes.fromhex("21 e5 8f ca 70"))
            self.assertEqual([item[0] for item in writes], [0x20, 0x21, 0x02, 0x51, 0x22])

        asyncio.run(scenario())

    def test_password_packet_then_random_writes_the_pair_queue(self):
        writes: list[bytes] = []

        async def write(payload: bytes) -> None:
            writes.append(payload)

        async def scenario():
            queue: asyncio.Queue[bytes] = asyncio.Queue()
            queue.put_nowait(bytes.fromhex("a0 11 22 33 44") + bytes(15))
            queue.put_nowait(bytes.fromhex("a1 01 00 00 a0") + bytes(15))
            for slot in range(1, 9):
                queue.put_nowait(bytes((0x83, slot)) + b" " * 16 + bytes(2))
            with TemporaryDirectory() as tmp:
                store = ScaleStore(Path(tmp) / "store.json")
                await run_scale_handshake(
                    write=write,
                    queue=queue,
                    store=store,
                    device_key="21CED90074C9",
                    user_number=1,
                    user_name="User",
                    password_override=None,
                    listen_seconds=0,
                    log=lambda *_args, **kwargs: None,
                    sleep=_asleep,
                )
                saved = store.get("21CED90074C9")
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved["password"], "11223344")
            self.assertEqual(writes[0][0], 0x21)
            self.assertEqual(writes[1], xor_frame(bytes.fromhex("11223344"), bytes.fromhex("010000a0")))
            self.assertEqual(writes[2], bind_user_frame(1, "User"))
            self.assertEqual(writes[3], user_info_fallback(1))
            self.assertEqual(writes[4][0], 0x02)
            self.assertEqual(writes[5], disconnect_frame())

        asyncio.run(scenario())

    def test_profile_is_written_on_the_pair_queue(self):
        writes: list[bytes] = []

        async def write(payload: bytes) -> None:
            writes.append(payload)

        async def scenario():
            queue: asyncio.Queue[bytes] = asyncio.Queue()
            queue.put_nowait(bytes.fromhex("a0 11 22 33 44") + bytes(15))
            queue.put_nowait(bytes.fromhex("a1 01 00 00 a0") + bytes(15))
            for slot in range(1, 9):
                queue.put_nowait(bytes((0x83, slot)) + b" " * 16 + bytes(2))
            with TemporaryDirectory() as tmp:
                store = ScaleStore(Path(tmp) / "store.json")
                await run_scale_handshake(
                    write=write,
                    queue=queue,
                    store=store,
                    device_key="21CED90074C9",
                    user_number=1,
                    user_name="User",
                    password_override=None,
                    listen_seconds=0,
                    log=lambda *_args, **kwargs: None,
                    sleep=_asleep,
                    age=36,
                    height_cm=183,
                    sex="male",
                )
                saved = store.get("21CED90074C9")
            self.assertEqual(saved["age"], 36)
            self.assertEqual(saved["height_cm"], 183)
            self.assertEqual(saved["sex"], "male")
            self.assertEqual(writes[3], bytes.fromhex("51 df 01 01 24 b7 e0 00 00 00 00 00 ff 00 00"))

        asyncio.run(scenario())


class ProfileExtrasTests(unittest.TestCase):
    def test_goal_weight_follows_float_to_string(self):
        self.assertEqual(goal_weight_bytes(0.0), bytes.fromhex("00 00 00 ff"))
        self.assertEqual(goal_weight_bytes(75), bytes.fromhex("ee 02 00 ff"))
        self.assertEqual(goal_weight_bytes(72.5), bytes.fromhex("d5 02 00 ff"))

    def test_activity_and_goal_fill_bytes_7_and_9_to_12(self):
        frame = user_info_frame(user_number=1, age=36, height_cm=183, sex="male", activity_level=3, goal_kg=80)
        self.assertEqual(frame, bytes.fromhex("51 df 01 01 24 b7 e0 03 00 20 03 00 ff 00 00"))


class UserListTests(unittest.TestCase):
    def test_bind_waits_for_the_whole_user_list(self):
        events: list[str] = []
        holder: dict[str, asyncio.Queue[bytes]] = {}

        async def write(payload: bytes) -> None:
            events.append(f"write {payload[0]:02x}")
            if payload[0] == 0x20:
                for slot in range(1, 9):
                    holder["queue"].put_nowait(bytes((0x83, slot)) + b" " * 16 + bytes(2))

        def log(_kind, **kwargs) -> None:
            if "user slots" in kwargs.get("message", ""):
                events.append("slots")

        async def scenario():
            queue: asyncio.Queue[bytes] = asyncio.Queue()
            holder["queue"] = queue
            queue.put_nowait(bytes.fromhex("a0 11 22 33 44") + bytes(15))
            queue.put_nowait(bytes.fromhex("a1 01 00 00 a0") + bytes(15))
            with TemporaryDirectory() as tmp:
                await run_scale_handshake(
                    write=write,
                    queue=queue,
                    store=ScaleStore(Path(tmp) / "store.json"),
                    device_key="k",
                    user_number=1,
                    user_name="User",
                    password_override=None,
                    listen_seconds=0,
                    log=log,
                    sleep=_asleep,
                    release=False,
                )

        asyncio.run(scenario())
        self.assertEqual(events[:4], ["write 21", "write 20", "slots", "write 03"])

    def test_slot_outside_the_list_is_not_bound(self):
        writes: list[bytes] = []

        async def write(payload: bytes) -> None:
            writes.append(payload)

        async def scenario():
            queue: asyncio.Queue[bytes] = asyncio.Queue()
            queue.put_nowait(bytes.fromhex("a0 11 22 33 44") + bytes(15))
            queue.put_nowait(bytes.fromhex("a1 01 00 00 a0") + bytes(15))
            for slot in range(1, 9):
                queue.put_nowait(bytes((0x83, slot)) + b" " * 16 + bytes(2))
            with TemporaryDirectory() as tmp:
                await run_scale_handshake(
                    write=write,
                    queue=queue,
                    store=ScaleStore(Path(tmp) / "store.json"),
                    device_key="k",
                    user_number=9,
                    user_name="User",
                    password_override=None,
                    listen_seconds=0,
                    log=lambda *_args, **kwargs: None,
                    sleep=_asleep,
                    release=False,
                )

        asyncio.run(scenario())
        self.assertEqual([item[0] for item in writes], [0x21, 0x20])

    def test_user_slot_trims_the_name(self):
        self.assertEqual(user_slot(bytes((0x83, 2)) + b"Anna" + b" " * 12 + bytes(2)), (2, "Anna"))
        self.assertIsNone(user_slot(bytes.fromhex("a1 01 00 00 a0")))


async def _asleep(_seconds: float) -> None:
    return None


if __name__ == "__main__":
    unittest.main()
