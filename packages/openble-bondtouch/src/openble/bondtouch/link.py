"""A bracelet session over any transport: setup handshake, routing and pacing.

``BraceletLink`` takes a ``write(uuid, payload)`` coroutine, and optionally a
``read(uuid)`` one, and is fed every notification. It answers the token,
AUID and paired-signal requests as the app does, collects touch patterns,
and sends commands one at a time with the app's pauses (BleCommandHandler):
it holds commands while the bracelet is busy, and on V1 waits for each
``ffa7`` result and retries once. OS-level bonding is left to the caller.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Sequence
from typing import Any

from openble.bondtouch import uuids, v1, v2, v3
from openble.bondtouch.colours import BLACK, RGB
from openble.bondtouch.identify import MINI, V1, V3, V4, generation_of, is_v3
from openble.bondtouch.patterns import from_samples, to_samples
from openble.bondtouch.v2 import TOKEN_VALUE, TouchMessage

COMMAND_TIMEOUT = 10.0  # per attempt
RETRY_DELAY = 3.5  # after a negative V1 result
V1_BUSY_PAUSE = 30.0
BUSY_PAUSE = 15.0  # V2 MSG and the V3 busy states
QUEUE_PAUSE = 5.0  # after a run-queue command, and in QUEUE_EXECUTING


class CommandError(Exception):
    """A V1 command came back with a result other than success, twice."""

    def __init__(self, result: v1.Result) -> None:
        super().__init__(f"{result.name} for seq {result.seq}")
        self.result = result


def notify_uuids(generation: str) -> tuple[str, ...]:
    """The characteristics to subscribe to, in the app's order, before ``start``.

    V4 and Mini also have ``BOND_TRIGGER``; subscribe to it only to bond.
    """
    if generation == V1:
        return (uuids.BATTERY, uuids.EVENT, uuids.STATE, uuids.V1_RESULT)
    if generation == V3:
        return (uuids.V3_COMMAND, uuids.V3_TOUCH)
    return (uuids.BATTERY, uuids.EVENT, uuids.STATE)


async def detect_generation(
    read: Callable[[str], Awaitable[bytes]], service_uuids: Iterable[str]
) -> str:
    """V3 if the Bond More service is there, else the generation ``ff10`` names."""
    if is_v3(service_uuids):
        return V3
    return generation_of(await read(uuids.API_VERSION))


class BraceletLink:
    """Drive one bracelet of a known generation.

    Call ``feed`` from the notification callback of every characteristic in
    ``notify_uuids(generation)``, then ``start``. ``connected`` is set once the
    bracelet reports it is set up and idle. Received touches land in
    ``touches``; other events (taps, V3 reports and ACKs) in ``events``.
    ``needs_setup`` turns True when the bracelet rejects the AUID or, on V3,
    reports out-of-box state, and back to False once it is connected. A
    bracelet holding another AUID answers ``AUID_ERROR``, goes to OOBE and
    flashes; the app then asks the wearer to double-tap it to continue.
    """

    def __init__(
        self,
        write: Callable[[str, bytes], Awaitable[None]],
        generation: str,
        auid: int,
        *,
        read: Callable[[str], Awaitable[bytes]] | None = None,
        command_timeout: float = COMMAND_TIMEOUT,
        retry_delay: float = RETRY_DELAY,
        log: Callable[..., None] | None = None,
    ) -> None:
        if not 0 <= auid <= 0xFFFFFFFF:
            raise ValueError("the AUID is a 32-bit number")
        self.generation = generation
        self.auid = auid
        self._write = write
        self._read = read
        self._command_timeout = command_timeout
        self._retry_delay = retry_delay
        self._log = log or (lambda kind, **payload: None)
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._paused_until = 0.0
        self._resumed = asyncio.Event()
        self._resumed.set()
        self._seq = 0
        self._pending: dict[int, asyncio.Future[v1.Result]] = {}
        self._burst_sent = False
        self._v1_recorder = v1.TouchRecorder()
        self._recorder = v2.TouchRecorder(generation)
        self._assembler = v3.TouchAssembler()
        self.state: int | None = None
        self.battery: int | None = None
        self.firmware: tuple[int, ...] | None = None
        self.needs_setup = False
        self.connected = asyncio.Event()
        self.touches: asyncio.Queue[TouchMessage] = asyncio.Queue()
        self.events: asyncio.Queue[Any] = asyncio.Queue()

    @property
    def command_uuid(self) -> str:
        return uuids.V3_COMMAND if self.generation == V3 else uuids.COMMAND

    async def start(self) -> None:
        """Begin setup once notifications are on, as each manager does.

        With ``read``, V1, V2, V4 and Mini also read ``ff06`` first, so
        ``battery`` is set before the first battery notification.
        """
        if self.generation != V3 and self._read is not None:
            self.feed(uuids.BATTERY, await self._read(uuids.BATTERY))
        if self.generation == V3:
            await self.send(uuids.V3_COMMAND, v3.HELLO)
        elif self.generation in (V4, MINI):
            if self._read is not None:
                self.feed(uuids.STATE, await self._read(uuids.STATE))
        else:
            await self.send(uuids.TOKEN, TOKEN_VALUE)

    async def wait_connected(self, timeout: float = 30.0) -> None:
        async with asyncio.timeout(timeout):
            await self.connected.wait()

    def feed(self, uuid: str, data: bytes) -> None:
        """Take one notification (or read value). Safe to call from a bleak callback."""
        uuid, data = uuid.lower(), bytes(data)
        if not data:
            return
        if uuid == uuids.BATTERY:
            if self.generation == V1:
                self.battery = v1.battery_percent(data)
            else:
                self.battery = v2.battery_percent(data)
        elif uuid == uuids.STATE:
            if self.generation == V1:
                self._on_v1_state(v1.parse_state(data))
            else:
                self._on_state(v2.parse_state(data))
        elif uuid == uuids.EVENT:
            if self.generation == V1:
                self._on_v1_event(v1.parse_event(data))
            else:
                self._on_event(v2.parse_event(data, self.generation))
        elif uuid == uuids.V1_RESULT:
            result = v1.parse_result(data)
            future = self._pending.pop(result.seq, None)
            if future is not None and not future.done():
                future.set_result(result)
        elif uuid == uuids.V3_COMMAND:
            self._on_v3(v3.parse(data))
        elif uuid == uuids.V3_TOUCH:
            message = self._assembler.feed(data)
            if message is not None and message.samples:
                pattern = from_samples(message.samples)
                self.touches.put_nowait(TouchMessage(pattern, message.slot or 1))
        else:
            self._log("ignored", message=f"{uuid} {data.hex(' ')}")

    async def send(self, uuid: str, payload: bytes) -> None:
        """One GATT write, with no other write in flight."""
        async with self._lock:
            self._log("write", message=f"{uuid} {payload.hex(' ')}", data=payload)
            await self._write(uuid, payload)

    async def command(self, payload: bytes, uuid: str | None = None) -> None:
        """Send a command once the bracelet is not busy.

        On V1 a command to ``ffa6`` waits for its ``ffa7`` result and is
        retried once, after 3.5 s on a negative result. A run-queue command
        (``0x32``) pauses later commands for 5 s while the bracelet plays.
        """
        uuid = (uuid or self.command_uuid).lower()
        await self._wait_resumed()
        if self.generation == V1 and uuid == uuids.COMMAND and len(payload) >= 4:
            await self._v1_command(payload)
        else:
            await self.send(uuid, payload)
        if self.generation != V1 and uuid == uuids.COMMAND and payload[:1] == b"\x32":
            self._pause(QUEUE_PAUSE)

    async def show_colour(self, colour: RGB) -> None:
        """Light the bracelet in one colour until it is cleared."""
        if self.generation == V1:
            await self.command(v1.colour(colour))
        elif self.generation == V3:
            await self.command(v3.show_colour(colour))
        else:
            await self.command(v2.show_colour(colour))

    async def clear_colour(self) -> None:
        """Turn the LEDs off. On V1 this sends colour black, which is inferred."""
        if self.generation == V1:
            await self.command(v1.colour(BLACK))
        elif self.generation == V3:
            await self.command(v3.LED_OFF)
        else:
            await self.command(v2.clear_colour())

    async def play(
        self,
        pattern: Sequence[int],
        colour: RGB,
        strength: int = v2.DEFAULT_STRENGTH,
        slot: int | None = None,
    ) -> None:
        """Play a touch pattern the way the app plays a partner's touch.

        ``strength`` applies to V2, V4 and Mini. ``slot`` is the sending
        partner's slot on V4 and V3.
        """
        if self.generation == V1:
            for payload in v1.play_pattern(pattern, v1.led_id_for(colour)):
                await self.command(payload)
        elif self.generation == V3:
            frames = v3.touch_frames(to_samples(pattern), colour, slot=slot or 1)
            for payload in frames:
                await self.command(payload, uuids.V3_TOUCH)
        else:
            for payload in v2.play(pattern, colour, self.generation, strength, slot):
                await self.command(payload)

    async def close(self) -> None:
        """Cancel answers not sent yet and fail commands still waiting."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for future in self._pending.values():
            future.cancel()
        self._pending.clear()

    def _on_v1_state(self, state: v1.State) -> None:
        self.state = state.paired_state
        if state.paired_state == v1.WAITING_AUID:
            self._spawn(self.send(uuids.AUID, v2.auid(self.auid)))
        elif state.paired_state == v1.IDLE:
            self._set_connected()
        elif state.paired_state == v1.BUSY:
            self._pause(V1_BUSY_PAUSE)

    def _on_v1_event(self, event: v1.Event) -> None:
        if event.event_id == v1.PAIRED_SIGNAL:
            self._spawn(self.send(uuids.COMMAND, v1.PAIRED_ACK))
        elif event.event_id == v1.AUID_ERROR:
            self.needs_setup = True
        if event.event_id == v1.SEND_MSG:
            pattern = self._v1_recorder.feed(event, time.monotonic())
            if pattern:
                self.touches.put_nowait(TouchMessage(pattern))
        else:
            self.events.put_nowait(event)

    def _on_state(self, state: v2.State) -> None:
        # The app acts only when the bond state changes (m4237O); the bracelet
        # repeats it when another byte, such as ledBusy, changes.
        if state.bond_state == self.state:
            return
        self.state = state.bond_state
        if state.bond_state == v2.WAITING_TOKEN:
            self._spawn(self.send(uuids.TOKEN, TOKEN_VALUE))
        elif state.bond_state == v2.WAITING_AUID:
            self._spawn(self.send(uuids.AUID, v2.auid(self.auid)))
        elif state.bond_state == v2.CONNECTED:
            self._set_connected()
        elif state.bond_state == v2.MSG:
            self._pause(BUSY_PAUSE)
        elif state.bond_state == v2.QUEUE_EXECUTING:
            self._pause(QUEUE_PAUSE)

    def _on_event(self, event: v2.Event) -> None:
        if event.event_id == v2.PAIRED_SIGNAL:
            self._spawn(self.send(uuids.COMMAND, v2.PAIRED_ACK))
        elif event.event_id == v2.AUID_ERROR:
            self.needs_setup = True
        if event.event_id in (v2.SEND_MSG, v2.SEND_MSG_TIMEOUT):
            message = self._recorder.feed(event)
            if message is not None:
                self.touches.put_nowait(message)
        else:
            self.events.put_nowait(event)

    def _on_v3(self, message: v3.Message) -> None:
        if message.kind == "state":
            self._on_v3_state(message.value)
            return
        if message.kind == "event" and message.value[0] == v3.PAIRED_SIGNAL:
            self._spawn(self.send(uuids.V3_COMMAND, v3.PAIRED_ACK))
            return
        if message.kind == "firmware":
            self.firmware = message.value
        self.events.put_nowait(message)

    def _on_v3_state(self, state: int) -> None:
        self.state = state
        if state == v3.WAITING_TOKEN:
            self._spawn(self.send(uuids.V3_COMMAND, v3.TOKEN))
        elif state == v3.WAITING_AUID:
            self._spawn(self.send(uuids.V3_COMMAND, v3.auid(self.auid)))
        elif state == v3.OOBE:
            self.needs_setup = True
        elif state == v3.CONNECTED:
            self._set_connected()
            if not self._burst_sent:
                self._burst_sent = True
                self._spawn(self._send_burst())
        elif state in v3.BUSY_STATES:
            self._pause(BUSY_PAUSE)
        elif state == v3.WAIT_FOR_ACT_PAIRED:
            self._spawn(self.send(uuids.V3_COMMAND, v3.PAIRED_ACK))

    async def _send_burst(self) -> None:
        # The app reads 2a19 before the last write; that read is the caller's.
        for payload in v3.CONNECT_BURST:
            await self.send(uuids.V3_COMMAND, payload)

    async def _v1_command(self, payload: bytes) -> None:
        for attempt in (1, 2):
            seq = self._seq
            self._seq = (self._seq + 1) & 0xFFFF
            future = asyncio.get_running_loop().create_future()
            self._pending[seq] = future
            await self.send(uuids.COMMAND, v1.with_seq(payload, seq))
            try:
                async with asyncio.timeout(self._command_timeout):
                    result = await future
            except TimeoutError:
                self._pending.pop(seq, None)
                if attempt == 2:
                    raise
                continue
            if result.ok:
                return
            self._log("error", message=f"{result.name} for seq {seq}")
            if attempt == 2:
                raise CommandError(result)
            await asyncio.sleep(self._retry_delay)

    def _set_connected(self) -> None:
        self.needs_setup = False
        self.connected.set()
        self._paused_until = 0.0
        self._resumed.set()

    def _pause(self, seconds: float) -> None:
        self._paused_until = time.monotonic() + seconds
        self._resumed.clear()

    async def _wait_resumed(self) -> None:
        while (left := self._paused_until - time.monotonic()) > 0:
            try:
                async with asyncio.timeout(left):
                    await self._resumed.wait()
            except TimeoutError:
                break
            if self._resumed.is_set():
                break

    def _spawn(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
