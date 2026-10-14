"""Google Health API (v4) writes for weight and body fat.

Write support for Weight and Body Fat is listed in the Google Health API
release notes (2026-03-24). Data points are created with

    POST https://health.googleapis.com/v4/users/me/dataTypes/{type}/dataPoints

and the response is an Operation, since writes are applied asynchronously.

Linking uses OAuth 2.0 with PKCE and a "Desktop app" OAuth client. Desktop
clients may redirect to http://localhost. The Pi is not localhost for the
browser doing the sign-in, so the browser lands on a page that does not load.
The user pastes that address back into the UI, and the code is exchanged here.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://health.googleapis.com/v4/users/me/dataTypes"
SCOPE = "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.writeonly"
REDIRECT_URI = "http://localhost"
WEIGHT_TYPE = "weight"
BODY_FAT_TYPE = "body-fat"


class GoogleError(Exception):
    pass


def pkce_challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )


def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    return verifier, pkce_challenge(verifier)


def authorization_url(client_id: str, state: str, challenge: str) -> str:
    query = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(query)}"


def parse_redirect(text: str) -> tuple[str, str | None]:
    """Return (code, state) from a pasted redirect URL, or (code, None) for a bare code."""
    text = text.strip()
    if "code=" not in text:
        if not text:
            raise GoogleError(
                "Paste the address the browser ended on after signing in."
            )
        return text, None
    query = parse_qs(urlparse(text).query if "://" in text else text.lstrip("?"))
    if "error" in query:
        raise GoogleError(f"Google returned an error: {query['error'][0]}")
    code = query.get("code", [""])[0]
    if not code:
        raise GoogleError("No authorisation code in that address.")
    return code, query.get("state", [None])[0]


async def _token_request(
    session: aiohttp.ClientSession, data: dict[str, str]
) -> dict[str, Any]:
    async with session.post(
        TOKEN_URL, data=data, timeout=aiohttp.ClientTimeout(total=30)
    ) as resp:
        body = await resp.json(content_type=None)
        if resp.status != 200:
            detail = body.get("error_description") or body.get("error") or resp.status
            raise GoogleError(f"Token request failed: {detail}")
        return body


async def exchange_code(
    session: aiohttp.ClientSession,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    verifier: str,
) -> dict[str, Any]:
    body = await _token_request(
        session,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
    )
    if "refresh_token" not in body:
        raise GoogleError(
            "Google did not return a refresh token. Remove the app's access in your Google account and link again."
        )
    body["expires_at"] = time.time() + float(body.get("expires_in", 3600)) - 60
    return body


async def refresh_access_token(
    session: aiohttp.ClientSession,
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> tuple[str, float]:
    body = await _token_request(
        session,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    return body["access_token"], time.time() + float(body.get("expires_in", 3600)) - 60


def sample_time(measured_at: datetime, utc_offset_s: int) -> dict[str, str]:
    physical = measured_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"physicalTime": physical, "utcOffset": f"{int(utc_offset_s)}s"}


def weight_point(
    weight_kg: float, measured_at: datetime, utc_offset_s: int
) -> dict[str, Any]:
    return {
        "dataSource": {"recordingMethod": "ACTIVELY_MEASURED"},
        "weight": {
            "weightGrams": round(weight_kg * 1000),
            "sampleTime": sample_time(measured_at, utc_offset_s),
            "notes": "Philips DL8780 via open-ble-hub",
        },
    }


def body_fat_point(
    fat_pct: float, measured_at: datetime, utc_offset_s: int
) -> dict[str, Any]:
    return {
        "dataSource": {"recordingMethod": "ACTIVELY_MEASURED"},
        "bodyFat": {
            "percentage": round(fat_pct, 1),
            "sampleTime": sample_time(measured_at, utc_offset_s),
        },
    }


async def create_data_point(
    session: aiohttp.ClientSession,
    access_token: str,
    data_type: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    url = f"{API_BASE}/{data_type}/dataPoints"
    headers = {"Authorization": f"Bearer {access_token}"}
    async with session.post(
        url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
    ) as resp:
        payload = await resp.json(content_type=None) if resp.content_length != 0 else {}
        if resp.status >= 300:
            message = (
                (payload or {}).get("error", {}).get("message")
                if isinstance(payload, dict)
                else None
            )
            raise GoogleError(
                f"{data_type} write failed ({resp.status}): {message or payload}"
            )
        if isinstance(payload, dict) and payload.get("error"):
            raise GoogleError(
                f"{data_type} write failed: {payload['error'].get('message')}"
            )
        return payload or {}
