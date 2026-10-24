#!/usr/bin/env python3
"""Validate protocol manifests and build the public, versioned website catalog."""

import argparse
import json
import os
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/kadima-tech/openble"
STATUSES = {"verified", "reported", "documented", "planned", "unsupported"}
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def source_file(value, root=ROOT):
    require(
        nonempty(value)
        and not re.search(r"[\\:?#%]", value)
        and not value.startswith("/")
        and all(part not in {"", ".", ".."} for part in value.split("/")),
        "Source path must be a safe relative path within the repository",
    )
    file = (root / value).resolve()
    require(file.is_relative_to(root.resolve()), "Source path escapes repository")
    require(file.is_file(), f"Missing source file: {value}")
    return file


def validate_protocol(protocol, root=ROOT):
    for key in [
        "id",
        "name",
        "type",
        "summary",
        "description",
        "tested",
        "limits",
        "manual",
        "next",
    ]:
        require(
            isinstance(protocol.get(key), str) and protocol[key].strip(),
            f"Missing {key}",
        )
    require(SLUG.fullmatch(protocol["id"]), "Invalid protocol id")
    source_file(protocol["manual"], root)
    if "extraManual" in protocol:
        require(
            isinstance(protocol["extraManual"], list)
            and len(protocol["extraManual"]) == 2
            and nonempty(protocol["extraManual"][0]),
            "extraManual needs a title and path",
        )
        source_file(protocol["extraManual"][1], root)
    require("package" in protocol, "Missing package (use null for manual-only entries)")
    package = protocol.get("package")
    if package:
        require(re.fullmatch(r"openble-[a-z0-9-]+", package), "Invalid package name")
        metadata = tomllib.loads(
            source_file(f"packages/{package}/pyproject.toml", root).read_text()
        )
        require(
            metadata["project"]["name"] == package,
            "Package name does not match pyproject.toml",
        )
        for key in ["version", "requires-python"]:
            require(nonempty(metadata["project"].get(key)), f"Invalid package {key}")
        require(
            nonempty(protocol.get("code")),
            "Library needs a code example",
        )
    else:
        require(
            package is None and "code" in protocol and protocol["code"] is None,
            "Manual-only entry cannot have package/example",
        )
    capabilities = protocol.get("capabilities")
    require(isinstance(capabilities, list) and capabilities, "Missing capabilities")
    require(
        all(
            isinstance(row, list) and len(row) == 3 and all(nonempty(v) for v in row)
            for row in capabilities
        ),
        "Invalid capability row",
    )
    require(
        isinstance(protocol.get("integrations"), list)
        and all(nonempty(v) for v in protocol["integrations"]),
        "Invalid integrations",
    )
    require(
        protocol.get("issueLabels") == ["protocol:" + protocol["id"]],
        "Use the canonical protocol:<id> issue label",
    )
    devices = protocol.get("devices")
    require(
        isinstance(devices, list) and devices,
        "Each protocol needs at least one device entry",
    )
    ids = set()
    for device in devices:
        require(
            isinstance(device, dict) and SLUG.fullmatch(device.get("id", "")),
            "Invalid device id",
        )
        require(device["id"] not in ids, "Duplicate device id")
        ids.add(device["id"])
        for key in ["brand", "model", "notes"]:
            require(
                isinstance(device.get(key), str) and device[key].strip(),
                f"Device needs {key}",
            )
        require(device.get("status") in STATUSES, "Unknown verification status")
        require(
            package or device["status"] != "verified",
            "Manual-only model cannot claim verified library support",
        )
        for key in ["firmware", "platform"]:
            require(
                key in device and (device[key] is None or nonempty(device[key])),
                f"Invalid {key}",
            )
        require(
            device.get("issueLabels") == ["device:" + device["id"]],
            "Use the canonical device:<id> issue label",
        )
        require(
            isinstance(device.get("evidence"), list) and device["evidence"],
            "Device needs evidence",
        )
        for item in device["evidence"]:
            require(
                nonempty(item.get("title")),
                "Evidence needs a title",
            )
            source_file(item.get("path"), root)
        if device["status"] == "verified":
            require(device.get("platform"), "Verified model needs a test platform")
    return protocol


