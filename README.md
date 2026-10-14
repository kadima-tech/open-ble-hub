# Philips BLE kit

Notes from a static read of two Philips Android apps, and a small Mac client that talks to the devices those notes describe.

- Scale: [docs/lifesense-scale-protocol.md](docs/lifesense-scale-protocol.md)
- This scale, live: [docs/dl8780-connection-handoff.md](docs/dl8780-connection-handoff.md)
- Toothbrush: [docs/sonicare-toothbrush-protocol.md](docs/sonicare-toothbrush-protocol.md)

Each manual records what the bytecode does, which class each fact came from, and which questions are still open. No device was connected while the manuals were written.

## Philips BLE Hub (Raspberry Pi)

`ble_hub` turns the client into an always-on bridge. A Raspberry Pi 3 near the scale listens for weighs, works out who stepped on, calculates body fat, and sends weight and body fat to that person's Google Health account. A small web UI on the Pi handles profiles, Google linking and pairing.

Install on DietPi or Raspberry Pi OS, from a copy of this repository on the Pi:

```
sudo ./deploy/install.sh
```

The script installs packages, creates a `philips-ble-hub` service user, puts the app in `/opt/philips-ble-hub` and its data in `/var/lib/philips-ble-hub`, and starts `philips-ble-hub.service`. Then open `http://<pi-address>:8080`. Before installing:

- Enable the built-in Bluetooth. DietPi turns it off by default (`dietpi-config` > Advanced Options > Bluetooth).
- Set the timezone. The scale stamps weighs in local time.

Setup in the UI:

1. **Profiles:** one per person, with sex, birth date, height and current weight. The current weight is used to recognise their first weighs.
2. **Settings:** a Google Cloud OAuth client of type *Desktop app*, with the Google Health API enabled. The steps are on the page. While the OAuth app is in *Testing*, Google ends sign-ins after 7 days.
3. **Link Google account** on each profile. Sign in, then paste back the `http://localhost/?…` address the browser lands on.
4. **Pair scale:** press the button, then hold the scale's unit button for 3 s. This replaces any phone app's pairing.

Each weigh goes to the person whose recent weight is closest, when that is within the tolerance in Settings (3 kg by default) and clearly closer than anyone else. Other weighs wait on the overview for a manual choice. Body fat uses the Jebb et al. 2000 foot-to-foot equation; lean mass is weight minus fat. The raw impedance is kept, so values can be recomputed later.

Run it on a computer with `make`. The first run creates `.venv` and installs `requirements.txt`, and it reinstalls whenever that file changes. `make help` lists every target.

```
make run              # hub with Bluetooth, UI on http://localhost:8080, data in ./data
make ui               # UI only, no Bluetooth
make test
make run PORT=9000 DATA_DIR=/tmp/hub
```

## Local client

`python -m philips_ble` scans, connects, reads the characteristics the manuals name, and subscribes to their notifications. Scale packets are parsed with the layouts in the scale manual, section 6. Toothbrush values whose byte layout is still open are printed as hex.

`scale` answers the Lifesense A3 exchange on characteristic 8A81. A scale that is already paired sends a random (`0xA1`) and expects the password from the original pair. This DL8780 has already sent that password; it is in `.philips-scale.json`. Hold the measurement-unit button for 3 seconds so the scale enters pairing and sends `0xA0` when a new pair is required. The client stores the password and broadcast id in `.philips-scale.json`. Later connections answer the random with that password, write the stored broadcast id and the clock, and wait for the scale's `0xC0` before writing the profile and `0x22`. The scale then keeps the link and sends the weigh on 8A24 and 8A22. Use `watch` for this. If another app pairs the scale, pair it again from the Mac. What has and has not worked on the live scale is in [docs/dl8780-connection-handoff.md](docs/dl8780-connection-handoff.md). Sonicare SACP writes are still unsent. On macOS, Core Bluetooth shows its own pairing dialog when a read needs encryption.

```
make venv
source .venv/bin/activate
python -m philips_ble scan
python -m philips_ble brush
python -m philips_ble scale
python -m philips_ble watch
```

`watch` keeps a scan running and connects at the first advertisement from the scale. It subscribes to the scale indications, answers an A3 password with the pairing queue or a random with the XOR and the clock, and leaves the link up until the scale drops it or the link has been quiet for `--idle-seconds` (default 180). It then scans again. Ctrl-C stops it. The Bluetooth symbol on the scale lights when the scale accepts that connection, and it flashes while a measurement is sent.

On macOS the device address printed by `scan` is a UUID. Pass it back with `--address` when more than one match is in range. `--out readings.jsonl` appends a JSON line per read and notification. `--seconds` is how long to keep listening after subscribe (60s for the scale, 25s for the brush).

Allow Bluetooth for the terminal in System Settings → Privacy & Security → Bluetooth. For a first pair, hold the scale's unit button for 3 seconds, then step on barefoot when the client says the handshake was sent. `--password` accepts 8 hex digits copied from an earlier pair. `--user-number` and `--user-name` are the slot written during that new pair (defaults `1` and `User`). `--age`, `--height-cm`, and `--sex` fill the Lifesense user-info frame (age 18..100, height 100..204 cm, sex `male` or `female`). The scale stores that height in metres after dividing the centimetres by 100. Leave all three off and the client sends the empty 15-byte frame.

`make scan`, `make scale` and `make watch` run the same commands inside `.venv`; pass options with `ARGS`, for example `make watch ARGS="--out readings.jsonl"`.

Parser checks do not need a radio or a device:

```
make test
```
