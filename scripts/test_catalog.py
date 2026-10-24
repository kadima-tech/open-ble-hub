import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from catalog import (
    ROOT,
    build_catalog,
    ensure_labels,
    fetch_issues,
    main,
    validate_protocol,
)


class CatalogTests(unittest.TestCase):
    def test_all_packages_and_model_evidence_are_registered(self):
        catalog = build_catalog()
        self.assertEqual(catalog["schemaVersion"], 1)
        self.assertEqual(len(catalog["revision"]), 40)
        lifesense = next(p for p in catalog["protocols"] if p["id"] == "lifesense")
        self.assertGreater(len(lifesense["devices"]), 1)
        self.assertTrue(lifesense["packageMetadata"]["version"])

    def test_issues_relate_to_protocols_and_exact_models(self):
        issues = [
            {
                "number": 12,
                "title": "A model finding",
                "state": "open",
                "labels": [{"name": "device:lifesense-dl8780"}],
            }
        ]
        catalog = build_catalog(issues=issues)
        lifesense = next(p for p in catalog["protocols"] if p["id"] == "lifesense")
        self.assertEqual(lifesense["issues"][0]["deviceIds"], ["lifesense-dl8780"])
        self.assertEqual(sum(len(p["issues"]) for p in catalog["protocols"]), 1)

    def test_duplicate_models_missing_evidence_and_unsupported_states_fail(self):
        protocol = build_catalog()["protocols"][0]
        duplicate = copy.deepcopy(protocol)
        duplicate["devices"].append(copy.deepcopy(duplicate["devices"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate device"):
            validate_protocol(duplicate)
        invalid = copy.deepcopy(protocol)
        invalid["devices"][0]["status"] = "probably works"
        with self.assertRaisesRegex(ValueError, "Unknown verification"):
            validate_protocol(invalid)
        invalid["devices"][0]["status"] = "verified"
        invalid["devices"][0]["evidence"] = []
        with self.assertRaisesRegex(ValueError, "needs evidence"):
            validate_protocol(invalid)

    @patch.dict("os.environ", {"GH_TOKEN": "fixture-not-a-real-token"})
    @patch("catalog.subprocess.run")
    @patch(
        "catalog.subprocess.check_output", return_value='[{"name":"protocol:fixture"}]'
    )
    def test_missing_labels_are_created_without_overwriting_existing_labels(
        self, read, run
    ):
        ensure_labels(
            [
                {
                    "issueLabels": ["protocol:fixture"],
                    "devices": [{"issueLabels": ["device:fixture-model"]}],
                }
            ]
        )
        run.assert_called_once()
        self.assertIn("device:fixture-model", run.call_args.args[0])
        self.assertNotIn("--force", run.call_args.args[0])

    def test_evidence_cannot_escape_the_repository(self):
        protocol = copy.deepcopy(build_catalog()["protocols"][0])
        protocol["devices"][0]["evidence"][0]["path"] = "../outside.md"
        with self.assertRaisesRegex(ValueError, "relative path"):
            validate_protocol(protocol, ROOT)

    def test_records_rejected_by_the_website_are_rejected_before_publication(self):
        source = next(p for p in build_catalog()["protocols"] if p["id"] == "lifesense")
        mutations = [
            lambda p: p["devices"][0].pop("firmware"),
            lambda p: p["devices"][0].pop("platform"),
            lambda p: p["devices"][0].update(firmware=""),
            lambda p: p["devices"][0].update(firmware="  "),
            lambda p: p.update(integrations=[""]),
            lambda p: p.update(capabilities=[[" ", "Read", "Details"]]),
            lambda p: p.update(code="  "),
            lambda p: p.update(manual=str(ROOT / p["manual"])),
            lambda p: p.update(manual="catalog/../README.md"),
            lambda p: p.update(extraManual=[]),
            lambda p: p.update(extraManual=["", "README.md"]),
            lambda p: p["devices"][0]["evidence"][0].update(title=" "),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                protocol = copy.deepcopy(source)
                mutate(protocol)
                with self.assertRaises(ValueError):
                    validate_protocol(protocol)

    def test_device_labels_cannot_refer_to_models_in_two_protocols(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["catalog", "packages", "docs"]:
                shutil.copytree(ROOT / name, root / name)
            path = root / "catalog/protocols/sonicare.json"
            protocol = json.loads(path.read_text())
            protocol["devices"][0]["id"] = "a2"
            protocol["devices"][0]["issueLabels"] = ["device:a2"]
            path.write_text(json.dumps(protocol))
            with self.assertRaisesRegex(ValueError, "across protocols"):
                build_catalog(root)

    @patch("catalog.urlopen")
    def test_all_issue_pages_are_read_and_pull_requests_are_excluded(self, open_url):
        first_page = [{"number": 1}] + [
            {"number": number, "pull_request": {}} for number in range(2, 101)
        ]
        second_page = [{"number": 101}]
        open_url.side_effect = [
            io.StringIO(json.dumps(first_page)),
            io.StringIO(json.dumps(second_page)),
        ]
        self.assertEqual([issue["number"] for issue in fetch_issues()], [1, 101])
        self.assertIn("page=2", open_url.call_args.args[0].full_url)

    @patch("catalog.fetch_issues", side_effect=URLError("fixture API failure"))
    def test_issue_api_failure_does_not_write_a_publishable_feed(self, fetch):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog.json"
            with (
                patch("sys.argv", ["catalog.py", "--issues", "--output", str(output)]),
                self.assertRaises(URLError),
            ):
                main()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
