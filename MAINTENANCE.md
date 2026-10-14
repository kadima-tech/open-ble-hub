# Maintenance

## Maintenance Log

- **2026-10-13:** Added `aiohttp` to `requirements.txt` for the Scale Hub web UI and Google Health client. Added `.philips-scale-*.json` and `data/` to `.gitignore`, because both hold scale pairing secrets or the hub database.
- **2026-10-14:** Added a `Makefile` that creates `.venv`, reinstalls `requirements.txt` when it changes (stamp file `.venv/.installed`), and runs the hub, tests and `philips_ble` commands inside it. After a dependency bump, `make venv` picks it up; `make clean` resets the environment.
- **2026-10-14:** Renamed Scale Hub to Philips BLE Hub: package `scale_hub` → `ble_hub`, systemd unit, service user, `/opt` and `/var/lib` paths `scale-hub` → `philips-ble-hub`, database file `philips-ble-hub.db`. No Pi had been installed yet, so nothing needed migrating.

## Recurring Patterns

None yet.
