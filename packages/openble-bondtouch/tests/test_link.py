"""BraceletLink against fake bracelets of each generation."""

import asyncio
import unittest

from openble.bondtouch import uuids, v1, v2, v3
from openble.bondtouch.identify import MINI, V1, V2, V3, V4
from openble.bondtouch.link import (
    BraceletLink,
    CommandError,
    detect_generation,
    notify_uuids,
)
from openble.bondtouch.patterns import to_samples

AUID = 0x0A0B0C0D
RED = (0xFF, 0, 0)


class FakeBracelet:
    """Records writes and answers some of them with notifications."""

    def __init__(self, answer=None, reads=None):
        self.answer = answer or (lambda uuid, payload: [])
        self.reads = {uuids.BATTERY: b"\x4b\x00", **(reads or {})}
        self.writes: list[tuple[str, bytes]] = []
        self.link: BraceletLink | None = None

    async def write(self, uuid: str, payload: bytes) -> None:
        self.writes.append((uuid, payload))
        for reply_uuid, data in self.answer(uuid, payload):
            asyncio.get_running_loop().call_soon(self.link.feed, reply_uuid, data)

    async def read(self, uuid: str) -> bytes:
        return self.reads[uuid]


def make_link(bracelet: FakeBracelet, generation: str, **options) -> BraceletLink:
    link = BraceletLink(
        bracelet.write,
        generation,
        AUID,
        read=bracelet.read,
        **{"retry_delay": 0, "command_timeout": 0.2, **options},
    )
    bracelet.link = link
    return link


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


class HelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_detect_generation(self):
        bracelet = FakeBracelet(reads={uuids.API_VERSION: b"\x44"})
        self.assertEqual(
            await detect_generation(bracelet.read, [uuids.INFO_SERVICE]), V4
        )
        self.assertEqual(await detect_generation(bracelet.read, [uuids.V3_SERVICE]), V3)

    def test_notify_uuids(self):
        self.assertEqual(notify_uuids(V1)[-1], uuids.V1_RESULT)
        self.assertEqual(notify_uuids(MINI), (uuids.BATTERY, uuids.EVENT, uuids.STATE))
        self.assertEqual(notify_uuids(V3), (uuids.V3_COMMAND, uuids.V3_TOUCH))


