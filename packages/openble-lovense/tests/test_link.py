"""Channel selection, and ToyLink against a fake toy."""

import asyncio
import time
import unittest

from openble.lovense.frames import crc8
from openble.lovense.link import ToyLink, pick_channels

SERVICE = "5a300001-0023-4bd4-bbd5-a6920e4c5653"
TX = "5a300002-0023-4bd4-bbd5-a6920e4c5653"
RX = "5a300003-0023-4bd4-bbd5-a6920e4c5653"
BE_SERVICE = "42450001-0023-4bd4-bbd5-a6920e4c5653"
BE_TX = "42450002-0023-4bd4-bbd5-a6920e4c5653"
BE_RX = "42450003-0023-4bd4-bbd5-a6920e4c5653"
GAP = "00001800-0000-1000-8000-00805f9b34fb"


class PickChannelsTests(unittest.TestCase):
    def test_last_writable_and_every_notify(self):
        table = [
            (GAP, "00002a00-0000-1000-8000-00805f9b34fb", ["read", "write"]),
            (SERVICE, TX.upper(), ["write", "write-without-response"]),
            (SERVICE, RX, ["notify"]),
            (SERVICE, "5a300004-0023-4bd4-bbd5-a6920e4c5653", ["notify", "read"]),
        ]
        channels = pick_channels(table)
        self.assertEqual(channels.tx, TX)
        self.assertEqual(len(channels.rx), 2)

    def test_write_without_response_alone_is_not_tx(self):
        with self.assertRaises(LookupError):
            pick_channels([(SERVICE, TX, ["write-without-response", "notify"])])

    def test_pinned_model(self):
        table = [
            (BE_SERVICE, BE_TX, ["write"]),
            (BE_SERVICE, BE_RX, ["notify"]),
            (SERVICE, TX, ["write"]),
            (SERVICE, RX, ["notify"]),
        ]
        channels = pick_channels(table, model="BE")
        self.assertEqual((channels.tx, channels.rx), (BE_TX, (BE_RX,)))
        with self.assertRaises(LookupError):
            pick_channels(table + [(BE_SERVICE, BE_TX, ["write"])], model="be")


class FakeToy:
    """Answers like a toy: the reply is fed back as a notification."""

    def __init__(self, replies: dict[bytes, list[bytes]]):
        self.replies = replies
        self.writes: list[bytes] = []
        self.link: ToyLink | None = None

    async def write(self, payload: bytes) -> None:
        self.writes.append(payload)
        for reply in self.replies.get(payload, []):
            asyncio.get_running_loop().call_soon(self.link.feed, reply)


def make_link(toy: FakeToy, **options) -> ToyLink:
    link = ToyLink(toy.write, **{"gap": 0, "qcode_delay": 0, **options})
    toy.link = link
    return link


class ToyLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake(self):
        toy = FakeToy(
            {
                b"DeviceType;": [b"85;", b"S:35:0082059AD3BD;"],
                b"Battery;": [b"85;"],
                b"GetCap;": [b"unkown,GetCap"],
            }
        )
        link = make_link(toy)
        identity = await link.device_type(timeout=1)
        self.assertEqual((identity.model, identity.firmware), ("s", 35))
        # The stray "85;" stays queued, so the battery reply that follows is read
        # first and the queue holds one more.
        self.assertEqual(await link.battery(timeout=1), 85)
        self.assertIsNone(await link.capabilities(timeout=1))
        self.assertEqual(toy.writes, [b"DeviceType;", b"Battery;", b"GetCap;"])

    async def test_device_type_resends_until_timeout(self):
        toy = FakeToy({})
        link = make_link(toy)
        with self.assertRaises(TimeoutError):
            await link.device_type(timeout=0.05)
        self.assertGreaterEqual(len(toy.writes), 1)
        self.assertEqual(set(toy.writes), {b"DeviceType;"})

    async def test_qcode_is_answered(self):
        toy = FakeToy({})
        link = make_link(toy)
        link.feed(b"$010102030405060708;")
        await asyncio.sleep(0.01)
        await link.close()
        self.assertEqual(toy.writes, [b"$01DE000005060708;"])
        self.assertTrue(link.texts.empty())

    async def test_frames_are_checked(self):
        logged = []
        link = make_link(FakeToy({}), log=lambda kind, **payload: logged.append(kind))
        good = bytes((0xAA, 0x8A, 0x00, 0x00))
        link.feed(good + bytes((crc8(good),)))
        link.feed(good + b"\x00")
        frame = link.frames.get_nowait()
        self.assertEqual(frame.command, 0x8A)
        self.assertTrue(link.frames.empty())
        self.assertEqual(logged, ["error"])

    async def test_ok_is_counted_not_queued(self):
        toy = FakeToy({b"Vibrate:3;": [b"OK;"], b"Battery;": [b"77;"]})
        link = make_link(toy)
        await link.move(b"Vibrate:3;")
        self.assertEqual(await link.battery(timeout=1), 77)
        self.assertEqual(link.acks, 1)
        self.assertTrue(link.texts.empty())

    async def test_move_drops_a_quick_repeat(self):
        toy = FakeToy({})
        link = make_link(toy)
        self.assertTrue(await link.move(b"Vibrate:10;"))
        self.assertFalse(await link.move(b"Vibrate:10;"))
        self.assertTrue(await link.move(b"Vibrate:11;"))
        await link.stop(["v", "r"])
        self.assertTrue(await link.move(b"Vibrate:11;"))
        self.assertEqual(
            toy.writes,
            [
                b"Vibrate:10;",
                b"Vibrate:11;",
                b"Vibrate:0;",
                b"Rotate:0;",
                b"Vibrate:11;",
            ],
        )

    async def test_send_keeps_the_gap(self):
        toy = FakeToy({})
        link = make_link(toy, gap=0.05)
        start = time.monotonic()
        for _ in range(3):
            await link.send(b"Battery;")
        self.assertGreaterEqual(time.monotonic() - start, 0.1)


if __name__ == "__main__":
    unittest.main()
