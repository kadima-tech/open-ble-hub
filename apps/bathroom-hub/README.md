# Bathroom Hub

A self-hosted hub for the devices in the bathroom. It listens for them around the clock, works out which person a reading belongs to, and keeps that data on the hub. A small web app on your network handles onboarding, people, charts and pairing.

Devices: the Philips DL8780 scale, through [openble-lifesense](../../packages/openble-lifesense). The Sonicare toothbrush is in the device catalogue as planned.

## What it does

- **Weigh first, decide later.** The scale doesn't know who stepped on. The hub matches each weigh to the person whose recent weight is closest, and asks "Who was this?" on the dashboard when it can't tell.
- **Body composition from published science.** Body fat uses the Jebb et al. (2000) equation for foot-to-foot scales (typical error ±4.8 % for men, ±3.3 % for women); lean mass is weight minus fat. The raw impedance is kept, so values can be recomputed.
- **Google Health, when a person connects.** Weight and body fat are written to that person's Google Health account, with retries. Leave the account unconnected and the readings stay on the hub.
- **Web app.** Onboarding, a dashboard with trends per person, a device hub for pairing, weigh history and settings. Server-rendered, works offline on the local network, light and dark mode. The design language is in [DESIGN.md](../../DESIGN.md).

## Run it on a computer

From the repository root:

```
make run                              # hub with Bluetooth, UI on http://localhost:8080, data in ./data
make ui                               # web app only, no Bluetooth
make run PORT=9000 DATA_DIR=/tmp/hub  # other port or data folder
```

## Install on a Raspberry Pi

From a copy of this repository on the Pi:

```
sudo ./apps/bathroom-hub/deploy/install.sh
```

The script installs packages, creates a `bathroom-hub` service user and the data directory `/var/lib/bathroom-hub`, and installs [hub-update](../../deploy). hub-update then builds a release of the checkout in `/opt/bathroom-hub/releases` and starts `bathroom-hub.service` on it. A Pi installed as Open BLE Hub or Philips BLE Hub is moved over: the old service is removed, and its data directory and database are kept. Then open `http://<pi-address>:8080` from a phone or laptop on the same network. Before installing:

- Enable the built-in Bluetooth. DietPi turns it off by default (`dietpi-config` → Advanced Options → Bluetooth).
- Set the timezone. The scale stamps weighs in local time.

The web app has no login. Keep it on your home network.

## Update or roll back

```
sudo hub-update update bathroom-hub     # newest bathroom-hub-v* release
sudo hub-update rollback bathroom-hub   # back to the release before
hub-update status bathroom-hub
```

An update is built next to the running hub, and the hub keeps running if the build fails. The data directory is then snapshotted and the hub is switched over. It has to answer on `/healthz` and stay up for 20 seconds, or the previous release and the snapshot are put back. An update cut short by a power cut is rolled back at the next boot. Running `install.sh` again from a newer checkout updates the same way. To update automatically every week, run `sudo systemctl enable --now hub-update@bathroom-hub.timer`. See [deploy/README.md](../../deploy/README.md) for how it works.

## First setup

The first visit starts onboarding:

1. **Your profile:** name, sex, birth date, height and today's weight. Add more people later from the profile switcher.
2. **Google Health (optional):** skip this and readings stay on the hub. To sync, the hub needs one Google Cloud OAuth client of type *Desktop app* with the Google Health API enabled; Settings lists the steps. Then each person connects their own account: sign in, then paste back the `http://localhost/?…` address the browser lands on. While the OAuth app is in *Testing*, Google ends sign-ins after 7 days. Disconnecting a person stops further uploads; readings already sent to Google stay there.
3. **Pair the scale:** press Start pairing, then hold the scale's unit button for 3 seconds. This replaces any phone app's pairing.

## License

[MIT License](LICENSE), copyright 2026 Kadima Tech. The Instrument Sans font in `src/bathroom_hub/static/fonts/` remains under the SIL Open Font License (`OFL.txt` next to the font).
