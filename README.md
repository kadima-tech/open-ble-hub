# Open BLE Hub

A self-hosted hub for the Bluetooth devices around your home. It listens for them around the clock, works out which person a reading belongs to, and keeps that data on the hub. A small web app on your network handles onboarding, people, charts and pairing.

## Mission

Open-source the communication protocols for the Bluetooth devices around your home, both old and new, so you are not dependent on the manufacturer. Keep the readings on hardware you run instead of submitting them to the maker's cloud. Syncing to Google Health is opt-in, per person. Apple Health is a later goal and is not in the hub today.

- **Local-first.** Profiles and readings live in the hub's database. A reading is uploaded only after that person connects a cloud account.
- **Manufacturer-independent.** The hub talks to the device itself. It does not need the maker's app or account.
- **Open protocols.** Handshakes, packet layouts and clients live in this repository, so the next device can be added in the open.
- **Cloud sync is opt-in.** Each person can connect their own Google account from onboarding or their profile. Until they do, their readings stay on the hub. Connecting later also sends readings already stored here. Disconnecting stops further uploads.

Open BLE Hub is an independent project. It is not affiliated with or endorsed by Philips or any other device maker. It is not a medical device.

## Supported devices

| Device | Model | What the hub reads | Status |
| --- | --- | --- | --- |
| Philips body analysis scale | DL8780 | Weight, impedance → body fat and lean mass (calculated per person) | Supported |

That is the whole list for now. **We welcome support for more devices**: see [Adding a device](#adding-a-device).

## Platforms

Runs on **macOS** and **Linux**, including a Raspberry Pi 3 with DietPi or Raspberry Pi OS. It needs Python 3.11 or newer and a Bluetooth LE adapter (built in on Macs and the Pi 3). Windows is not supported.

## What it does

- **Weigh first, decide later.** The scale doesn't know who stepped on. The hub matches each weigh to the person whose recent weight is closest, and asks "Who was this?" on the dashboard when it can't tell.
- **Body composition from published science.** Body fat uses the Jebb et al. (2000) equation for foot-to-foot scales (typical error ±4.8 % for men, ±3.3 % for women); lean mass is weight minus fat. The raw impedance is kept, so values can be recomputed.
- **Google Health, when a person connects.** Weight and body fat are written to that person's Google Health account, with retries. Leave the account unconnected and the readings stay on the hub.
- **Web app.** Onboarding, a dashboard with trends per person, a device hub for pairing, weigh history and settings. Server-rendered, works offline on the local network, light and dark mode.

## Quick start (Mac or Linux)

```
git clone https://github.com/kadima-tech/open-ble-hub.git
cd open-ble-hub
make run
```

`make run` creates a virtualenv in `.venv`, installs the requirements, and starts the hub with Bluetooth. Open <http://localhost:8080> and follow the onboarding. Data lives in `./data`.

```
make ui                               # web app only, no Bluetooth
make test                             # unit tests, no device needed
make run PORT=9000 DATA_DIR=/tmp/hub  # other port or data folder
make help                             # every target
```

On macOS, allow Bluetooth for your terminal in System Settings → Privacy & Security → Bluetooth.

## Install on a Raspberry Pi

From a copy of this repository on the Pi:

```
sudo ./deploy/install.sh
```

The script installs packages, creates an `open-ble-hub` service user, puts the app in `/opt/open-ble-hub` and its data in `/var/lib/open-ble-hub`, and starts `open-ble-hub.service`. Then open `http://<pi-address>:8080` from a phone or laptop on the same network. Before installing:

- Enable the built-in Bluetooth. DietPi turns it off by default (`dietpi-config` → Advanced Options → Bluetooth).
- Set the timezone. The scale stamps weighs in local time.

The web app has no login. Keep it on your home network.

## First setup

The first visit starts onboarding:

1. **Your profile:** name, sex, birth date, height and today's weight. Add more people later from the profile switcher.
2. **Google Health (optional):** skip this and readings stay on the hub. To sync, the hub needs one Google Cloud OAuth client of type *Desktop app* with the Google Health API enabled; Settings lists the steps. Then each person connects their own account: sign in, then paste back the `http://localhost/?…` address the browser lands on. While the OAuth app is in *Testing*, Google ends sign-ins after 7 days. Disconnecting a person stops further uploads; readings already sent to Google stay there.
3. **Pair the scale:** press Start pairing, then hold the scale's unit button for 3 seconds. This replaces any phone app's pairing.

## Adding a device

Support for more devices is very welcome, from any brand. A device usually needs:

1. **Protocol notes** in `docs/`: services, characteristics, the handshake and the packet layouts. An Android HCI snoop log of the maker's app talking to the device is the fastest way to get these right; static reading of an app alone missed steps for the scale.
2. **A client** that speaks the protocol (see `philips_ble/` for the scale), with tests built from captured packets.
3. **Hub support**: a listener like `ble_hub/listener.py`, an entry in the catalogue in `ble_hub/devices.py`, and any new data types in `ble_hub/google_health.py`.

Not ready to write code? Open an issue with the device model, what it measures and, if you can, a capture of it talking to its app.

## Project layout

| Path | What it is |
| --- | --- |
| `ble_hub/` | The hub: Bluetooth listener, assignment, body composition, Google Health client, SQLite storage, web app |
| `philips_ble/` | Low-level Bluetooth clients and packet parsers for Philips devices |
| `docs/` | Protocol notes for the DL8780 scale and the Sonicare toothbrush, and the scale's connection log |
| `deploy/` | Raspberry Pi install script and systemd unit |
| `tests/` | Unit tests, built from captured packets |
| `DESIGN.md` | The web app's design language |
| `CONTRIBUTING.md` | Development setup, tests and pull requests |
| `SECURITY.md` | How to report a vulnerability |
| `LICENSE` | MIT License |

## Low-level client

`python -m philips_ble` talks to devices directly, without the hub. Useful when working on a protocol.

```
make venv && source .venv/bin/activate
python -m philips_ble scan     # list nearby Philips devices
python -m philips_ble scale    # connect to the scale once
python -m philips_ble watch    # keep listening for the scale
python -m philips_ble brush    # read the Sonicare toothbrush (unsupported, hex output)
```

`scale` and `watch` answer the Lifesense A3 exchange. A paired scale sends a random (`0xA1`) and expects the password from the original pair; a scale in pairing mode (hold the unit button for 3 seconds) sends `0xA0`. The client stores the password and broadcast id in `.philips-scale.json`. On each connection it answers with that password, writes the broadcast id and the clock, waits for the scale's `0xC0`, then writes the profile and `0x22`. The scale then sends the weigh on `8A24` and `8A22`. Details and what worked on a live scale are in [docs/dl8780-connection-handoff.md](docs/dl8780-connection-handoff.md).

Options: `--address` picks a device when several are in range (on macOS this is a UUID from `scan`); `--out readings.jsonl` logs every read and notification; `--seconds` sets how long to listen; `--user-number`, `--user-name`, `--age`, `--height-cm` and `--sex` fill the scale's user slot on a new pair. `make scan`, `make scale` and `make watch` run the same commands with options in `ARGS`, for example `make watch ARGS="--out readings.jsonl"`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests and pull requests. Report security issues privately, as [SECURITY.md](SECURITY.md) describes.

## License

Open BLE Hub is released under the [MIT License](LICENSE), copyright 2026 Kadima Tech. The Instrument Sans font in `ble_hub/static/fonts/` remains under the SIL Open Font License (`OFL.txt` next to the font).
