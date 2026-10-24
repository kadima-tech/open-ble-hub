#!/usr/bin/env python3
"""Install, update and roll back a hub app on a Raspberry Pi or another Linux host.

Each release is built in its own directory beside the one that is running, so
a failed download or pip install never touches the hub::

    /opt/<app>/releases/<id>/src    apps/<app>, packages/ and deploy/ at that commit
    /opt/<app>/releases/<id>/venv   the app and its libraries from packages/
    /opt/<app>/current -> releases/<id>
    /opt/<app>/state.json           previous release, unfinished switch, skipped releases
    /var/backups/<app>/             data directory snapshots, one per switch

A switch stops the service, snapshots the data directory, points ``current``
at the new release, installs its systemd unit, starts it and waits for it to
stay healthy (``apps/<app>/deploy/hub.toml`` says how). If it does not, the
previous release and the snapshot are put back. A switch cut short, for
example by a power cut, is rolled back by ``recover``, which
``hub-recover@<app>.service`` runs at boot before the app starts.

Standard library only, and installed outside every release as
/usr/local/sbin/hub-update, so it works whatever state a release is in::

    sudo hub-update update bathroom-hub              # newest bathroom-hub-v* tag
    sudo hub-update update bathroom-hub --ref main   # a branch, tag or commit
    sudo hub-update update bathroom-hub --source .   # a local checkout
    sudo hub-update rollback bathroom-hub            # back to the previous release
    hub-update status bathroom-hub
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_REPO = "https://github.com/kadima-tech/openble.git"
# Paths of the repository every release needs, besides apps/<app>.
SOURCE_PATHS = ("packages", "deploy")
COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "__pycache__", "*.pyc", "*.egg-info", "build", "dist", "data"
)
# Units shipped in deploy/ and installed with the updater.
TOOL_UNITS = ("hub-update@.service", "hub-update@.timer", "hub-recover@.service")
KEEP_RELEASES = 3
KEEP_BACKUPS = 3
KEEP_HISTORY = 20
# A Pi 3 build of the Bathroom Hub venv takes about 60 MB; leave room for pip's cache.
MIN_FREE_MB = 300
APP_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


class UpdateError(Exception):
    """A step failed. The message says which, and what the hub is running now."""


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def install_file(src: Path, dest: Path, mode: int) -> None:
    """Copy src over dest in one rename, so a reader never sees half a file."""
    tmp = dest.with_name(f".{dest.name}.new")
    shutil.copyfile(src, tmp)
    tmp.chmod(mode)
    os.replace(tmp, dest)


def write_json(path: Path, value: dict) -> None:
    tmp = path.with_name(f".{path.name}.new")
    with open(tmp, "w") as fh:
        json.dump(value, fh, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def chown_tree(path: Path, uid: int, gid: int) -> None:
    os.lchown(path, uid, gid)
    for parent, dirs, files in os.walk(path):
        for name in dirs + files:
            os.lchown(os.path.join(parent, name), uid, gid)


@dataclass
class Manifest:
    """apps/<app>/deploy/hub.toml: how to run, check and back up one hub app."""

    service: str
    data_dir: Path
    health_url: str | None = None
    health_timeout: float = 90
    settle: float = 20

    @classmethod
    def load(cls, path: Path) -> Manifest:
        try:
            raw = tomllib.loads(path.read_text())
            manifest = cls(
                service=raw["service"],
                data_dir=Path(raw["data_dir"]),
                health_url=raw.get("health_url"),
                health_timeout=float(raw.get("health_timeout", cls.health_timeout)),
                settle=float(raw.get("settle", cls.settle)),
            )
        except FileNotFoundError:
            raise UpdateError(f"{path} is missing. A hub app needs deploy/hub.toml.")
        except (KeyError, ValueError) as exc:
            raise UpdateError(f"{path} is not a valid hub manifest: {exc}")
        if not manifest.service.endswith(".service"):
            raise UpdateError(f"{path}: service must name a .service unit.")
        if not manifest.data_dir.is_absolute():
            raise UpdateError(f"{path}: data_dir must be an absolute path.")
        return manifest


@dataclass
class Target:
    """A release to install, before it is built."""

    id: str
    version: str
    ref: str
    commit: str | None
    fill: Callable[[Path], None]


class System:
    """Everything outside the app directory: commands, systemd and HTTP. Tests replace it."""

    unit_dir = Path("/etc/systemd/system")
    tool_path = Path("/usr/local/sbin/hub-update")

    def run(self, cmd: list, cwd: Path | None = None) -> str:
        cmd = [str(part) for part in cmd]
        try:
            result = subprocess.run(
                cmd, check=False, cwd=cwd, text=True, capture_output=True
            )
        except FileNotFoundError:
            raise UpdateError(f"{cmd[0]} is not installed.")
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[-2000:]
            raise UpdateError(f"{' '.join(cmd[:4])} failed:\n{detail}")
        return result.stdout

    def systemctl(self, *args: str, check: bool = True) -> None:
        try:
            self.run(["systemctl", *args])
        except UpdateError:
            if check:
                raise

    def is_active(self, service: str) -> bool:
        return (
            subprocess.run(
                ["systemctl", "is-active", "--quiet", service], check=False
            ).returncode
            == 0
        )

    def restarts(self, service: str) -> int:
        out = self.run(
            ["systemctl", "show", "--property=NRestarts", "--value", service]
        )
        return int(out.strip() or 0)

    def http_ok(self, url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.status == 200
        except OSError:
            return False

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def clock(self) -> float:
        return time.monotonic()

    def install_unit(self, path: Path) -> None:
        install_file(path, self.unit_dir / path.name, 0o644)
        self.systemctl("daemon-reload")

    def install_tools(self, deploy: Path, app: str) -> None:
        """Install the updater and its units from a release, and arm recovery at boot."""
        script = deploy / "hub_update.py"
        compile(script.read_text(), str(script), "exec")
        install_file(script, self.tool_path, 0o755)
        for unit in TOOL_UNITS:
            install_file(deploy / unit, self.unit_dir / unit, 0o644)
        self.systemctl("daemon-reload")
        self.systemctl("enable", f"hub-recover@{app}.service")


class Updater:
    def __init__(
        self,
        app: str,
        root: Path = Path("/opt"),
        backup_root: Path = Path("/var/backups"),
        system: System | None = None,
        out: Callable[[str], None] = lambda line: print(f"==> {line}", flush=True),
    ):
        self.app = app
        self.home = root / app
        self.releases = self.home / "releases"
        self.current_link = self.home / "current"
        self.state_path = self.home / "state.json"
        self.backups = backup_root / app
        self.system = system or System()
        self.out = out

    # state ------------------------------------------------------------
    def load_state(self) -> dict:
        state = {
            "repo_url": DEFAULT_REPO,
            "previous": None,
            "backup": None,
            "pending": None,
            "skip": [],
            "history": [],
        }
        with contextlib.suppress(FileNotFoundError):
            state.update(json.loads(self.state_path.read_text()))
        return state

    def save_state(self, state: dict) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        write_json(self.state_path, state)

    def record(self, state: dict, event: str) -> None:
        history = state["history"]
        history.append(f"{datetime.now(UTC).isoformat(timespec='seconds')} {event}")
        del history[:-KEEP_HISTORY]

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        self.home.mkdir(parents=True, exist_ok=True)
        with open(self.home / ".lock", "w") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise UpdateError(f"Another hub-update is working on {self.app}.")
            yield

    # releases ---------------------------------------------------------
    def current(self) -> str | None:
        try:
            return Path(os.readlink(self.current_link)).name
        except OSError:
            return None

    def complete(self, release_id: str | None) -> bool:
        return (
            bool(release_id) and (self.releases / release_id / "release.json").exists()
        )

    def kept(self) -> list[str]:
        if not self.releases.is_dir():
            return []
        return sorted(d.name for d in self.releases.iterdir() if self.complete(d.name))

    def source_of(self, release_id: str) -> Path:
        return self.releases / release_id / "src"

    def manifest(self, release_id: str) -> Manifest:
        return Manifest.load(
            self.source_of(release_id) / "apps" / self.app / "deploy" / "hub.toml"
        )

    def read_version(self, pyproject: str) -> str:
        return tomllib.loads(pyproject)["project"]["version"]

    def local_packages(self, src: Path) -> list[Path]:
        """Libraries in packages/ that the app depends on, to install from the same commit."""
        pyproject = (src / "apps" / self.app / "pyproject.toml").read_text()
        found = []
        for requirement in tomllib.loads(pyproject)["project"].get("dependencies", []):
            name = re.match(r"[A-Za-z0-9._-]+", requirement).group(0)
            path = src / "packages" / name.lower().replace("_", "-")
            if (path / "pyproject.toml").exists():
                found.append(path)
        return found

    # sources ----------------------------------------------------------
    def fetch(self, repo_url: str) -> Path:
        """Bring a bare clone of the repository's branches and tags up to date."""
        mirror = self.home / "repo.git"
        git = ["git", "--git-dir", mirror]
        if not (mirror / "HEAD").exists():
            shutil.rmtree(mirror, ignore_errors=True)
            self.system.run(["git", "init", "--bare", "--quiet", mirror])
            self.system.run([*git, "remote", "add", "origin", repo_url])
            self.system.run(
                [*git, "config", "remote.origin.fetch", "+refs/heads/*:refs/heads/*"]
            )
        self.system.run([*git, "remote", "set-url", "origin", repo_url])
        self.out(f"Fetching {repo_url}")
        self.system.run(
            [*git, "fetch", "--prune", "--prune-tags", "--tags", "--quiet", "origin"]
        )
        return mirror

    def latest_tag(self, mirror: Path) -> str:
        out = self.system.run(
            [
                "git",
                "--git-dir",
                mirror,
                "tag",
                "--list",
                f"{self.app}-v*",
                "--sort=-v:refname",
            ]
        )
        tags = out.split()
        if not tags:
            raise UpdateError(
                f"The repository has no {self.app}-v* release tag yet. "
                "Pass --ref main to install the main branch."
            )
        return tags[0]

    def from_git(self, repo_url: str, ref: str | None) -> Target:
        mirror = self.fetch(repo_url)
        ref = ref or self.latest_tag(mirror)
        git = ["git", "--git-dir", mirror]
        try:
            commit = self.system.run(
                [*git, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]
            ).strip()
        except UpdateError:
            raise UpdateError(f"{ref} is not a branch, tag or commit of {repo_url}.")
        try:
            pyproject = self.system.run(
                [*git, "show", f"{commit}:apps/{self.app}/pyproject.toml"]
            )
        except UpdateError:
            raise UpdateError(f"{ref} has no apps/{self.app}.")
        version = self.read_version(pyproject)
        if ref.startswith(f"{self.app}-v") and ref != f"{self.app}-v{version}":
            raise UpdateError(
                f"Tag {ref} does not match version {version} in apps/{self.app}/pyproject.toml."
            )

        def fill(dest: Path) -> None:
            dest.mkdir(parents=True)
            archive = dest.parent / "src.tar"
            paths = [f"apps/{self.app}", *SOURCE_PATHS]
            self.system.run(
                [*git, "archive", "--format=tar", f"--output={archive}", commit, *paths]
            )
            with tarfile.open(archive) as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(dest, filter="data")
                else:
                    tar.extractall(dest)
            archive.unlink()

        return Target(f"{version}-{commit[:7]}", version, ref, commit, fill)

    def from_checkout(self, checkout: Path) -> Target:
        checkout = checkout.resolve()
        pyproject = checkout / "apps" / self.app / "pyproject.toml"
        if not pyproject.exists():
            raise UpdateError(f"{checkout} is not a checkout with apps/{self.app}.")
        version = self.read_version(pyproject.read_text())
        paths = [f"apps/{self.app}", *SOURCE_PATHS]
        # Root runs git in a checkout another user owns.
        git = ["git", "-c", f"safe.directory={checkout}", "-C", checkout]
        try:
            commit = self.system.run([*git, "rev-parse", "HEAD"]).strip()
            dirty = bool(
                self.system.run([*git, "status", "--porcelain", "--", *paths]).strip()
            )
        except UpdateError:
            commit, dirty = None, True
        if commit and not dirty:
            release_id = f"{version}-{commit[:7]}"
        elif commit:
            release_id = f"{version}-{commit[:7]}-dirty-{stamp()}"
        else:
            release_id = f"{version}-local-{stamp()}"

        def fill(dest: Path) -> None:
            for rel in paths:
                shutil.copytree(checkout / rel, dest / rel, ignore=COPY_IGNORE)

        return Target(release_id, version, str(checkout), commit, fill)

    # building ---------------------------------------------------------
    def prepare(self, target: Target) -> None:
        """Build a release beside the running one. On failure nothing else has changed."""
        release = self.releases / target.id
        if self.complete(target.id):
            self.out(f"Reusing the {target.id} build")
            return
        self.releases.mkdir(parents=True, exist_ok=True)
        free_mb = shutil.disk_usage(self.releases).free // 2**20
        if free_mb < MIN_FREE_MB:
            raise UpdateError(
                f"Only {free_mb} MB free under {self.releases}; {MIN_FREE_MB} MB needed."
            )
        # A directory without release.json is a build that was cut short.
        shutil.rmtree(release, ignore_errors=True)
        try:
            self.out(f"Building {target.id} from {target.ref}")
            target.fill(release / "src")
            self.manifest(target.id)
            self.build_venv(release)
            write_json(
                release / "release.json",
                {
                    "id": target.id,
                    "version": target.version,
                    "ref": target.ref,
                    "commit": target.commit,
                    "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
                },
            )
        except BaseException:
            shutil.rmtree(release, ignore_errors=True)
            raise

    def build_venv(self, release: Path) -> None:
        src = release / "src"
        venv = release / "venv"
        pip = [
            venv / "bin" / "python",
            "-m",
            "pip",
            "--disable-pip-version-check",
            "-q",
        ]
        extra = []
        if platform.machine() in ("armv6l", "armv7l"):
            extra = ["--extra-index-url", "https://www.piwheels.org/simple"]
        self.system.run([sys.executable, "-m", "venv", venv])
        self.system.run([*pip, "install", *extra, "--upgrade", "pip"])
        self.system.run(
            [
                *pip,
                "install",
                *extra,
                *self.local_packages(src),
                src / "apps" / self.app,
            ]
        )
        self.system.run([*pip, "check"])

    # switching --------------------------------------------------------
    def activate(self, release_id: str) -> None:
        """Point current at a release and install that release's systemd unit."""
        link = self.home / ".current.new"
        link.unlink(missing_ok=True)
        link.symlink_to(Path("releases") / release_id)
        os.replace(link, self.current_link)
        manifest = self.manifest(release_id)
        unit = (
            self.source_of(release_id) / "apps" / self.app / "deploy" / manifest.service
        )
        self.system.install_unit(unit)

    def backup_path(self, label: str) -> Path:
        """A new directory name in the backups, newest sorting last."""
        self.backups.mkdir(parents=True, exist_ok=True)
        self.backups.chmod(0o700)
        base = f"{stamp()}-{label}"
        path, n = self.backups / base, 1
        while path.exists():
            n += 1
            path = self.backups / f"{base}-{n}"
        return path

    def snapshot(self, manifest: Manifest, label: str) -> Path | None:
        if not manifest.data_dir.is_dir():
            return None
        dest = self.backup_path(label)
        partial = dest.with_name(f".{dest.name}.partial")
        shutil.rmtree(partial, ignore_errors=True)
        self.out(f"Snapshot of {manifest.data_dir} in {dest}")
        shutil.copytree(manifest.data_dir, partial, symlinks=True)
        os.replace(partial, dest)
        return dest

    def restore(self, manifest: Manifest, backup: Path) -> None:
        """Replace the data directory with a snapshot, keeping what it replaced."""
        data = manifest.data_dir
        owner = os.stat(data if data.exists() else backup)
        self.out(f"Restoring {data} from {backup}")
        if data.exists():
            shutil.move(data, self.backup_path("replaced"))
        shutil.copytree(backup, data, symlinks=True)
        chown_tree(data, owner.st_uid, owner.st_gid)

    def wait_healthy(self, manifest: Manifest) -> str | None:
        """None once the service answers and stays up, otherwise what went wrong."""
        system = self.system
        deadline = system.clock() + manifest.health_timeout
        # Restart=always brings a crashing hub back, so count restarts too.
        restarts = system.restarts(manifest.service)
        while not (
            system.is_active(manifest.service)
            and (not manifest.health_url or system.http_ok(manifest.health_url))
        ):
            if system.restarts(manifest.service) != restarts:
                return f"{manifest.service} crashed while starting"
            if system.clock() >= deadline:
                what = manifest.health_url or manifest.service
                return f"{what} did not answer within {manifest.health_timeout:g} s"
            system.sleep(2)
        system.sleep(manifest.settle)
        if (
            not system.is_active(manifest.service)
            or system.restarts(manifest.service) != restarts
        ):
            return (
                f"{manifest.service} stopped within {manifest.settle:g} s of starting"
            )
        if manifest.health_url and not system.http_ok(manifest.health_url):
            return f"{manifest.health_url} stopped answering"
        return None

    def switch(self, state: dict, to_id: str, restore: Path | None = None) -> None:
        """Move the service to a built release, or put everything back."""
        from_id = self.current()
        manifest = self.manifest(to_id)
        before = self.manifest(from_id) if self.complete(from_id) else manifest
        state["pending"] = {
            "from": from_id,
            "to": to_id,
            "step": "stopping",
            "backup": None,
        }
        self.save_state(state)
        try:
            self.out(f"Stopping {before.service}")
            self.system.systemctl("stop", before.service, check=False)
            backup = self.snapshot(before, from_id or "first-install")
            state["pending"].update(step="switching", backup=backup and str(backup))
            self.save_state(state)
            if restore:
                self.restore(manifest, restore)
            self.out(f"Switching to {to_id}")
            self.activate(to_id)
            self.system.systemctl("enable", manifest.service, check=False)
            self.system.systemctl("start", manifest.service, check=False)
            state["pending"]["step"] = "checking"
            self.save_state(state)
            self.out(f"Checking {manifest.health_url or manifest.service}")
            problem = self.wait_healthy(manifest)
        except BaseException:
            self.out("The switch stopped part-way")
            self.undo(state, restart=True, skip=False)
            raise
        if problem:
            self.out(f"{to_id} is not healthy: {problem}")
            self.undo(state, restart=True, skip=True)
            if from_id is None:
                raise UpdateError(
                    f"{to_id} is not healthy ({problem}) and there is no earlier release "
                    f"to go back to. See journalctl -u {manifest.service}."
                )
            raise UpdateError(
                f"{to_id} is not healthy ({problem}). Rolled back to {from_id}."
            )
        state.update(previous=from_id, backup=backup and str(backup), pending=None)
        state["skip"] = [skipped for skipped in state["skip"] if skipped != to_id]
        self.record(state, f"switched {from_id or 'nothing'} -> {to_id}")
        self.save_state(state)
        self.prune(state)
        try:
            self.system.install_tools(self.source_of(to_id) / "deploy", self.app)
        except (OSError, SyntaxError, UpdateError) as exc:
            self.out(
                f"WARNING: kept the installed hub-update; the one in {to_id} did not install: {exc}"
            )
        self.out(f"{self.app} is on {to_id}")

    def undo(self, state: dict, restart: bool, skip: bool) -> None:
        """Put back the release and data from before the pending switch."""
        pending = state["pending"]
        back, left = pending["from"], pending["to"]
        if skip and left not in state["skip"]:
            state["skip"].append(left)
        if not self.complete(back):
            state["pending"] = None
            self.record(state, f"{left} failed with nothing to go back to")
            self.save_state(state)
            return
        manifest = self.manifest(back)
        self.out(f"Rolling back to {back}")
        if restart:
            self.system.systemctl("stop", manifest.service, check=False)
        if pending["backup"] and pending["step"] != "stopping":
            self.restore(manifest, Path(pending["backup"]))
        self.activate(back)
        state["pending"] = None
        self.record(state, f"rolled back {left} -> {back}")
        self.save_state(state)
        if not restart:
            return
        self.system.systemctl("start", manifest.service, check=False)
        problem = self.wait_healthy(manifest)
        if problem:
            self.out(
                f"WARNING: {back} is not healthy either: {problem}. See journalctl -u {manifest.service}."
            )

    def recover_pending(self, state: dict, restart: bool) -> None:
        if state["pending"]:
            self.out(f"An update to {state['pending']['to']} was cut short")
            self.undo(state, restart=restart, skip=False)

    def prune(self, state: dict) -> None:
        keep = {name for name in (self.current(), state["previous"]) if name}
        builds = sorted(
            self.releases.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True
        )
        for build in builds:
            if build.name in keep:
                continue
            if self.complete(build.name) and len(keep) < KEEP_RELEASES:
                keep.add(build.name)
                continue
            shutil.rmtree(build, ignore_errors=True)
        if self.backups.is_dir():
            snapshots = sorted(
                (d for d in self.backups.iterdir() if not d.name.startswith(".")),
                reverse=True,
            )
            for snapshot in snapshots[KEEP_BACKUPS:]:
                if str(snapshot) != state["backup"]:
                    shutil.rmtree(snapshot, ignore_errors=True)

    # commands ---------------------------------------------------------
    def update(
        self,
        ref: str | None = None,
        source: Path | None = None,
        repo_url: str | None = None,
        force: bool = False,
    ) -> None:
        with self.locked():
            state = self.load_state()
            self.recover_pending(state, restart=True)
            if repo_url:
                state["repo_url"] = repo_url
                self.save_state(state)
            if source:
                target = self.from_checkout(source)
            else:
                target = self.from_git(state["repo_url"], ref)
            if target.id == self.current():
                self.out(f"{self.app} is already on {target.id}")
                return
            if target.id in state["skip"] and not (ref or source or force):
                self.out(
                    f"Skipping {target.id}: it failed its health check or was rolled back. "
                    "Pass --force to install it anyway."
                )
                return
            self.prepare(target)
            self.switch(state, target.id)

    def rollback(self, to: str | None = None, restore_data: bool = False) -> None:
        with self.locked():
            state = self.load_state()
            self.recover_pending(state, restart=True)
            current = self.current()
            target = to or state["previous"]
            if not target:
                raise UpdateError(
                    f"There is no earlier release of {self.app} to roll back to."
                )
            if target == current:
                raise UpdateError(f"{self.app} is already on {target}.")
            if not self.complete(target):
                raise UpdateError(
                    f"{target} is not kept on this hub. Kept: {', '.join(self.kept())}."
                )
            restore = None
            if restore_data:
                if not state["backup"] or not Path(state["backup"]).is_dir():
                    raise UpdateError(
                        f"No data snapshot from before {current} is kept."
                    )
                restore = Path(state["backup"])
            self.switch(state, target, restore=restore)
            # Keep the timer from installing the release that was just rolled back.
            if current and current not in state["skip"]:
                state["skip"].append(current)
                self.save_state(state)

    def recover(self, restart: bool = True) -> None:
        with self.locked():
            state = self.load_state()
            if not state["pending"]:
                self.out(f"No unfinished update of {self.app}")
                return
            self.recover_pending(state, restart=restart)

    def status(self, check: bool = False) -> list[str]:
        state = self.load_state()
        current = self.current()
        if not current and not self.state_path.exists():
            return [f"{self.app} is not installed under {self.home}."]
        lines = []
        info = {}
        if self.complete(current):
            info = json.loads((self.releases / current / "release.json").read_text())
        lines.append(
            f"current   {current or 'none'}  ({info.get('ref', '?')}, built {info.get('built_at', '?')})"
        )
        lines.append(f"previous  {state['previous'] or 'none'}")
        lines.append(f"kept      {', '.join(self.kept()) or 'none'}")
        if self.complete(current):
            service = self.manifest(current).service
            lines.append(
                f"service   {service} {'active' if self.system.is_active(service) else 'NOT active'}"
            )
        if state["skip"]:
            lines.append(f"skipped   {', '.join(state['skip'])}")
        if state["pending"]:
            lines.append(
                f"pending   switch to {state['pending']['to']} was cut short: run hub-update recover {self.app}"
            )
        if check:
            tag = self.latest_tag(self.fetch(state["repo_url"]))
            lines.append(f"latest    {tag}")
        lines.extend(f"history   {event}" for event in state["history"][-5:])
        return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hub-update",
        description="Install, update and roll back a hub app, with automatic rollback.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/opt"),
        help="Where hub apps live (default /opt)",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path("/var/backups"),
        help="Where data snapshots go (default /var/backups)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    update = commands.add_parser(
        "update", help="Install the newest release, or a ref or checkout"
    )
    update.add_argument("app")
    source = update.add_mutually_exclusive_group()
    source.add_argument(
        "--ref", help="Branch, tag or commit (default: newest <app>-v* tag)"
    )
    source.add_argument(
        "--source", type=Path, help="A local checkout of the repository"
    )
    update.add_argument(
        "--repo-url",
        help=f"Repository to fetch from, remembered (default {DEFAULT_REPO})",
    )
    update.add_argument(
        "--force", action="store_true", help="Install a release even if it was skipped"
    )

    rollback = commands.add_parser(
        "rollback", help="Go back to the previous release, or another kept one"
    )
    rollback.add_argument("app")
    rollback.add_argument(
        "--to", help="Release id from `status` (default: the previous release)"
    )
    rollback.add_argument(
        "--restore-data",
        action="store_true",
        help="Also put back the data snapshot taken when the current release was installed",
    )

    recover = commands.add_parser(
        "recover", help="Roll back an update that was cut short"
    )
    recover.add_argument("app")
    recover.add_argument(
        "--no-restart",
        action="store_true",
        help="Leave the service alone (used at boot)",
    )

    status = commands.add_parser("status", help="Show the installed releases")
    status.add_argument("app")
    status.add_argument(
        "--check", action="store_true", help="Fetch and show the newest release tag"
    )

    args = parser.parse_args(argv)
    if not APP_NAME.fullmatch(args.app):
        parser.error(f"{args.app!r} is not an app name like bathroom-hub")
    if (args.command != "status" or args.check) and os.geteuid() != 0:
        parser.error("run this with sudo")
    # Releases are built by root and read by the service user.
    os.umask(0o022)
    updater = Updater(args.app, root=args.root, backup_root=args.backup_root)
    try:
        if args.command == "update":
            updater.update(
                ref=args.ref,
                source=args.source,
                repo_url=args.repo_url,
                force=args.force,
            )
        elif args.command == "rollback":
            updater.rollback(to=args.to, restore_data=args.restore_data)
        elif args.command == "recover":
            updater.recover(restart=not args.no_restart)
        else:
            print("\n".join(updater.status(check=args.check)))
    except UpdateError as exc:
        print(f"hub-update: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
