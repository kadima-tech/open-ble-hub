"""MuseLink and the start-up sequence against a fake headband."""

import asyncio
import json
import unittest

from openble.muse import uuids
from openble.muse.link import BootloaderError, MuseLink
from openble.muse.replies import MuseError

VERSION = {"ap": "headset", "fw": "3.1.0", "pv": 4, "rc": 0}
STATUS = {"hn": "MuseS-1A2B", "sn": "7001-…", "ma": "…", "id": "…", "bp": 64, "rc": 0}


def chunks(reply: dict) -> list[bytes]:
    text = json.dumps(reply).encode("ascii")
    return [
        bytes((len(text[i : i + 19]),)) + text[i : i + 19]
        for i in range(0, len(text), 19)
    ]


class FakeHeadband:
    """Answers each framed command with chunked JSON notifications."""

    def __init__(self, replies: dict[str, dict]):
        self.replies = replies
        self.commands: list[str] = []
        self.link: MuseLink | None = None

    async def write(self, payload: bytes) -> None:
        self.assertFramed(payload)
        command = payload[1:-1].decode("ascii")
        self.commands.append(command)
        reply = self.replies.get(command, self.replies.get(command[0]))
        for chunk in chunks(reply) if reply is not None else []:
            asyncio.get_running_loop().call_soon(self.link.feed, chunk)

    @staticmethod
    def assertFramed(payload: bytes) -> None:
        assert payload[0] == len(payload) - 1 and payload.endswith(b"\n"), payload


def make_link(headband: FakeHeadband) -> MuseLink:
    link = MuseLink(headband.write)
    headband.link = link
    return link


def athena(**overrides) -> FakeHeadband:
    replies = {"v": VERSION, "s": STATUS, "h": {"rc": 0}, "p": {"rc": 0}}
    replies["d"] = {"rc": 0}
    return FakeHeadband({**replies, **overrides})


class PrepareTests(unittest.IsolatedAsyncioTestCase):
    async def test_athena_sequence(self):
        headband = athena()
        link = make_link(headband)
        session = await link.prepare("1045")
        self.assertEqual(session.model, "MS_03")
        self.assertEqual(session.layout, "ble4")
        self.assertEqual(session.subscribe, (uuids.UNIVERSAL, uuids.MUSE_DEBUG))
        self.assertEqual(await link.start_streaming(), 0)
        self.assertEqual(headband.commands, ["v7", "s", "h", "p1045", "s", "dc001"])

    async def test_default_preset_and_time_sync_left_out(self):
        headband = athena(v={**VERSION, "pv": 5})
        session = await make_link(headband).prepare()
        self.assertEqual(session.preset, "1021")
        self.assertNotIn(uuids.TIME_SYNC, session.subscribe)
        self.assertIn("p1021", headband.commands)

    async def test_muse_2_per_sensor(self):
        headband = athena(v={**VERSION, "pv": 1}, s={**STATUS, "sn": "4210-…"})
        session = await make_link(headband).prepare()
        self.assertEqual((session.model, session.layout), ("MU_03", "per-sensor"))
        self.assertEqual(len(session.subscribe), 13)
        self.assertEqual(session.preset, "21")

    async def test_bootloader(self):
        headband = athena(v={**VERSION, "ap": "bootloader"})
        with self.assertRaises(BootloaderError):
            await make_link(headband).prepare()
        self.assertEqual(headband.commands, ["v7"])

    async def test_protocol_out_of_range(self):
        with self.assertRaisesRegex(MuseError, "library too old"):
            await make_link(athena(v={**VERSION, "pv": 8})).prepare()

    async def test_halt_and_preset_refusals(self):
        with self.assertRaisesRegex(MuseError, "halt"):
            await make_link(athena(h={"rc": 1})).prepare()
        with self.assertRaisesRegex(MuseError, "preset"):
            await make_link(athena(p={"rc": 1})).prepare("1045")


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_licence_and_already_streaming(self):
        link = make_link(athena(d={"rc": 2}))
        with self.assertRaisesRegex(MuseError, "licence"):
            await link.start_streaming()
        link = make_link(athena(d={"rc": 1}))
        self.assertEqual(await link.start_streaming(), 1)

    async def test_led_needs_no_reply(self):
        headband = FakeHeadband({})
        link = make_link(headband)
        await link.led(True)
        self.assertEqual(headband.commands, ["L1"])

    async def test_timeout_then_next_command(self):
        headband = FakeHeadband({"s": STATUS})
        link = make_link(headband)
        link.feed(b'\x05{"rc"')  # a stray partial reply is discarded on timeout
        with self.assertRaises(TimeoutError):
            await link.command("h", timeout=0.05)
        status = await link.status(timeout=1)
        self.assertEqual(status.name, "MuseS-1A2B")

    async def test_unsolicited_reply_is_logged(self):
        logged = []
        link = MuseLink(None, log=lambda kind, **payload: logged.append(kind))
        for chunk in chunks({"rc": 0}):
            link.feed(chunk)
        self.assertEqual(logged, ["reply", "unsolicited"])


if __name__ == "__main__":
    unittest.main()
