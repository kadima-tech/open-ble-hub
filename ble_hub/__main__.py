"""Run the Open BLE Hub: Bluetooth listener, Google uploads and the configuration UI.

Example::

    python -m ble_hub --data-dir /var/lib/open-ble-hub --port 8080
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
from pathlib import Path

from aiohttp import web

from ble_hub.db import Database
from ble_hub.hub import Hub
from ble_hub.web import create_app


class NoBluetooth:
    """Stand-in listener for running the UI without a Bluetooth adapter."""

    def status(self) -> dict:
        return {
            "state": "disabled",
            "address": None,
            "paired": False,
            "pairing": False,
            "pairing_seconds_left": 0,
            "last_pair_result": None,
            "last_seen": None,
            "last_error": "Started with --no-bluetooth.",
            "nearby": [],
        }

    def start_pairing(self, seconds: int = 180) -> None:
        pass

    def forget(self) -> None:
        pass


async def serve(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir)
    db = Database(data_dir / "open-ble-hub.db")
    hub = Hub(db)
    if args.no_bluetooth:
        listener = NoBluetooth()
    else:
        from ble_hub.listener import ScaleListener

        listener = ScaleListener(hub, data_dir)
    runner = web.AppRunner(create_app(hub, listener), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, args.host, args.port).start()
    db.log(f"Open BLE Hub started on port {args.port}.")
    tasks = [asyncio.create_task(hub.upload_loop())]
    if not args.no_bluetooth:
        tasks.append(asyncio.create_task(listener.run()))
    try:
        await asyncio.Event().wait()
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await hub.close()
        await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="open-ble-hub", description="Bluetooth health devices to Google Health"
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Where the database and scale pairing live (default ./data)",
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Address for the UI (default all interfaces)"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Port for the UI (default 8080)"
    )
    parser.add_argument(
        "--no-bluetooth",
        action="store_true",
        help="Run the UI only, without the scale listener",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(args))


if __name__ == "__main__":
    main()
