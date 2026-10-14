# Security policy

## Reporting a vulnerability

Report security issues privately. Do not open a public GitHub issue, and do not put exploit details in a pull request.

- [GitHub private vulnerability reporting](https://github.com/kadima-tech/open-ble-hub/security/advisories/new)
- Email: [jacobus@kadima-tech.com](mailto:jacobus@kadima-tech.com)

Either channel is enough. Include what you found, how to reproduce it, and the commit or the date you pulled `main`.

## What to expect

- An acknowledgement within 3 days.
- A confirmation or a rejection within 7 days of that acknowledgement. We will say so if we need longer.
- For a confirmed issue that exposes health data, Google credentials, or scale pairing secrets, a fix or a mitigation within 14 days, then a private advisory when the fix is on `main`.
- Credit in the advisory if you want to be named.

Research that follows this policy will not be met with legal action.

## Scope

In scope:

- The hub (`ble_hub/`), the Philips client (`philips_ble/`), and the Raspberry Pi installer (`deploy/`).
- How the project stores and handles health measurements, the Google OAuth client secret, refresh and access tokens, and scale pairing secrets.
- The local web app, when a bug would expose that data beyond the machine or the home network.

Out of scope:

- Philips, Google, and other third-party services. If a dependency advisory affects a release of this project, tell us as well as upstream.
- No login on the web app when it is used as documented, on a trusted home network. The app has no authentication and listens on all interfaces by default. Do not put it on the public internet.
- Physical access to the computer that runs the hub.

## Supported versions

There are no versioned releases. Security fixes land on `main`. Update by pulling that branch.
