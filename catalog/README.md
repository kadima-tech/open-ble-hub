# Public protocol catalog, version 1

This repository owns the data used by the OpenBLE website. Edit one JSON manifest
per protocol in `catalog/protocols/`; keep code in `packages/openble-<protocol>/`
and manuals beside it (or `docs/` for manual-only protocols). Add as many exact
device models as the evidence supports. Device IDs are stable and globally unique across the catalog. Prefix new IDs
with the protocol name so issue labels identify exactly one model.

`python3 scripts/catalog.py` validates every manifest, checks every evidence/manual
path, ensures every package has exactly one manifest, and exports
`dist/catalog/v1/catalog.json`. Package version and Python requirement are read
from `pyproject.toml`, never copied into a manifest. Exported versions describe
the source revision, which may be ahead of the latest PyPI release.

## Verification belongs to the device

| Status | Meaning |
| --- | --- |
| `verified` | A live model has been tested with this OpenBLE library; include platform, firmware when known, notes and evidence. |
| `reported` | A community report exists; a maintainer has not verified it. |
| `documented` | The model appears in protocol evidence; compatibility is not claimed. |
| `planned` | Work is planned; the device cannot be used yet. |
| `unsupported` | Known incompatibility or support gap; explain it in notes. |

Each model records brand, model, verification status, nullable firmware/platform,
notes, and evidence links to tracked files. Unknown firmware stays `null`.
Documentation or a parser test alone cannot promote a device to `verified`.
Sonicare currently has one verified HX999X handle: add other exact models when
their identity and evidence are available, without guessing retail model names.

## Issues and publication

The publisher creates missing protocol/model labels while preserving existing label settings.
Label issues `protocol:<protocol-id>` and/or `device:<device-id>`. Device labels
identify exactly one model; duplicate device IDs across protocols fail validation. Publication reads all issue pages, excludes pull requests, and exports
open/closed issues with links and affected models. Unlabelled issues are not
classified automatically. An API failure fails the export; it never reports
unknown issue status as zero issues.

Issue titles are **untrusted, user-controlled plain text**, even after publication
in this feed. Consumers must escape them for their output context: use HTML
escaping or `textContent` in a website, never `innerHTML` or a raw HTML template
slot. JSON encoding and schema validation do not make a title safe HTML.
The OpenBLE website escapes titles in both open and closed issue lists.

The **Publish protocol catalog** workflow validates pull requests. On changes to
main, releases, its six-hour schedule, or a manual dispatch it publishes `catalog.json`
and `schema.json` as assets on the stable `catalog-v1` GitHub release:

    https://github.com/kadima-tech/openble/releases/download/catalog-v1/catalog.json

Issue events do not trigger workflows; issue edits and label changes appear on
the next scheduled or manual publication. Publishing always checks out main on
`ubuntu-latest`, disables persisted Git credentials, and provides the repository
token only to the export/label and release-upload steps.

This uses the repository's own GitHub token; no cross-repository secret or
external database is required. Every payload includes the source commit and
generation timestamp. Version 1 remains compatible; breaking changes use a new
schema version and release tag. Manifest validation and publisher tests run before publication.
