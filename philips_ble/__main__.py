"""Command line for the local Mac BLE client.

Examples::

    python -m philips_ble scan
    python -m philips_ble brush
    python -m philips_ble scale
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from philips_ble.scale_link import DEFAULT_USER_NAME, DEFAULT_USER_NUMBER, hex_decode
from philips_ble.session import run_collect, run_scan, run_watch


def _build() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="philips-ble",
        description=(
            "Connect to a Philips Lifesense scale or a Philips Sonicare toothbrush "
            "and record the characteristics described in docs/."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="List scale and Sonicare advertisements")
    scan.add_argument(
        "--seconds", type=float, default=8, help="How long to listen (default 8)"
    )
    scan.add_argument(
        "--all", action="store_true", help="Also list advertisements that do not match"
    )

    for name, default_seconds, help_text in (
        ("brush", 25, "Read and subscribe to the Sonicare handle"),
        ("scale", 60, "Read identity and listen for scale measurements"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument(
            "--address",
            help="Device address from a previous scan. On macOS this is a UUID.",
        )
        command.add_argument(
            "--seconds",
            type=float,
            default=default_seconds,
            help=f"How long to listen after subscribing (default {default_seconds})",
        )
        command.add_argument(
            "--scan-seconds",
            type=float,
            default=8,
            help="How long to look for the device first (default 8)",
        )
        command.add_argument("--out", type=Path, help="Append JSON lines to this file")
        if name == "scale":
            command.add_argument(
                "--store",
                type=Path,
                default=Path(".philips-scale.json"),
                help="Where to keep the scale password and broadcast id (default .philips-scale.json)",
            )
            command.add_argument(
                "--user-number",
                type=int,
                default=DEFAULT_USER_NUMBER,
                help="User slot written during a new pair (default 1)",
            )
            command.add_argument(
                "--user-name",
                default=DEFAULT_USER_NAME,
                help="User name written during a new pair (default User)",
            )
            command.add_argument(
                "--password",
                help="8 hex digits from a previous pair, if this Mac does not have the store yet",
            )
            command.add_argument(
                "--age", type=int, help="Age in years, sent with --height-cm and --sex"
            )
            command.add_argument(
                "--height-cm", type=int, help="Height in centimetres (100..204)"
            )
            command.add_argument(
                "--sex", choices=("male", "female"), help="male or female"
            )

    watch = sub.add_parser(
        "watch", help="Keep scanning and connect as soon as the scale advertises"
    )
    watch.add_argument("--address", help="Only this scale. On macOS this is a UUID.")
    watch.add_argument("--out", type=Path, help="Append JSON lines to this file")
    watch.add_argument(
        "--idle-seconds",
        type=float,
        default=180,
        help="How long to hold the link after the last indication (default 180)",
    )
    watch.add_argument(
        "--store",
        type=Path,
        default=Path(".philips-scale.json"),
        help="Password and broadcast id store",
    )
    watch.add_argument("--user-number", type=int, default=DEFAULT_USER_NUMBER)
    watch.add_argument("--user-name", default=DEFAULT_USER_NAME)
    watch.add_argument("--password", help="8 hex digits from a previous pair")
    watch.add_argument(
        "--age", type=int, help="Age in years, sent with --height-cm and --sex"
    )
    watch.add_argument("--height-cm", type=int)
    watch.add_argument("--sex", choices=("male", "female"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build().parse_args(argv)
    try:
        if args.command == "scan":
            return asyncio.run(run_scan(args.seconds, args.all))
        password = None
        store_path = None
        user_number = DEFAULT_USER_NUMBER
        user_name = DEFAULT_USER_NAME
        age = None
        height_cm = None
        sex = None
        if args.command in {"scale", "watch"}:
            store_path = args.store
            user_number = args.user_number
            user_name = args.user_name
            age = args.age
            height_cm = args.height_cm
            sex = args.sex
            given = [age is not None, height_cm is not None, sex is not None]
            if any(given) and not all(given):
                print("Pass --age, --height-cm, and --sex together.")
                return 2
            if args.password:
                try:
                    password = hex_decode(args.password)
                except ValueError as exc:
                    print(exc)
                    return 2
                if len(password) != 4:
                    print("--password must be 8 hex digits (4 bytes)")
                    return 2
        if args.command == "watch":
            return asyncio.run(
                run_watch(
                    args.address,
                    args.out,
                    args.idle_seconds,
                    store_path=store_path,
                    user_number=user_number,
                    user_name=user_name,
                    password=password,
                    age=age,
                    height_cm=height_cm,
                    sex=sex,
                )
            )
        return asyncio.run(
            run_collect(
                args.command,
                args.address,
                args.seconds,
                args.scan_seconds,
                args.out,
                store_path=store_path,
                user_number=user_number,
                user_name=user_name,
                password=password,
                age=age,
                height_cm=height_cm,
                sex=sex,
            )
        )
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