class V2LinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_handshake(self):
        def answer(uuid, payload):
            if uuid == uuids.TOKEN:
                return [(uuids.STATE, b"\x83\x00\x00\x00\x00")]
            if uuid == uuids.AUID:
                return [(uuids.STATE, b"\x85\x01\x00\x00\x00")]
            return []

        bracelet = FakeBracelet(answer)
        link = make_link(bracelet, V2)
        link.feed(uuids.BATTERY.upper(), b"\x4b\x00")
        await link.start()
        await link.wait_connected(timeout=1)
        self.assertEqual(
            bracelet.writes,
            [(uuids.TOKEN, b"12345678"), (uuids.AUID, bytes.fromhex("0d0c0b0a"))],
        )
        self.assertEqual((link.state, link.battery), (v2.CONNECTED, 75))

    async def test_repeated_state_is_answered_once(self):
        # Live, a V2 on 2.6.4 repeated WAITING_AUID with ledBusy set.
        bracelet = FakeBracelet()
        link = make_link(bracelet, V2)
        link.feed(uuids.STATE, bytes.fromhex("83 00 00 00 00"))
        link.feed(uuids.STATE, bytes.fromhex("83 00 01 00 00"))
        await settle()
        self.assertEqual(bracelet.writes, [(uuids.AUID, bytes.fromhex("0d0c0b0a"))])

    async def test_auid_error_then_double_tap(self):
        bracelet = FakeBracelet(
            lambda uuid, payload: (
                [(uuids.STATE, b"\x85")] if uuid == uuids.COMMAND else []
            )
        )
        link = make_link(bracelet, V2)
        link.feed(uuids.EVENT, b"\x12" + bytes(13))
        link.feed(uuids.STATE, bytes.fromhex("84 00 01 00 00"))
        self.assertTrue(link.needs_setup)
        link.feed(uuids.EVENT, b"\x13" + bytes(13))  # the wearer double-tapped
        await link.wait_connected(timeout=1)
        self.assertEqual(bracelet.writes, [(uuids.COMMAND, v2.PAIRED_ACK)])
        self.assertFalse(link.needs_setup)

    async def test_v4_reads_state_first(self):
        bracelet = FakeBracelet(
            reads={uuids.STATE: b"\x82\x00\x00\x00\x00", uuids.BATTERY: b"\x1e\x00"}
        )
        link = make_link(bracelet, V4)
        await link.start()
        await settle()
        self.assertEqual(bracelet.writes, [(uuids.TOKEN, b"12345678")])
        self.assertEqual(link.battery, 30)

    async def test_paired_signal_and_auid_error(self):
        bracelet = FakeBracelet()
        link = make_link(bracelet, V2)
        link.feed(uuids.EVENT, b"\x13\x00")
        link.feed(uuids.EVENT, b"\x12\x00")
        await settle()
        self.assertEqual(bracelet.writes, [(uuids.COMMAND, v2.PAIRED_ACK)])
        self.assertTrue(link.needs_setup)
        self.assertEqual(link.events.get_nowait().name, "PAIRED_SIGNAL")

    async def test_touch_is_recorded(self):
        link = make_link(FakeBracelet(), V4)
        stop = (0xFFFFFFFF).to_bytes(4, "little")
        link.feed(uuids.EVENT, bytes.fromhex("14 01 90010000 00000000 00000000 02"))
        link.feed(
            uuids.EVENT, bytes.fromhex("14 02 2c010000 c8000000") + stop + b"\x02"
        )
        message = link.touches.get_nowait()
        self.assertEqual((message.pattern, message.slot), ((400, 200, 300), 2))
        self.assertTrue(link.events.empty())

    async def test_play_and_busy_pause(self):
        bracelet = FakeBracelet()
        link = make_link(bracelet, V2)
        await link.play([400], RED)
        self.assertEqual([payload for _, payload in bracelet.writes][-1], v2.RUN_TOUCH)
        # RUN_TOUCH holds commands until the bracelet reports CONNECTED again.
        task = asyncio.create_task(link.show_colour(RED))
        await settle()
        self.assertEqual(len(bracelet.writes), 2)
        link.feed(uuids.STATE, b"\x85")
        await task
        self.assertEqual(bracelet.writes[-1], (uuids.COMMAND, v2.show_colour(RED)))

    async def test_msg_state_pauses(self):
        bracelet = FakeBracelet()
        link = make_link(bracelet, V2)
        link.feed(uuids.STATE, b"\x86")
        task = asyncio.create_task(link.clear_colour())
        await settle()
        self.assertEqual(bracelet.writes, [])
        link.feed(uuids.STATE, b"\x85")
        await task
        self.assertEqual(bracelet.writes, [(uuids.COMMAND, v2.clear_colour())])


