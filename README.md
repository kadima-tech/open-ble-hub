# Open BLE Hub

Open Bluetooth protocols for the devices around your home, as small libraries anyone can build on, and self-hosted hubs that put a selection of them to work. A hub listens for its devices around the clock, works out which person a reading belongs to, and keeps that data on the hub.

## Mission

We believe the devices in your home should work for you, not for their manufacturer. Your data belongs to you, on your own hardware, for as long as the device keeps working.

We believe in:

- **Your data staying on your own hardware by default.** Profiles and readings live in the hub's database. A reading is uploaded only after that person connects a cloud account.
- **Open protocols, so no device is locked to one company's app or cloud.** The hub talks to the device itself. Handshakes, packet layouts and clients live in this repository, and the libraries are published so anyone can build on them.
- **Cloud sync that is opt-in, per person, and easy to turn off.** Today that is Google Health. Each person connects their own account from onboarding or their profile. Until they do, readings stay on the hub. Connecting later also sends readings already stored here. Disconnecting that account stops further uploads. While the account stays linked, uploads continue; there is no separate pause switch. Apple Health is not in the hub today.
- **Keeping old devices out of landfill by keeping them useful.** Open notes for devices old and new are how a device stays usable after its maker moves on.

Open BLE Hub is an independent project. It is not affiliated with or endorsed by Philips, Lifesense, Lovense or any other device maker; their names identify the devices this interoperates with. It is not a medical device.

## Libraries

One library per device protocol, published to PyPI under the `openble` namespace. Each is pure Python 3.11+ with no dependencies and no Bluetooth stack, so it works with bleak, a test double or anything else. Each ships with its protocol manual: what the bytes are, which class each fact came from, and which questions are still open.

| Package | Devices | Import | Manual |
| --- | --- | --- | --- |
| [openble-lifesense](packages/openble-lifesense) | Lifesense A2/A3 scales, including the Philips DL8780 | `openble.lifesense` | [scale](packages/openble-lifesense/docs/lifesense-scale-protocol.md), [DL8780 live](packages/openble-lifesense/docs/dl8780-connection-handoff.md) |
| [openble-sonicare](packages/openble-sonicare) | Philips Sonicare toothbrushes | `openble.sonicare` | [toothbrush](packages/openble-sonicare/docs/sonicare-toothbrush-protocol.md) |
| [openble-lovense](packages/openble-lovense) | Lovense toys | `openble.lovense` | [toys](packages/openble-lovense/docs/lovense-ble-protocol.md) |

```
pip install openble-lifesense
```

Protocol manuals for devices that have no library yet are in [`docs/`](docs): [Lovense toys](docs/lovense-ble-protocol.md).

## Front-ends

Apps in this repository, each using a selection of the libraries. They are not published.

| App | What it is | Libraries |
| --- | --- | --- |
| [Bathroom Hub](apps/bathroom-hub) | Raspberry Pi hub with a web app: onboarding, people, charts, pairing, and Google Health sync | lifesense |
| [BLE probe](apps/ble-probe) | Diagnostic CLI: scan, connect, read and subscribe, without a hub | lifesense, sonicare |

## Supported devices

| Device | Model | Library | What is read | Status |
| --- | --- | --- | --- | --- |
| Philips body analysis scale | DL8780 | openble-lifesense | Weight, impedance → body fat and lean mass (calculated per person in the Bathroom Hub) | Supported |
| Philips Sonicare toothbrush | HX9393 | openble-sonicare | GATT map and advertisement matching; most byte layouts still open | Planned |

**We welcome support for more devices**: see [Adding a device](#adding-a-device).

## Platforms

Runs on **macOS** and **Linux**, including a Raspberry Pi 3 with DietPi or Raspberry Pi OS. It needs Python 3.11 or newer and a Bluetooth LE adapter (built in on Macs and the Pi 3). Windows is not supported.

## Quick start (Mac or Linux)

```
git clone https://github.com/kadima-tech/open-ble-hub.git
cd open-ble-hub
make run
```

`make run` creates a virtualenv in `.venv`, installs every package and app editable, and starts the Bathroom Hub with Bluetooth. Open <http://localhost:8080> and follow the onboarding. Data lives in `./data`. To install on a Raspberry Pi, see [apps/bathroom-hub](apps/bathroom-hub#install-on-a-raspberry-pi).

```
make ui                               # web app only, no Bluetooth
make test                             # unit tests of every package and app, no device needed
make scan                             # BLE probe: list nearby supported devices
make build                            # sdists and wheels of the libraries in dist/
make run PORT=9000 DATA_DIR=/tmp/hub  # other port or data folder
make help                             # every target
```

On macOS, allow Bluetooth for your terminal in System Settings → Privacy & Security → Bluetooth.

## Adding a device

Support for more devices is very welcome, from any brand. A device usually needs:

1. **A library** in `packages/openble-<protocol>/`: the code in `src/openble/<protocol>/` (no `__init__.py` in `src/openble/`, which is a namespace shared by every library), tests built from captured packets in `tests/`, protocol notes in `docs/` (services, characteristics, the handshake and the packet layouts), and a `README.md`, `LICENSE` and `pyproject.toml` modelled on the existing ones. Add it to `requirements-dev.txt`. An Android HCI snoop log of the maker's app talking to the device is the fastest way to get the notes right; static reading of an app alone missed steps for the scale.
2. **A front-end** that uses it: a listener and catalogue entry in an existing hub (for the Bathroom Hub, `listener.py`, `devices.py`, and `google_health.py` for new data types), or a new app under `apps/` when the device does not fit an existing hub.

Not ready to write code? Open an issue with the device model, what it measures and, if you can, a capture of it talking to its app.

## Releasing a library

Bump `version` in the package's `pyproject.toml`, merge, then push a tag `<distribution>-v<version>`:

```
git tag openble-lifesense-v0.1.0
git push origin openble-lifesense-v0.1.0
```

[`.github/workflows/publish.yml`](.github/workflows/publish.yml) checks the version, tests the wheel on Python 3.11 and 3.14, and publishes it with PyPI trusted publishing. Each PyPI project needs a trusted publisher for this repository, workflow `publish.yml` and environment `pypi`.

## Project layout

| Path | What it is |
| --- | --- |
| `packages/` | The libraries, one per device protocol, each with its tests and protocol notes |
| `apps/bathroom-hub/` | The Bathroom Hub: listener, assignment, body composition, Google Health client, SQLite storage, web app, and the Raspberry Pi installer in `deploy/` |
| `apps/ble-probe/` | The diagnostic CLI |
| `docs/` | Protocol manuals for devices that have no library yet |
| `tests/` | Bluetooth tests that drive both apps against bleak's real API, with no radio |
| `DESIGN.md` | The web app's design language |
| `CONTRIBUTING.md` | Development setup, tests and pull requests |
| `SECURITY.md` | How to report a vulnerability |
| `LICENSE` | MIT License |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests and pull requests. Report security issues privately, as [SECURITY.md](SECURITY.md) describes.

## License

Everything here is released under the [MIT License](LICENSE), copyright 2026 Kadima Tech. Each package and app carries its own copy of the license. The Instrument Sans font in `apps/bathroom-hub/src/bathroom_hub/static/fonts/` remains under the SIL Open Font License (`OFL.txt` next to the font).
