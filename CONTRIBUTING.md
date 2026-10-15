# Contributing

Open BLE Hub welcomes fixes and support for more devices. Contributions are licensed under [MIT No Attribution (MIT-0)](LICENSE), copyright 2026 Kadima Tech.

## Development setup

Python 3.11 or newer, on macOS or Linux (including Raspberry Pi). Windows is not supported. A Bluetooth LE adapter is required only when you talk to a real device.

```bash
git clone https://github.com/kadima-tech/open-ble-hub.git
cd open-ble-hub
make venv
```

`make venv` creates `.venv` and installs every library and app in [requirements-dev.txt](requirements-dev.txt) editable, with their dependencies (`bleak`, `aiohttp`). It reinstalls when that file or a `pyproject.toml` changes. `make clean` removes `.venv` and leaves `./data` in place.

| Command | What it does |
| --- | --- |
| `make run` | Bathroom Hub with Bluetooth. UI at <http://localhost:8080>, data in `./data`. |
| `make ui` | Same UI with `--no-bluetooth`. |
| `make test` | Unit tests of every library and app, and `tests/`. No device and no network. |
| `make build` | Sdists and wheels of the libraries in `dist/`. |
| `make scan`, `make scale`, `make watch` | `python -m ble_probe` against a live device. Pass extra flags with `ARGS`. |
| `make help` | Every target. |

`make run PORT=9000 DATA_DIR=/tmp/hub` overrides the port and data folder. On macOS, allow Bluetooth for your terminal under System Settings → Privacy & Security → Bluetooth.

`./data` holds the SQLite database. `.philips-scale.json` holds the scale password and broadcast id. Both are gitignored. Deploy a Pi with `sudo ./apps/bathroom-hub/deploy/install.sh` from a copy of the repository on that machine.

## Tests

`make test` runs the standard-library test runner once per test folder, for example:

```bash
.venv/bin/python -m unittest discover -s packages/openble-lifesense/tests
```

Each library and app keeps its tests in its own `tests/test_*.py`. The root `tests/` holds the Bluetooth suite that drives both apps. Tests are built from captured packets and fakes (`unittest.mock`, `aiohttp.test_utils`). They do not need a scale, an adapter, or Google credentials.

New behaviour needs tests in that style. A protocol change should carry the bytes it was checked against, the way `packages/openble-lifesense/tests/test_packets.py` and `test_link.py` do.

pytest is not installed or configured. `.pytest_cache/` is listed in `.gitignore`, and there is no coverage tool.

### Bleak upgrades

`make test` installs `bleak` from the apps' `pyproject.toml` files (`bleak>=3.0.2,<4`) and runs `tests/test_bluetooth.py` on the Linux and macOS matrix. Those tests import bleak and drive `bathroom_hub/listener.py` and `ble_probe/session.py` with fakes spec'd to the installed bleak classes: discovery with `return_adv=True`, detection callbacks, `BleakClient` as a context manager, service and characteristic enumeration, read and write with `response=True`, start and stop notify (including the `8A82` stop-then-restart), `is_connected`, and `BleakError`, including the "Insufficient Encryption" hint. A signature change fails CI. The tests do not open a radio. The upper bound means the next major version arrives as a Dependabot pull request instead of installing on its own.

CI does not replace a hardware smoke test. Before merging a bleak upgrade, pair a DL8780 and take a weigh on both stacks this project runs on:

- Raspberry Pi with BlueZ: `make run`, start pairing in the UI, hold the scale's unit button for 3 seconds, then step on. The weigh should show on the dashboard.
- Mac: the same pair and weigh, with Bluetooth allowed for the terminal under System Settings → Privacy & Security → Bluetooth.

## Linters and CI

[Ruff](https://docs.astral.sh/ruff/) 0.17.0 lints and formats Python. The config is [ruff.toml](ruff.toml), aimed at Python 3.11. There is no type checker and no pre-commit hook.

```bash
python3 -m pip install ruff==0.17.0
make lint
```

`make lint` runs `ruff check` and `ruff format --check`. Match that, and match the file you are editing. Quotes inside f-strings stay as they are: reusing the outer quote is Python 3.12 syntax, and this project is 3.11.

GitHub Actions runs that lint, and `make test`, on every push and pull request. Tests run on Python 3.11, 3.12, 3.13 and 3.14, on Linux and macOS. CI has to pass before merge.

## Pull requests

Branch from `main`. Keep the change focused.

- Describe what changed, why, and how you tested it. The pull request template is the checklist.
- Add tests for new behaviour. `make test` passes.
- `make lint` passes, and so does CI.
- A new device follows [Adding a device](README.md#adding-a-device): a library in `packages/` with packet tests and notes in its `docs/`, then front-end wiring, such as `listener.py`, `devices.py`, and `google_health.py` in the Bathroom Hub when a new measurement is written.
- UI work follows [DESIGN.md](DESIGN.md). Pages stay server-rendered and usable with no internet; the font is vendored.

## Coding style

- Python 3.11+. Modules use `from __future__ import annotations` and type hints (`str | None`, `dict[str, Any]`).
- Double quotes. A short module docstring. Imports are standard library, then third party, then local.
- Comments explain a protocol detail or a captured-packet fact. Names say what the value is (`weight_kg`, `refresh_token`).
- Device bytes stay in a library under `packages/`, with the write-up in its `docs/`. Libraries have no runtime dependencies and import no Bluetooth stack. Front-ends live in `apps/`.
- Runtime dependencies are the `dependencies` in each `pyproject.toml`. There is no lockfile. The libraries are published to PyPI from a tag (see [Releasing a library](README.md#releasing-a-library)). The apps are not published: run them as `python -m bathroom_hub` and `python -m ble_probe`, and the Pi installs them with pip from the checkout.

A new dependency needs a reason in the pull request: what the standard library cannot do, and that it still installs on a Raspberry Pi. `apps/bathroom-hub/deploy/install.sh` uses [piwheels](https://www.piwheels.org/simple) for 32-bit ARM.

## Security

Report vulnerabilities privately, as [SECURITY.md](SECURITY.md) describes: GitHub private vulnerability reporting, or [jacobus@kadima-tech.com](mailto:jacobus@kadima-tech.com). Do not open a public GitHub issue, and do not put exploit details in a pull request.

Take extra care with health data and Google credentials:

- The database (`./data/bathroom-hub.db`, or `/var/lib/bathroom-hub/bathroom-hub.db` on a Pi) stores profiles, weighs, the Google OAuth client secret, and each person's refresh and access tokens.
- Scale pairing secrets live in `.philips-scale.json` and in the data directory.
- The web app has no login and listens on all interfaces by default. It is meant for a home network.

Do not commit databases, tokens, client secrets, pairing files, or `readings.jsonl`. Do not log them. Tests and examples use synthetic profiles and captured protocol bytes, not a real household. Leave `data/`, `.philips-scale.json`, and `.philips-scale-*.json` gitignored.

## License

This project is under MIT No Attribution (MIT-0), copyright 2026 Kadima Tech. See [LICENSE](LICENSE); each library and app carries the same file. Sending a contribution means you license it under those terms.

The Instrument Sans files in `apps/bathroom-hub/src/bathroom_hub/static/fonts/` stay under the SIL Open Font License (`OFL.txt` beside them). That license is separate from MIT-0.
