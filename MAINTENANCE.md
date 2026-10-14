# Maintenance

## Maintenance Log

- **2026-10-14:** Added maintainer guardrails: GitHub Actions CI (ruff 0.17.0 and `make test` on Python 3.11–3.14, Linux and macOS), `ruff.toml`, `SECURITY.md`, Dependabot for pip and GitHub Actions, `CODEOWNERS`, and a pull request template. Ruff fixes are formatting, import order, and equivalent cleanups (`datetime.UTC`, `TimeoutError`, an unused local). Bluetooth `except Exception` handlers are left as they are.
- **2026-10-13:** Added `aiohttp` to `requirements.txt` for the Scale Hub web UI and Google Health client. Added `.philips-scale-*.json` and `data/` to `.gitignore`, because both hold scale pairing secrets or the hub database.
- **2026-10-14:** Added a `Makefile` that creates `.venv`, reinstalls `requirements.txt` when it changes (stamp file `.venv/.installed`), and runs the hub, tests and `philips_ble` commands inside it. After a dependency bump, `make venv` picks it up; `make clean` resets the environment.
- **2026-10-14:** Renamed Scale Hub to Philips BLE Hub: package `scale_hub` → `ble_hub`, systemd unit, service user, `/opt` and `/var/lib` paths `scale-hub` → `philips-ble-hub`, database file `philips-ble-hub.db`. No Pi had been installed yet, so nothing needed migrating.
- **2026-10-14:** Vendored the Instrument Sans variable font (`ble_hub/static/fonts/`, from `@fontsource-variable/instrument-sans@5.2.8`, OFL licence beside it) for the Mineral UI, so the Pi needs no internet for fonts. To update it, download the same `files/instrument-sans-latin-wght-normal.woff2` and `LICENSE` from a newer version.
- **2026-10-14:** Renamed the project to Open BLE Hub for the public repository `kadima-tech/open-ble-hub`: UI name, systemd unit `open-ble-hub.service`, service user and `/opt`, `/var/lib` paths, database file `open-ble-hub.db`. Python packages `ble_hub` and `philips_ble` keep their names.

## Recurring Patterns

None yet.
