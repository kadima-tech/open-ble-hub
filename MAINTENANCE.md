# Maintenance

## Maintenance Log

- **2026-10-14:** Added maintainer guardrails: GitHub Actions CI (ruff 0.17.0 and `make test` on Python 3.11–3.14, Linux and macOS), `ruff.toml`, `SECURITY.md`, Dependabot for pip and GitHub Actions, `CODEOWNERS`, and a pull request template. Ruff fixes are formatting, import order, and equivalent cleanups (`datetime.UTC`, `TimeoutError`, an unused local). Bluetooth `except Exception` handlers are left as they are.
- **2026-10-13:** Added `aiohttp` to `requirements.txt` for the Scale Hub web UI and Google Health client. Added `.philips-scale-*.json` and `data/` to `.gitignore`, because both hold scale pairing secrets or the hub database.
- **2026-10-14:** Added a `Makefile` that creates `.venv`, reinstalls `requirements.txt` when it changes (stamp file `.venv/.installed`), and runs the hub, tests and `philips_ble` commands inside it. After a dependency bump, `make venv` picks it up; `make clean` resets the environment.
- **2026-10-14:** Renamed Scale Hub to Philips BLE Hub: package `scale_hub` → `ble_hub`, systemd unit, service user, `/opt` and `/var/lib` paths `scale-hub` → `philips-ble-hub`, database file `philips-ble-hub.db`. No Pi had been installed yet, so nothing needed migrating.
- **2026-10-14:** Vendored the Instrument Sans variable font (`ble_hub/static/fonts/`, from `@fontsource-variable/instrument-sans@5.2.8`, OFL licence beside it) for the Mineral UI, so the Pi needs no internet for fonts. To update it, download the same `files/instrument-sans-latin-wght-normal.woff2` and `LICENSE` from a newer version.
- **2026-10-14:** Renamed the project to Open BLE Hub for the public repository `kadima-tech/open-ble-hub`: UI name, systemd unit `open-ble-hub.service`, service user and `/opt`, `/var/lib` paths, database file `open-ble-hub.db`. Python packages `ble_hub` and `philips_ble` keep their names.
- **2026-10-15:** Split the repository into libraries and front-ends (copyright 2026 Kadima Tech; the license stays MIT and the vendored font stays OFL). `philips_ble` became `packages/openble-lifesense` (`openble.lifesense`: `scale_packets` → `packets`, `scale_link` → `link`) and `packages/openble-sonicare` (`openble.sonicare`), with the protocol manuals moved beside them; both are dependency-free and publishable. The diagnostic CLI became `apps/ble-probe` (`python -m ble_probe`). Open BLE Hub the app became Bathroom Hub (Open BLE Hub stays the project name): `ble_hub` → `apps/bathroom-hub` (`bathroom_hub`), systemd unit, service user, `/opt` and `/var/lib` paths `open-ble-hub` → `bathroom-hub`, database → `bathroom-hub.db`. `install.sh` moves a Pi installed as `open-ble-hub` or `philips-ble-hub`, and the hub renames either old database on start. `requirements.txt` → `requirements-dev.txt` (editable installs); runtime dependencies moved into each app's `pyproject.toml`, and Dependabot now watches those. Ruff per-file ignores and first-party names, and the CI pip cache key, follow the new paths. Added `.github/workflows/publish.yml` to publish a library from a `<distribution>-v<version>` tag.
- **2026-10-16:** Dropped macOS from the CI test matrix; tests now run on Linux only (Python 3.11–3.14). macOS runners cost more and the Bluetooth tests use fakes, so they caught nothing Linux did not. Both CI jobs now use `runs-on: ${{ vars.CI_RUNNER || 'ubuntu-latest' }}`, like `publish.yml`.

## Recurring Patterns

### Renaming the hub or a package

Seen three times: Scale Hub → Philips BLE Hub (2026-10-14), → Open BLE Hub (2026-10-14), → Bathroom Hub (2026-10-15). A rename touches more than the Python package:

- package directory and every import, including `mock.patch` target strings in tests and the module names passed to the `bluetooth(...)` helper in `tests/test_bluetooth.py`;
- `ruff.toml` per-file ignores and `known-first-party`;
- the systemd unit file name and its `Description`, `User`, `Group`, `WorkingDirectory`, `ExecStart` and `ReadWritePaths`;
- `install.sh`: `APP_DIR`, `DATA_DIR`, `SERVICE_USER`, unit name, and the `OLD_NAMES` migration list for Pis already installed under an earlier name;
- the database file name, with the old name added to `LEGACY_DB_NAMES` in `bathroom_hub/__main__.py` so existing data directories are renamed on start;
- UI brand and page titles, the CSS and JS header comments, `DESIGN.md`, READMEs, `CONTRIBUTING.md`, `SECURITY.md` and Makefile help text;
- strings sent to other services, such as the Google Health data point `notes`.

Search for the old name in every form (`old_name`, `old-name`, `Old Name`) before committing. Once no Pi runs an old name, drop it from `OLD_NAMES` and `LEGACY_DB_NAMES`.
