# hub-update

Installs, updates and rolls back the hub apps in `apps/` on a Raspberry Pi or another Linux host with systemd. One tool for every hub. It is standard-library Python and is installed outside every release as `/usr/local/sbin/hub-update`, so it still works when a release is broken.

```
sudo hub-update update bathroom-hub              # newest bathroom-hub-v* release tag
sudo hub-update update bathroom-hub --ref main   # a branch, tag or commit
sudo hub-update update bathroom-hub --source .   # a local checkout (what install.sh does)
sudo hub-update rollback bathroom-hub            # back to the previous release
sudo hub-update rollback bathroom-hub --restore-data
sudo hub-update recover bathroom-hub             # finish rolling back an update that was cut short
hub-update status bathroom-hub                   # releases, service, history (--check: newest tag)
```

A hub's own `deploy/install.sh` sets up the machine once (packages, service user, data directory), installs `hub-update`, and runs `hub-update update <app> --source <checkout>`.

## How an update runs

1. **Build beside the running release.** Fetch the repository into a bare clone (`/opt/<app>/repo.git`), export `apps/<app>`, `packages/` and `deploy/` at that commit into `/opt/<app>/releases/<id>/src`, and create `releases/<id>/venv` with the app and the libraries it depends on from `packages/`. The id is `<version>-<commit>`. `release.json` is written last and marks a build as complete. A failed fetch, a failed pip install or a full disk stops here. The hub keeps running and the half-built directory is removed.
2. **Stop and snapshot.** Stop the service and copy its data directory to `/var/backups/<app>/<time>-<release>`.
3. **Switch.** Point `/opt/<app>/current` at the new release with one rename, install that release's systemd unit, and start the service.
4. **Check.** `health_url` has to answer 200 within `health_timeout` seconds. Then the service has to stay up for `settle` seconds without systemd restarting it.
5. **Keep it, or put everything back.** If the check fails, the service is stopped, the data snapshot is restored, `current` points back at the previous release, and the previous unit is reinstalled and started. The data the failed release wrote is kept in `/var/backups/<app>/<time>-replaced`. The failed release is skipped by later `update` runs that name no ref. Pass `--force` to retry it.

On success the three newest releases and data snapshots are kept, and `hub-update` installs itself and its units from the new release.

Every step is recorded in `/opt/<app>/state.json` before it runs. If the process dies part-way, for example in a power cut, the next `hub-update` command rolls the switch back first. `hub-recover@<app>.service` does the same at boot, before the app starts. `hub-update` enables it for each app it installs.

| What fails | What runs afterwards |
| --- | --- |
| Fetch, pip install, disk space | The release that was already running. Nothing was stopped. |
| New release does not answer, crashes or restarts | The previous release, with the data from before the update. |
| Power cut or `kill` during the switch | The previous release after the next boot or `hub-update` run, with the data from before the update. |
| First install fails its check | Nothing to go back to. The error points at `journalctl -u <service>`. |

## Rolling back by hand

`hub-update rollback <app>` switches to the previous release, with the same snapshot, check and automatic undo as an update. The data stays as it is, because the hub may have recorded readings since the update. `--restore-data` also puts back the snapshot taken when the current release was installed, which discards everything written since. `--to <id>` picks any release that `status` lists as kept. The release you leave is skipped by later updates that name no ref, so the timer does not reinstall it.

## Automatic updates

Off by default. To update every Sunday around 04:00:

```
sudo systemctl enable --now hub-update@bathroom-hub.timer
```

`journalctl -u hub-update@bathroom-hub` shows what each run did. A run that rolled back leaves the unit failed.

## Releasing a hub app

Bump `version` in `apps/<app>/pyproject.toml`, merge, then push a tag `<app>-v<version>`:

```
git tag bathroom-hub-v0.2.0
git push origin bathroom-hub-v0.2.0
```

`hub-update update <app>` installs the newest such tag. A tag that does not match the version in `pyproject.toml` is refused. App tags do not trigger `publish.yml`, which only publishes `openble-*` tags.

## Making a hub app updatable

An app under `apps/<app>/` needs:

- `deploy/hub.toml`, read from the release being installed:

  ```toml
  service = "<app>.service"           # unit file next to it
  data_dir = "/var/lib/<app>"         # snapshotted before every switch
  health_url = "http://127.0.0.1:8080/healthz"
  health_timeout = 90                 # seconds to answer after starting
  settle = 20                         # seconds it must then stay up
  ```

- `deploy/<app>.service` running `/opt/<app>/current/venv/bin/<app>`, with `ReadWritePaths=` set to `data_dir`.
- A `health_url` endpoint that answers 200 once the app has opened its data and is serving. The Bathroom Hub's is `/healthz`.
- Its libraries listed in `dependencies` under their distribution names (`openble-lifesense`). Any that exist in `packages/` are installed from the same commit.

`deploy/tests/test_hub_update.py` checks the manifest and unit of every app that has a `deploy/hub.toml`.

## Layout on the hub

| Path | What it is |
| --- | --- |
| `/usr/local/sbin/hub-update` | This tool (`deploy/hub_update.py`) |
| `/etc/systemd/system/hub-update@.service`, `.timer`, `hub-recover@.service` | Update on a timer, recover at boot |
| `/opt/<app>/current` | Symlink to the running release |
| `/opt/<app>/releases/<id>/` | `src/`, `venv/` and `release.json` of each kept release |
| `/opt/<app>/repo.git` | Bare clone the releases are exported from |
| `/opt/<app>/state.json` | Previous release, unfinished switch, skipped releases, history |
| `/var/backups/<app>/` | Data snapshots, mode 700. They hold the same secrets as the database. |