class V1LinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_and_acknowledged_commands(self):
        def answer(uuid, payload):
            if uuid == uuids.AUID:
                return [(uuids.STATE, bytes((0x84, v1.IDLE, 0)))]
            if uuid == uuids.COMMAND and len(payload) >= 4:
                return [(uuids.V1_RESULT, b"\x01\x00" + payload[2:4])]
            return []

        bracelet = FakeBracelet(answer)
        link = make_link(bracelet, V1)
        await link.start()
        link.feed(uuids.STATE, bytes((0x84, v1.WAITING_AUID, 0)))
        await link.wait_connected(timeout=1)
        await link.play([400, 200, 400], RED)
        commands = [
            payload for uuid, payload in bracelet.writes if uuid == uuids.COMMAND
        ]
        self.assertEqual([v1.seq_of(payload) for payload in commands], [0, 1, 2, 3])
        self.assertEqual(commands[0][4], 0)  # ledId 0 for red
        self.assertEqual(bracelet.writes[0], (uuids.TOKEN, b"12345678"))

    async def test_retry_then_error(self):
        def answer(uuid, payload):
            if uuid == uuids.COMMAND:
                return [(uuids.V1_RESULT, b"\x0b\x00" + payload[2:4])]  # ACR_BUSY
            return []

        bracelet = FakeBracelet(answer)
        link = make_link(bracelet, V1)
        with self.assertRaises(CommandError) as caught:
            await link.show_colour(RED)
        self.assertEqual(caught.exception.result.name, "ACR_BUSY")
        self.assertEqual(len(bracelet.writes), 2)

    async def test_timeout_after_retry(self):
        bracelet = FakeBracelet()
        link = make_link(bracelet, V1, command_timeout=0.01)
        with self.assertRaises(TimeoutError):
            await link.clear_colour()
        self.assertEqual(len(bracelet.writes), 2)

    async def test_paired_ack_and_touch(self):
        bracelet = FakeBracelet()
        link = make_link(bracelet, V1)
        link.feed(uuids.EVENT, b"\x13\x00\x00\x00\x00\x00")
        link.feed(uuids.EVENT, bytes.fromhex("14 00 0100 2c01"))
        link.feed(uuids.EVENT, bytes.fromhex("14 00 ffff 0000"))
        await settle()
        self.assertEqual(bracelet.writes, [(uuids.COMMAND, b"\x31")])
        self.assertEqual(link.touches.get_nowait().pattern, (300,))


class V3LinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_burst_and_reports(self):
        def answer(uuid, payload):
            if payload == v3.HELLO:
                return [(uuid, bytes.fromhex("ac 01 01 03")), (uuid, b"\x04\x82")]
            if payload == v3.TOKEN:
                return [(uuid, b"\x04\x83")]
            if payload[:1] == b"\x07":
                return [(uuid, b"\x04\x85")]
            return []

        bracelet = FakeBracelet(answer)
        link = make_link(bracelet, V3)
        await link.start()
        await link.wait_connected(timeout=1)
        await settle()
        sent = [payload for _, payload in bracelet.writes]
        self.assertEqual(sent[:3], [v3.HELLO, v3.TOKEN, bytes.fromhex("07 0d")])
        self.assertEqual(tuple(sent[3:]), v3.CONNECT_BURST)
        self.assertEqual(link.firmware, (3, 1, 1))
        link.feed(uuids.V3_COMMAND, b"\x04\x85")
        await settle()
        self.assertEqual(len(bracelet.writes), 9)  # the burst goes once

    async def test_paired_and_touch(self):
        bracelet = FakeBracelet()
        link = make_link(bracelet, V3)
        link.feed(uuids.V3_COMMAND, b"\x04\x8a")
        link.feed(uuids.V3_COMMAND, b"\x02\x13")
        await settle()
        self.assertEqual(bracelet.writes, [(uuids.V3_COMMAND, v3.PAIRED_ACK)] * 2)
        for frame in v3.touch_frames(to_samples([200, 100, 300]), RED, slot=2):
            link.feed(uuids.V3_TOUCH, frame)
        message = link.touches.get_nowait()
        self.assertEqual((message.pattern, message.slot), ((200, 100, 300), 2))

    async def test_play_writes_ffb2(self):
        bracelet = FakeBracelet()
        link = make_link(bracelet, V3)
        await link.play([200, 100, 300], RED, slot=3)
        self.assertEqual({uuid for uuid, _ in bracelet.writes}, {uuids.V3_TOUCH})
        self.assertEqual(bracelet.writes[0][1][:3], bytes((3, 12, 1)))


if __name__ == "__main__":
    unittest.main()
