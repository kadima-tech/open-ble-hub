"""Ties measurements, profiles, body composition and Google uploads together."""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiohttp

from ble_hub import assign, bodycomp, google_health
from ble_hub.db import Database

SCALE_EPOCH = datetime(2010, 1, 1)
RETRY_SECONDS = 600


def scale_time(seconds: int) -> tuple[datetime, int]:
    """Scale timestamps count local wall-clock seconds from 2010-01-01.

    Returns the instant in UTC and the UTC offset that applied locally.
    """
    local_naive = SCALE_EPOCH + timedelta(seconds=int(seconds))
    local = local_naive.astimezone()
    offset = int(local.utcoffset().total_seconds()) if local.utcoffset() else 0
    return local.astimezone(timezone.utc), offset


class Hub:
    def __init__(self, db: Database):
        self.db = db
        self._session: aiohttp.ClientSession | None = None
        self._wake = asyncio.Event()

    # -- http ------------------------------------------------------------
    async def http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    # -- settings --------------------------------------------------------
    def google_client(self) -> tuple[str, str] | None:
        client_id = self.db.get_setting("google_client_id")
        secret = self.db.get_setting("google_client_secret")
        if client_id and secret:
            return client_id, secret
        return None

    def tolerance(self) -> float:
        try:
            return float(self.db.get_setting("assign_tolerance_kg", str(assign.TOLERANCE_KG)))
        except ValueError:
            return assign.TOLERANCE_KG

    # -- measurements ----------------------------------------------------
    def ingest(self, weight: dict[str, Any], append: dict[str, Any] | None, raw_weight: bytes, raw_append: bytes | None) -> int | None:
        measured_at, offset = scale_time(int(weight["utc_seconds"]))
        impedance = float(weight["impedance"]) if weight.get("impedance") not in (None, "", "0") else None
        values = {
            "measured_at": measured_at.isoformat(timespec="seconds"),
            "utc_offset_s": offset,
            "weight_kg": float(weight["weight_kg"]),
            "impedance": impedance,
            "scale_fat_pct": float(append["body_fat_ratio"]) if append and append.get("body_fat_ratio") else None,
            "raw_weight": raw_weight.hex(" "),
            "raw_append": raw_append.hex(" ") if raw_append else None,
            "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        measurement_id = self.db.insert_measurement(values)
        if measurement_id is None:
            return None
        self.db.log(f"Weigh received: {values['weight_kg']:.1f} kg, impedance {impedance or '-'}")
        self.auto_assign(measurement_id)
        return measurement_id

    def references(self) -> dict[int, float | None]:
        refs = {}
        for profile in self.db.profiles():
            refs[profile["id"]] = assign.reference_weight(self.db.recent_weights(profile["id"]), profile["start_weight_kg"])
        return refs

    def auto_assign(self, measurement_id: int) -> None:
        row = self.db.measurement(measurement_id)
        refs = self.references()
        choice = assign.choose_profile(row["weight_kg"], refs, tolerance=self.tolerance())
        if choice.profile_id is None:
            self.db.update_measurement(measurement_id, {"assign_note": choice.reason})
            self.db.log(f"Weigh {row['weight_kg']:.1f} kg needs a manual choice: {choice.reason}", "warn")
            return
        self.assign(measurement_id, choice.profile_id, by="auto", note=choice.reason)

    def assign(self, measurement_id: int, profile_id: int | None, *, by: str, note: str | None = None) -> None:
        row = self.db.measurement(measurement_id)
        if row is None:
            return
        if profile_id is None:
            self.db.update_measurement(
                measurement_id,
                {"profile_id": None, "assigned_by": None, "assign_note": note or "unassigned by hand", "fat_pct": None, "lean_kg": None, "bmi": None,
                 "google_status": "none" if row["google_status"] != "done" else "done"},
            )
            return
        profile = self.db.profile(profile_id)
        comp = self.composition_for(profile, row)
        linked = self.db.google_link(profile_id) is not None
        status = row["google_status"]
        if status == "done" and row["google_profile_id"] == profile_id:
            new_status = "done"
        else:
            new_status = "pending" if linked else "none"
        self.db.update_measurement(
            measurement_id,
            {
                "profile_id": profile_id,
                "assigned_by": by,
                "assign_note": note,
                "fat_pct": comp.fat_pct if comp else None,
                "lean_kg": comp.lean_kg if comp else None,
                "bmi": comp.bmi if comp else None,
                "google_status": new_status,
                "google_error": None,
            },
        )
        self.db.log(f"Weigh {row['weight_kg']:.1f} kg assigned to {profile['name']} ({by})")
        if new_status == "pending":
            self._wake.set()

    @staticmethod
    def composition_for(profile, row) -> bodycomp.Composition | None:
        measured = datetime.fromisoformat(row["measured_at"])
        return bodycomp.composition(
            male=profile["sex"] == "male",
            birth=date.fromisoformat(profile["birth_date"]),
            height_cm=float(profile["height_cm"]),
            weight_kg=float(row["weight_kg"]),
            impedance=row["impedance"],
            when=measured.date(),
        )

    def recompute_profile(self, profile_id: int) -> None:
        """Refresh body composition after a profile's height, sex or birth date changed."""
        profile = self.db.profile(profile_id)
        for row in self.db.conn.execute("SELECT * FROM measurements WHERE profile_id = ?", (profile_id,)).fetchall():
            comp = self.composition_for(profile, row)
            self.db.update_measurement(
                row["id"],
                {"fat_pct": comp.fat_pct if comp else None, "lean_kg": comp.lean_kg if comp else None, "bmi": comp.bmi if comp else None},
            )

    # -- google ------------------------------------------------------------
    async def access_token(self, profile_id: int) -> str:
        link = self.db.google_link(profile_id)
        if link is None:
            raise google_health.GoogleError("Profile has no linked Google account.")
        if link["access_token"] and link["expires_at"] and link["expires_at"] > time.time():
            return link["access_token"]
        client = self.google_client()
        if client is None:
            raise google_health.GoogleError("Google OAuth client is not configured in Settings.")
        token, expires_at = await google_health.refresh_access_token(
            await self.http(), client_id=client[0], client_secret=client[1], refresh_token=link["refresh_token"]
        )
        self.db.update_google_token(profile_id, token, expires_at)
        return token

    async def upload(self, measurement_id: int) -> None:
        row = self.db.measurement(measurement_id)
        if row is None or row["profile_id"] is None:
            return
        profile_id = row["profile_id"]
        try:
            token = await self.access_token(profile_id)
            measured_at = datetime.fromisoformat(row["measured_at"])
            session = await self.http()
            await google_health.create_data_point(
                session, token, google_health.WEIGHT_TYPE,
                google_health.weight_point(row["weight_kg"], measured_at, row["utc_offset_s"]),
            )
            if row["fat_pct"] is not None:
                await google_health.create_data_point(
                    session, token, google_health.BODY_FAT_TYPE,
                    google_health.body_fat_point(row["fat_pct"], measured_at, row["utc_offset_s"]),
                )
        except (google_health.GoogleError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            message = str(exc) or type(exc).__name__
            self.db.update_measurement(measurement_id, {"google_status": "error", "google_error": message})
            self.db.mark_google(profile_id, error=message)
            self.db.log(f"Google upload failed for weigh {measurement_id}: {message}", "error")
            return
        self.db.update_measurement(measurement_id, {"google_status": "done", "google_error": None, "google_profile_id": profile_id})
        self.db.mark_google(profile_id, error=None)
        self.db.log(f"Uploaded weigh {measurement_id} to Google Health")

    def kick_uploads(self) -> None:
        self._wake.set()

    async def upload_loop(self) -> None:
        while True:
            for row in self.db.pending_uploads():
                if self.db.google_link(row["profile_id"]) is None:
                    self.db.update_measurement(row["id"], {"google_status": "none"})
                    continue
                await self.upload(row["id"])
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), RETRY_SECONDS)
            except asyncio.TimeoutError:
                pass
