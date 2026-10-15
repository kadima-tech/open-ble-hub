"""Channel selection and a paced command link over any transport.

The app picks its channels by characteristic property (i5.b, ToyBleCharacter)
and paces writes per toy (ToyCommandBean, y9.c, y9.e). ``ToyLink`` copies
that: it takes a ``write`` coroutine and is fed the notifications, so it runs
over bleak, a test double, or anything else.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from openble.lovense import commands, frames
from openble.lovense.replies import (
    BATTERY_RE,
    UNKNOWN,
    Capabilities,
    DeviceType,
    is_qcode,
    parse_battery,
    parse_capabilities,
    parse_device_type,
    qcode_reply,
)
from openble.lovense.uuids import PINNED_CHANNELS

MIN_GAP = 0.1  # seconds between commands to one toy
REPEAT_WINDOW = 1.0  # an identical motion command inside this is dropped
QCODE_DELAY = 0.2  # the app answers a QCode challenge after this
DEVICE_TYPE_TIMEOUT = 10.0
DEVICE_TYPE_RESEND = 1.0
OK = b"OK;"  # untagged acknowledgement, seen after each motion command


@dataclass(frozen=True)
class Channels:
    tx: str  # the one characteristic every command is written to
    rx: tuple[str, ...]  # every characteristic to subscribe to


def pick_channels(
    characteristics: Iterable[tuple[str, str, Iterable[str]]], model: str = ""
) -> Channels:
    """Choose TX and RX from ``(service uuid, char uuid, properties)`` in discovery order.

    Properties are bleak's names (``write``, ``notify``, …). TX is the last
    characteristic with ``write`` across all services. Write-without-response
    alone does not qualify. RX is every characteristic with ``notify``. A model
    in ``PINNED_CHANNELS`` (``be``) uses its fixed service instead, and fails
    if that TX characteristic appears more than once.
    """
    table = [
        (service.lower(), char.lower(), set(props))
        for service, char, props in characteristics
    ]
    pinned = PINNED_CHANNELS.get(model.lower())
    if pinned:
        service, tx, rx = pinned
        found = [char for svc, char, _props in table if svc == service and char == tx]
        if len(found) != 1:
            raise LookupError(f"expected one {tx} in {service}, found {len(found)}")
        return Channels(tx=tx, rx=(rx,))
    writable = [char for _svc, char, props in table if "write" in props]
    if not writable:
        raise LookupError("no characteristic with the write property")
    rx = tuple(char for _svc, char, props in table if "notify" in props)
    return Channels(tx=writable[-1], rx=rx)


class ToyLink:
    """Write commands to one toy and route what it sends back.

    ``write`` sends one GATT write to the TX characteristic. The app writes
    without response for every command except the few long text ones. Call
    ``feed`` from the notification callback of every RX characteristic. Text
    replies land in ``texts`` and valid 0xAA frames in ``frames``. A bare
    ``OK;``, which a Max sends after every motion command, only counts in
    ``acks``, so a long session does not fill ``texts``. A QCode
    challenge is answered on its own, as the app does.
    """

    def __init__(
        self,
        write: Callable[[bytes], Awaitable[None]],
        *,
        gap: float = MIN_GAP,
        repeat_window: float = REPEAT_WINDOW,
        qcode_delay: float = QCODE_DELAY,
        log: Callable[..., None] | None = None,
    ) -> None:
        self._write = write
        self._gap = gap
        self._repeat_window = repeat_window
        self._qcode_delay = qcode_delay
        self._log = log or (lambda kind, **payload: None)
        self._lock = asyncio.Lock()
        self._last_sent = float("-inf")
        self._last_motion: tuple[bytes, float] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self.acks = 0
        self.texts: asyncio.Queue[bytes] = asyncio.Queue()
        self.frames: asyncio.Queue[frames.Response] = asyncio.Queue()

    def feed(self, data: bytes) -> None:
        """Take one notification. Safe to call from a bleak callback."""
        data = bytes(data)
        if data[:1] == b"\xaa":
            try:
                self.frames.put_nowait(frames.parse_response(data))
            except ValueError as error:
                self._log("error", message=str(error))
            return
        if is_qcode(data):
            task = asyncio.get_running_loop().create_task(self._answer_qcode(data))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return
        if data == OK:
            self.acks += 1
            return
        self.texts.put_nowait(data)

    async def send(self, command: bytes) -> None:
        """Write one command, at least ``gap`` seconds after the last one."""
        async with self._lock:
            wait = self._last_sent + self._gap - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._log("write", message=command.hex(" "), data=command)
            await self._write(command)
            self._last_sent = time.monotonic()

    async def move(self, command: bytes) -> bool:
        """Send a motion command unless the same one went out within the repeat window.

        Motion levels persist on the toy, so the repeat adds nothing. Returns
        whether it was sent.
        """
        now = time.monotonic()
        if self._last_motion is not None:
            previous, sent_at = self._last_motion
            if previous == command and now - sent_at < self._repeat_window:
                return False
        await self.send(command)
        self._last_motion = (command, time.monotonic())
        return True

    async def stop(self, letters: Iterable[str] = ("v",)) -> None:
        """Send level 0 for each function. Do this before disconnecting."""
        for command in commands.stop(list(letters)):
            await self.send(command)
        self._last_motion = None

    async def ask(
        self, command: bytes, accept: Callable[[bytes], bool], timeout: float
    ) -> bytes:
        """Send ``command`` and return the first text reply ``accept`` takes.

        Other replies that arrive meanwhile are put back on ``texts``.
        """
        await self.send(command)
        return await self._wait_text(accept, timeout)

    async def device_type(self, timeout: float = DEVICE_TYPE_TIMEOUT) -> DeviceType:
        """Send ``DeviceType;`` until the toy answers, resending every second."""
        deadline = time.monotonic() + timeout
        while True:
            await self.send(commands.DEVICE_TYPE)
            remaining = deadline - time.monotonic()
            try:
                reply = await self._wait_text(
                    lambda data: parse_device_type(data) is not None,
                    min(DEVICE_TYPE_RESEND, max(remaining, 0)),
                )
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"no DeviceType reply in {timeout}s") from None
                continue
            if identity := parse_device_type(reply):
                return identity

    async def battery(self, timeout: float = 5.0) -> int | None:
        """``Battery;`` -> percent, or None for the unexplained ``s<n>;`` form."""
        reply = await self.ask(
            commands.BATTERY,
            lambda data: BATTERY_RE.match(data.strip()) is not None,
            timeout,
        )
        return parse_battery(reply)

    async def capabilities(self, timeout: float = 5.0) -> Capabilities | None:
        """``GetCap;`` -> Capabilities, or None on older firmware that lacks it."""
        reply = await self.ask(
            commands.GET_CAP,
            lambda data: data.startswith((b"CAP:", UNKNOWN + b"GetCap")),
            timeout,
        )
        return parse_capabilities(reply)

    async def close(self) -> None:
        """Cancel a QCode answer that has not gone out yet."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _answer_qcode(self, challenge: bytes) -> None:
        await asyncio.sleep(self._qcode_delay)
        reply = qcode_reply(challenge.decode("ascii"))
        self._log("qcode", message=f"{challenge.decode('ascii')} -> {reply}")
        await self.send(reply.encode("ascii"))

    async def _wait_text(
        self, accept: Callable[[bytes], bool], timeout: float
    ) -> bytes:
        skipped: list[bytes] = []
        try:
            async with asyncio.timeout(timeout):
                while True:
                    data = await self.texts.get()
                    if accept(data):
                        return data
                    skipped.append(data)
        finally:
            for data in skipped:
                self.texts.put_nowait(data)