def ensure_labels(protocols):
    """Create missing catalog labels, preserving any existing label settings."""
    require(os.environ.get("GH_TOKEN"), "GH_TOKEN is required to create catalog labels")
    existing = {
        item["name"]
        for item in json.loads(
            subprocess.check_output(
                ["gh", "label", "list", "--limit", "10000", "--json", "name"], text=True
            )
        )
    }
    labels = set()
    for protocol in protocols:
        labels.update(protocol["issueLabels"])
        for device in protocol["devices"]:
            labels.update(device["issueLabels"])
    for label in sorted(labels - existing):
        subprocess.run(
            [
                "gh",
                "label",
                "create",
                label,
                "--color",
                "8b72a0",
                "--description",
                "OpenBLE catalog relationship: " + label,
            ],
            check=True,
        )


def fetch_issues():
    """Read every page; labels relate an issue to a protocol or exact device."""
    issues = []
    for page in range(1, 101):
        query = urlencode({"state": "all", "per_page": 100, "page": page})
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "openble-catalog",
        }
        if os.environ.get("GH_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
        request = Request(
            "https://api.github.com/repos/kadima-tech/openble/issues?" + query,
            headers=headers,
        )
        with urlopen(request, timeout=30) as response:
            batch = json.load(response)
        require(isinstance(batch, list), "Invalid GitHub issue response")
        issues.extend(issue for issue in batch if "pull_request" not in issue)
        if len(batch) < 100:
            return issues
    raise ValueError(
        "Too many issue pages; refusing to publish an incomplete issue index"
    )


def build_catalog(root=ROOT, issues=None):
    protocols = []
    for file in sorted((root / "catalog/protocols").glob("*.json")):
        protocol = validate_protocol(json.loads(file.read_text()), root)
        require(file.stem == protocol["id"], "Manifest filename must match protocol id")
        protocol["library"] = protocol["package"] is not None
        protocol["packageMetadata"] = None
        if protocol["package"]:
            package = protocol["package"]
            project = tomllib.loads(
                source_file(f"packages/{package}/pyproject.toml", root).read_text()
            )["project"]
            protocol["packageMetadata"] = {
                "version": project["version"],
                "python": project["requires-python"],
                "sourcePath": f"packages/{package}",
            }
        protocol["issues"] = []
        for issue in issues or ():
            labels = {label["name"] for label in issue["labels"]}
            device_ids = [
                device["id"]
                for device in protocol["devices"]
                if set(device["issueLabels"]) & labels
            ]
            if set(protocol["issueLabels"]) & labels or device_ids:
                protocol["issues"].append(
                    {
                        "number": issue["number"],
                        "title": issue["title"],
                        "state": issue["state"],
                        "url": f"{REPOSITORY}/issues/{issue['number']}",
                        "deviceIds": device_ids,
                    }
                )
        protocols.append(protocol)
    require(protocols, "No protocol manifests found")
    ids = [item["id"] for item in protocols]
    require(len(set(ids)) == len(ids), "Duplicate protocol id")
    model_ids = [
        device["id"] for protocol in protocols for device in protocol["devices"]
    ]
    require(
        len(set(model_ids)) == len(model_ids), "Duplicate device id across protocols"
    )
    packages = {item["package"] for item in protocols if item["package"]}
    actual_packages = {
        file.parent.name
        for file in (root / "packages").glob("openble-*/pyproject.toml")
    }
    require(
        packages == actual_packages,
        "Every protocol package must be registered exactly once",
    )
    require(
        len(packages) == sum(item["library"] for item in protocols),
        "Package registered more than once",
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    return {
        "schemaVersion": 1,
        "repository": REPOSITORY,
        "revision": revision,
        "generatedAt": datetime.now(UTC).isoformat(),
        "issuesIncluded": issues is not None,
        "protocols": protocols,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "dist/catalog/v1/catalog.json"
    )
    parser.add_argument(
        "--issues",
        action="store_true",
        help="Include live GitHub issue status; any fetch error fails publication",
    )
    parser.add_argument(
        "--ensure-labels",
        action="store_true",
        help="Create missing protocol/device issue labels (requires GH_TOKEN and gh)",
    )
    args = parser.parse_args()
    if args.ensure_labels:
        ensure_labels(build_catalog()["protocols"])
    catalog = build_catalog(issues=fetch_issues() if args.issues else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, indent=2) + "\n")
    print(
        f"Validated and exported {len(catalog['protocols'])} protocols to {args.output}"
    )


if __name__ == "__main__":
    main()
