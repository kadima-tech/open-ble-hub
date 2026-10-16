"""The command link and the app's start-up sequence, over any transport.

``nevis::ConnectorImpl`` keeps one command in flight and waits for its JSON
reply before the next, except for ``L…`` and ``Q…``, which get none.
``MuseLink`` copies that: it takes a ``write`` coroutine and is fed the
``SERIAL`` notifications, so it runs over bleak, a test double, or anything
else. ``prepare`` runs states 3-8 of the app's path to streaming.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from openble.muse import commands, models, uuids
from openble.muse.replies import (
    MuseError,
    Replies,
    Status,
    Version,
    check_protocol,
    parse_status,
    parse_version,
    return_code,
)

# interaxon::cmd::*_TIMEOUT, in seconds.
VERSION_TIMEOUT = 10.0
STATUS_TIMEOUT = 8.0
SERIAL_TIMEOUT = 6.0
KEEP_ALIVE_INTERVAL = 2.5  # while paused
DATA_TIMEOUT = 6.0  # no data while streaming for this long is an error

LICENCE_INVALID = 2  # dc001 rc


class BootloaderError(MuseError):
    """The headband runs its bootloader. Send ``*1`` (``boot_to_headset``) and reconnect."""


@dataclass(frozen=True)
class Session:
    """What ``prepare`` learned, and what to subscribe to before ``start_streaming``."""

    version: Version
    status: Status
    model: str
    preset: str
    layout: str  # "per-sensor", "universal" or "ble4"
    # Data characteristics to subscribe to. TIME_SYNC is left out: its message
    # format is still open.
    subscribe: tuple[str, ...]


class MuseLink:
    """Send commands to one headband and match its JSON replies.

    ``write`` sends one framed command to ``SERIAL``. The app writes without
    response where the characteristic allows it. Call ``feed`` from the
    ``SERIAL`` notification callback.
    """

    def __init__(
        self,
        write: Callable[[bytes], Awaitable[None]],
        *,
        log: Callable[..., None] | None = None,
    ) -> None:
        self._write = write
        self._log = log or (lambda kind, **payload: None)
        self._replies = Replies()
        self._lock = asyncio.Lock()
        self._pending: asyncio.Future[dict[str, Any]] | None = None

    def feed(self, data: bytes) -> None:
        """Take one ``SERIAL`` notification. Safe to call from a bleak callback."""
        reply = self._replies.feed(bytes(data))
        if reply is None:
            return
        self._log("reply", message=str(reply), data=reply)
        if self._pending is not None and not self._pending.done():
            self._pending.set_result(reply)
        else:
            self._log("unsolicited", message=str(reply), data=reply)

    async def command(
        self, command: str, timeout: float = SERIAL_TIMEOUT
    ) -> dict[str, Any] | None:
        """Write one command and return its reply, or None for ``L…``/``Q…``."""
        payload = commands.encode(command)
        async with self._lock:
            if not commands.expects_reply(command):
                self._log("write", message=command, data=payload)
                await self._write(payload)
                return None
            self._pending = asyncio.get_running_loop().create_future()
            try:
                self._log("write", message=command, data=payload)
                await self._write(payload)
                async with asyncio.timeout(timeout):
                    return await self._pending
            except TimeoutError:
                self._replies.reset()
                raise TimeoutError(f"no reply to {command!r} in {timeout}s") from None
            finally:
                self._pending = None

    async def version(
        self, offered: int = 7, timeout: float = VERSION_TIMEOUT
    ) -> Version:
        return parse_version(await self._reply(commands.version(offered), timeout))

    async def status(self, timeout: float = STATUS_TIMEOUT) -> Status:
        return parse_status(await self._reply(commands.STATUS, timeout))

    async def halt(self, timeout: float = SERIAL_TIMEOUT) -> None:
        """``h``. The app drops the connection on anything but ``{"rc":0}``."""
        reply = await self._reply(commands.HALT, timeout)
        if return_code(reply) != 0:
            raise MuseError(f"halt failed: {reply}")

    async def set_preset(self, code: str, timeout: float = SERIAL_TIMEOUT) -> None:
        """``p<code>``. The headband refuses while streaming, so halt first."""
        reply = await self._reply(commands.preset(code), timeout)
        if return_code(reply) != 0:
            raise MuseError(
                f"preset {code} refused (wrong model, or streaming): {reply}"
            )

    async def start_streaming(
        self, command: str | None = None, timeout: float = SERIAL_TIMEOUT
    ) -> int:
        """``dc001`` (or ``command``, e.g. ``commands.START_LEGACY``); returns ``rc``.

        ``rc`` 2 is an invalid headband licence and raises. Any other
        non-zero ``rc`` means it was already streaming, which the app accepts.
        """
        reply = await self._reply(command or commands.start_streaming(), timeout)
        rc = return_code(reply)
        if rc == LICENCE_INVALID:
            raise MuseError(f"the headband licence is not valid: {reply}")
        if rc != 0:
            self._log("already-streaming", message=str(reply), data=reply)
        return rc

    async def keep_alive(self, timeout: float = SERIAL_TIMEOUT) -> None:
        """``k``: send every ``KEEP_ALIVE_INTERVAL`` while paused."""
        await self._reply(commands.KEEP_ALIVE, timeout)

    async def led(self, on: bool) -> None:
        """``L1``/``L0``; Muse S and Athena only. No reply comes back."""
        await self.command(commands.led(on))

    async def boot_to_headset(self, timeout: float = SERIAL_TIMEOUT) -> None:
        """``*1``: leave the bootloader. Reconnect once the headband reboots."""
        reply = await self._reply(commands.BOOT_TO_HEADSET, timeout)
        if return_code(reply) == 1:
            raise MuseError(f"firmware CRC failure: {reply}")

    async def prepare(
        self, preset: str | None = None, offered_version: int = 7
    ) -> Session:
        """Version, status, halt, preset, status: the app's path up to subscribing.

        ``preset`` defaults to the app's default for the model. Next, subscribe
        to ``Session.subscribe`` and call ``start_streaming``.
        """
        version = await self.version(offered_version)
        check_protocol(version.protocol)
        if version.in_bootloader:
            raise BootloaderError(f"headband is in its bootloader: {version.raw}")
        model = (await self.status()).model
        code = (preset or models.default_preset(model)).upper()
        await self.halt()
        await self.set_preset(code)
        status = await self.status()
        subscribe = tuple(
            uuid
            for uuid in models.characteristics(model, version.protocol)
            if uuid != uuids.TIME_SYNC
        )
        return Session(
            version=version,
            status=status,
            model=model,
            preset=code,
            layout=models.layout(version.protocol),
            subscribe=subscribe,
        )

    async def _reply(self, command: str, timeout: float) -> dict[str, Any]:
        reply = await self.command(command, timeout)
        assert reply is not None
        return reply
