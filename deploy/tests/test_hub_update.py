"""hub-update against a fake systemd and pip, with real git and a real filesystem."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

DEPLOY = Path(__file__).resolve().parents[1]
REPO = DEPLOY.parent
sys.path.insert(0, str(DEPLOY))

import hub_update
from hub_update import Manifest, System, UpdateError, Updater

APP = "demo-hub"
SERVICE = "demo-hub.service"
GIT = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com"]
GIT += ["-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]


class PowerCut(BaseException):
    """The process dies where this is raised; nothing after it runs."""


class FakeSystem(System):
    """systemd, pip and HTTP for a hub whose behaviour depends on its version."""

    def __init__(self, home: Path, unit_dir: Path):
        self.home = home
        self.unit_dir = unit_dir
        self.calls: list[tuple] = []
        self.pip: list[list[str]] = []
        self.tools: list[tuple] = []
        self.active: dict[str, bool] = {}
        self.unhealthy: set[str] = set()
        # version -> text it writes to the database when it starts
        self.writes: dict[str, str] = {}
        self.pip_fails = False
        self.cut_power_on_start: str | None = None
        self.now = 0.0

    def run(self, cmd, cwd=None):
        cmd = [str(part) for part in cmd]
        if cmd[0] == "git":
            return super().run(cmd, cwd)
        if cmd[1:3] == ["-m", "venv"]:
            (Path(cmd[3]) / "bin").mkdir(parents=True)
            (Path(cmd[3]) / "bin" / "python").touch()
            return ""
        if cmd[1:3] == ["-m", "pip"]:
            self.pip.append(cmd)
            if self.pip_fails and "check" not in cmd and "--upgrade" not in cmd:
                raise UpdateError("pip install failed: no matching distribution")
            return ""
        raise AssertionError(f"unexpected command {cmd}")

    def running_version(self) -> str:
        return json.loads((self.home / "current" / "release.json").read_text())[
            "version"
        ]

    def systemctl(self, *args, check=True):
        self.calls.append(args)
        if args[0] == "start":
            version = self.running_version()
            if version == self.cut_power_on_start:
                raise PowerCut()
            if version in self.writes:
                data_dir = Manifest.load(
                    self.home / "current" / "src" / "apps" / APP / "deploy" / "hub.toml"
                ).data_dir
                (data_dir / "hub.db").write_text(self.writes[version])
            self.active[args[1]] = version not in self.unhealthy
        elif args[0] == "stop":
            self.active[args[1]] = False

    def is_active(self, service):
        return self.active.get(service, False)

    def restarts(self, service):
        return 0

    def http_ok(self, url):
        return self.active.get(SERVICE, False)

    def sleep(self, seconds):
        self.now += seconds

    def clock(self):
        return self.now

    def install_tools(self, deploy, app):
        self.tools.append((deploy, app))


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [*GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def make_checkout(repo: Path, data_dir: Path) -> None:
    files = {
        "README.md": "Not part of a release.\n",
        f"apps/{APP}/deploy/hub.toml": (
            f'service = "{SERVICE}"\ndata_dir = "{data_dir}"\n'
            'health_url = "http://127.0.0.1:8080/healthz"\nhealth_timeout = 10\nsettle = 4\n'
        ),
        f"apps/{APP}/deploy/{SERVICE}": (
            f"[Service]\nExecStart=/opt/{APP}/current/venv/bin/{APP}\n"
        ),
        "packages/openble-demo/pyproject.toml": '[project]\nname = "openble-demo"\n',
        "packages/openble-unused/pyproject.toml": '[project]\nname = "openble-unused"\n',
    }
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    shutil.copytree(
        DEPLOY, repo / "deploy", ignore=shutil.ignore_patterns("tests", "__pycache__")
    )
    git(repo, "init", "-q", "-b", "main")


def commit(repo: Path, version: str, tag: bool = False) -> str:
    (repo / "apps" / APP / "pyproject.toml").write_text(
        f'[project]\nname = "{APP}"\nversion = "{version}"\n'
        'dependencies = ["openble-demo>=0.1,<0.2", "aiohttp>=3.14.5"]\n'
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", version)
    if tag:
        git(repo, "tag", f"{APP}-v{version}")
    return git(repo, "rev-parse", "HEAD")


class HubTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.repo = tmp / "repo"
        self.repo.mkdir()
        self.data = tmp / "data"
        self.data.mkdir()
        self.db = self.data / "hub.db"
        self.db.write_text("data of 0.1.0")
        make_checkout(self.repo, self.data)
        (tmp / "systemd").mkdir()
        self.lines: list[str] = []
        self.system = FakeSystem(tmp / "opt" / APP, tmp / "systemd")
        self.updater = self.new_updater()

    def tearDown(self):
        self.tmp.cleanup()

    def new_updater(self) -> Updater:
        """Another hub-update process on the same hub."""
        tmp = Path(self.tmp.name)
        return Updater(
            APP,
            root=tmp / "opt",
            backup_root=tmp / "backups",
            system=self.system,
            out=self.lines.append,
        )

    def state(self) -> dict:
        return self.updater.load_state()


class LocalCheckoutTests(HubTestCase):
    def test_first_install_builds_a_release_and_starts_it(self):
        sha = commit(self.repo, "0.1.0")
        self.updater.update(source=self.repo)

        self.assertEqual(self.updater.current(), f"0.1.0-{sha[:7]}")
        release = self.updater.home / "current"
        self.assertTrue((release / "venv" / "bin" / "python").exists())
        self.assertFalse((release / "src" / "README.md").exists())
        self.assertIn(("enable", SERVICE), self.system.calls)
        self.assertIn(("start", SERVICE), self.system.calls)
        self.assertIn("current/venv/bin", (self.system.unit_dir / SERVICE).read_text())
        [install] = [
            cmd
            for cmd in self.system.pip
            if "install" in cmd and "--upgrade" not in cmd
        ]
        self.assertTrue(install[-2].endswith("packages/openble-demo"))
        self.assertTrue(install[-1].endswith(f"apps/{APP}"))
        self.assertNotIn("openble-unused", " ".join(install))
        self.assertEqual(self.system.tools[-1][1], APP)
        self.assertIsNone(self.state()["previous"])

    def test_the_same_commit_twice_is_a_no_op(self):
        commit(self.repo, "0.1.0")
        self.updater.update(source=self.repo)
        calls = len(self.system.calls)
        self.updater.update(source=self.repo)
        self.assertEqual(len(self.system.calls), calls)
        self.assertIn("already on", self.lines[-1])

    def test_uncommitted_changes_get_their_own_release(self):
        sha = commit(self.repo, "0.1.0")
        self.updater.update(source=self.repo)
        (self.repo / "apps" / APP / "deploy" / SERVICE).write_text(
            "[Service]\n# edited\n"
        )
        self.updater.update(source=self.repo)
        self.assertTrue(self.updater.current().startswith(f"0.1.0-{sha[:7]}-dirty-"))
        self.assertIn("# edited", (self.system.unit_dir / SERVICE).read_text())

    def test_update_keeps_the_previous_release_and_a_data_snapshot(self):
        first = f"0.1.0-{commit(self.repo, '0.1.0')[:7]}"
        self.updater.update(source=self.repo)
        second = f"0.2.0-{commit(self.repo, '0.2.0')[:7]}"
        self.updater.update(source=self.repo)

        self.assertEqual(self.updater.current(), second)
        state = self.state()
        self.assertEqual(state["previous"], first)
        self.assertEqual(
            (Path(state["backup"]) / "hub.db").read_text(), "data of 0.1.0"
        )
        self.assertIsNone(state["pending"])

    def test_a_failed_build_leaves_the_running_release_alone(self):
        first = f"0.1.0-{commit(self.repo, '0.1.0')[:7]}"
        self.updater.update(source=self.repo)
        commit(self.repo, "0.2.0")
        self.system.pip_fails = True
        calls = len(self.system.calls)

        with self.assertRaisesRegex(UpdateError, "pip install failed"):
            self.updater.update(source=self.repo)
        self.assertEqual(self.updater.current(), first)
        self.assertEqual(self.updater.kept(), [first])
        self.assertEqual(
            sorted(p.name for p in self.updater.releases.iterdir()), [first]
        )
        self.assertEqual(len(self.system.calls), calls, "the service was not touched")

    def test_an_unhealthy_release_is_rolled_back_with_its_data(self):
        first = f"0.1.0-{commit(self.repo, '0.1.0')[:7]}"
        self.updater.update(source=self.repo)
        second = f"0.2.0-{commit(self.repo, '0.2.0')[:7]}"
        self.system.unhealthy.add("0.2.0")
        self.system.writes["0.2.0"] = "migrated by 0.2.0"

        with self.assertRaisesRegex(UpdateError, f"Rolled back to {first}"):
            self.updater.update(source=self.repo)
        self.assertEqual(self.updater.current(), first)
        self.assertEqual(self.db.read_text(), "data of 0.1.0")
        self.assertTrue(self.system.is_active(SERVICE))
        self.assertEqual(self.system.calls[-1], ("start", SERVICE))
        state = self.state()
        self.assertEqual(state["skip"], [second])
        self.assertIsNone(state["pending"])
        # What the failed release wrote is kept for a look.
        [replaced] = self.updater.backups.glob("*-replaced")
        self.assertEqual((replaced / "hub.db").read_text(), "migrated by 0.2.0")

    def test_a_first_install_that_fails_has_nothing_to_go_back_to(self):
        commit(self.repo, "0.1.0")
        self.system.unhealthy.add("0.1.0")
        with self.assertRaisesRegex(UpdateError, "no earlier release"):
            self.updater.update(source=self.repo)
        self.assertIsNone(self.state()["pending"])

    def test_rollback_goes_back_and_keeps_newer_data(self):
        first = f"0.1.0-{commit(self.repo, '0.1.0')[:7]}"
        self.updater.update(source=self.repo)
        second = f"0.2.0-{commit(self.repo, '0.2.0')[:7]}"
        self.updater.update(source=self.repo)
        self.db.write_text("weighed on 0.2.0")

        self.updater.rollback()
        self.assertEqual(self.updater.current(), first)
        self.assertEqual(self.db.read_text(), "weighed on 0.2.0")
        state = self.state()
        self.assertEqual(state["previous"], second)
        self.assertEqual(state["skip"], [second])
        # And forward again, which is just another rollback.
        self.updater.rollback()
        self.assertEqual(self.updater.current(), second)

    def test_rollback_can_restore_the_data_from_before_the_update(self):
        first = f"0.1.0-{commit(self.repo, '0.1.0')[:7]}"
        self.updater.update(source=self.repo)
        commit(self.repo, "0.2.0")
        self.updater.update(source=self.repo)
        self.db.write_text("migrated by 0.2.0")

        self.updater.rollback(restore_data=True)
        self.assertEqual(self.updater.current(), first)
        self.assertEqual(self.db.read_text(), "data of 0.1.0")

    def test_rollback_without_an_earlier_release(self):
        commit(self.repo, "0.1.0")
        self.updater.update(source=self.repo)
        with self.assertRaisesRegex(UpdateError, "no earlier release"):
            self.updater.rollback()
        with self.assertRaisesRegex(UpdateError, "not kept"):
            self.updater.rollback(to="0.0.1-abcdef0")

    def test_a_switch_cut_short_is_rolled_back_at_boot(self):
        first = f"0.1.0-{commit(self.repo, '0.1.0')[:7]}"
        self.updater.update(source=self.repo)
        commit(self.repo, "0.2.0")
        self.system.writes["0.2.0"] = "half migrated by 0.2.0"

        # The new release starts, writes, and the power goes during the health check.
        def cut_power(seconds):
            raise PowerCut()

        with (
            mock.patch.object(self.system, "sleep", cut_power),
            mock.patch.object(Updater, "undo", side_effect=PowerCut),
            self.assertRaises(PowerCut),
        ):
            self.updater.update(source=self.repo)
        self.assertEqual(self.state()["pending"]["step"], "checking")
        self.assertEqual(self.db.read_text(), "half migrated by 0.2.0")

        calls = len(self.system.calls)
        self.new_updater().recover(restart=False)
        self.assertEqual(self.updater.current(), first)
        self.assertEqual(self.db.read_text(), "data of 0.1.0")
        self.assertIsNone(self.state()["pending"])
        self.assertEqual(self.state()["skip"], [])
        boot_calls = self.system.calls[calls:]
        self.assertEqual(boot_calls, [("daemon-reload",)], "no stop or start at boot")

    def test_an_interrupted_switch_is_rolled_back_by_the_next_update(self):
        first = f"0.1.0-{commit(self.repo, '0.1.0')[:7]}"
        self.updater.update(source=self.repo)
        commit(self.repo, "0.2.0")
        self.system.cut_power_on_start = "0.2.0"
        with (
            mock.patch.object(Updater, "undo", side_effect=PowerCut),
            self.assertRaises(PowerCut),
        ):
            self.updater.update(source=self.repo)
        self.system.cut_power_on_start = None
        self.system.unhealthy.add("0.2.0")

        with self.assertRaises(UpdateError):
            self.new_updater().update(source=self.repo)
        self.assertIn("was cut short", " ".join(self.lines))
        self.assertEqual(self.updater.current(), first)

    def test_a_second_hub_update_is_refused(self):
        commit(self.repo, "0.1.0")
        with self.updater.locked(), self.assertRaisesRegex(UpdateError, "Another"):
            self.new_updater().update(source=self.repo)

    def test_three_releases_are_kept(self):
        ids = []
        for version in ("0.1.0", "0.2.0", "0.3.0", "0.4.0"):
            ids.append(f"{version}-{commit(self.repo, version)[:7]}")
            self.updater.update(source=self.repo)
        self.assertEqual(self.updater.kept(), ids[1:])
        self.assertLessEqual(
            len(list(self.updater.backups.iterdir())), hub_update.KEEP_BACKUPS
        )

    def test_status(self):
        self.assertIn("not installed", self.updater.status()[0])
        commit(self.repo, "0.1.0")
        self.updater.update(source=self.repo)
        status = "\n".join(self.updater.status())
        self.assertIn(f"current   {self.updater.current()}", status)
        self.assertIn(f"{SERVICE} active", status)


class GitReleaseTests(HubTestCase):
    def test_the_newest_release_tag_is_installed(self):
        commit(self.repo, "0.1.0", tag=True)
        sha = commit(self.repo, "0.2.0", tag=True)
        commit(self.repo, "0.3.0.dev0")

        self.updater.update(repo_url=str(self.repo))
        self.assertEqual(self.updater.current(), f"0.2.0-{sha[:7]}")
        src = self.updater.home / "current" / "src"
        self.assertTrue((src / "apps" / APP / "deploy" / "hub.toml").exists())
        self.assertTrue((src / "packages" / "openble-demo" / "pyproject.toml").exists())
        self.assertTrue((src / "deploy" / "hub_update.py").exists())
        self.assertFalse((src / "README.md").exists())
        self.assertEqual(self.state()["repo_url"], str(self.repo))

    def test_a_branch_can_be_followed(self):
        commit(self.repo, "0.1.0", tag=True)
        sha = commit(self.repo, "0.2.0.dev0")
        self.updater.update(repo_url=str(self.repo), ref="main")
        self.assertEqual(self.updater.current(), f"0.2.0.dev0-{sha[:7]}")

    def test_no_release_tag_yet(self):
        commit(self.repo, "0.1.0")
        with self.assertRaisesRegex(UpdateError, "--ref main"):
            self.updater.update(repo_url=str(self.repo))

    def test_unknown_ref(self):
        commit(self.repo, "0.1.0")
        with self.assertRaisesRegex(UpdateError, "not a branch, tag or commit"):
            self.updater.update(repo_url=str(self.repo), ref="nope")

    def test_a_tag_has_to_match_the_app_version(self):
        commit(self.repo, "0.1.0")
        git(self.repo, "tag", f"{APP}-v0.2.0")
        with self.assertRaisesRegex(UpdateError, "does not match version 0.1.0"):
            self.updater.update(repo_url=str(self.repo))

    def test_a_failed_release_is_skipped_until_forced(self):
        first = f"0.1.0-{commit(self.repo, '0.1.0', tag=True)[:7]}"
        self.updater.update(repo_url=str(self.repo))
        commit(self.repo, "0.2.0", tag=True)
        self.system.unhealthy.add("0.2.0")
        with self.assertRaises(UpdateError):
            self.updater.update()

        calls = len(self.system.calls)
        self.updater.update()
        self.assertIn("Skipping", self.lines[-1])
        self.assertEqual(len(self.system.calls), calls)

        self.system.unhealthy.clear()
        self.updater.update(force=True)
        self.assertNotEqual(self.updater.current(), first)
        self.assertEqual(self.state()["skip"], [])


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.system = FakeSystem(Path("/nonexistent"), Path("/nonexistent"))
        self.updater = Updater(APP, system=self.system, out=lambda line: None)
        self.manifest = Manifest(SERVICE, Path("/data"), "http://x/healthz", 10, 4)

    def test_never_answering(self):
        problem = self.updater.wait_healthy(self.manifest)
        self.assertIn("did not answer within 10 s", problem)

    def test_crash_loop_while_starting(self):
        counts = iter([0, 0, 1])
        with mock.patch.object(self.system, "restarts", lambda service: next(counts)):
            problem = self.updater.wait_healthy(self.manifest)
        self.assertIn("crashed while starting", problem)
        self.assertEqual(self.system.now, 2, "without waiting for the timeout")

    def test_crash_loop_after_answering(self):
        self.system.active[SERVICE] = True
        counts = iter([0, 1])
        with mock.patch.object(self.system, "restarts", lambda service: next(counts)):
            problem = self.updater.wait_healthy(self.manifest)
        self.assertIn("stopped within 4 s", problem)

    def test_healthy(self):
        self.system.active[SERVICE] = True
        self.assertIsNone(self.updater.wait_healthy(self.manifest))


class RepositoryAppTests(unittest.TestCase):
    """Every app with deploy/hub.toml in this repository can be installed by hub-update."""

    def test_app_manifests(self):
        manifests = sorted(REPO.glob("apps/*/deploy/hub.toml"))
        self.assertTrue(manifests)
        for path in manifests:
            app = path.parents[1].name
            with self.subTest(app=app):
                manifest = Manifest.load(path)
                unit = (path.parent / manifest.service).read_text()
                self.assertIn(f"ExecStart=/opt/{app}/current/venv/bin/", unit)
                self.assertIn(f"ReadWritePaths={manifest.data_dir}", unit)
                self.assertTrue(manifest.health_url.startswith("http://127.0.0.1:"))

    def test_bathroom_hub_libraries_come_from_packages(self):
        updater = Updater("bathroom-hub", system=System())
        self.assertEqual(
            updater.local_packages(REPO), [REPO / "packages" / "openble-lifesense"]
        )

    def test_tool_units_are_shipped(self):
        for unit in hub_update.TOOL_UNITS:
            text = (DEPLOY / unit).read_text()
            if unit.endswith(".service"):
                self.assertIn(f"ExecStart={System.tool_path} ", text)


if __name__ == "__main__":
    unittest.main()
