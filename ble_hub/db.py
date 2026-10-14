"""SQLite storage for profiles, Google links, measurements, settings and events."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sex TEXT NOT NULL CHECK (sex IN ('male', 'female')),
    birth_date TEXT NOT NULL,
    height_cm REAL NOT NULL,
    start_weight_kg REAL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS google_links (
    profile_id INTEGER PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    refresh_token TEXT NOT NULL,
    access_token TEXT,
    expires_at REAL,
    linked_at TEXT NOT NULL,
    last_ok_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS oauth_pending (
    state TEXT PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    verifier TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY,
    measured_at TEXT NOT NULL,
    utc_offset_s INTEGER NOT NULL,
    weight_kg REAL NOT NULL,
    impedance REAL,
    scale_fat_pct REAL,
    raw_weight TEXT NOT NULL,
    raw_append TEXT,
    received_at TEXT NOT NULL,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE SET NULL,
    assigned_by TEXT,
    assign_note TEXT,
    fat_pct REAL,
    lean_kg REAL,
    bmi REAL,
    google_status TEXT NOT NULL DEFAULT 'none',
    google_error TEXT,
    google_profile_id INTEGER,
    UNIQUE (measured_at, weight_kg, impedance)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
"""

PROFILE_FIELDS = ("name", "sex", "birth_date", "height_cm", "start_weight_kg")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # settings ---------------------------------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row and row["value"] is not None else default

    def set_setting(self, key: str, value: str | None) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    # events -----------------------------------------------------------
    def log(self, message: str, level: str = "info") -> None:
        self.conn.execute(
            "INSERT INTO events (at, level, message) VALUES (?, ?, ?)",
            (now_iso(), level, message),
        )
        self.conn.execute(
            "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 500)"
        )
        self.conn.commit()

    def events(self, limit: int = 30) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    # profiles ---------------------------------------------------------
    def profiles(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT p.*, g.profile_id IS NOT NULL AS google_linked, g.last_error AS google_last_error, g.last_ok_at AS google_last_ok "
            "FROM profiles p LEFT JOIN google_links g ON g.profile_id = p.id ORDER BY p.name COLLATE NOCASE"
        ).fetchall()

    def profile(self, profile_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM profiles WHERE id = ?", (profile_id,)
        ).fetchone()

    def create_profile(self, values: dict[str, Any]) -> int:
        cur = self.conn.execute(
            "INSERT INTO profiles (name, sex, birth_date, height_cm, start_weight_kg, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (*(values.get(field) for field in PROFILE_FIELDS), now_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_profile(self, profile_id: int, values: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE profiles SET name = ?, sex = ?, birth_date = ?, height_cm = ?, start_weight_kg = ? WHERE id = ?",
            (*(values.get(field) for field in PROFILE_FIELDS), profile_id),
        )
        self.conn.commit()

    def delete_profile(self, profile_id: int) -> None:
        self.conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        self.conn.commit()

    def recent_weights(self, profile_id: int, limit: int = 5) -> list[float]:
        rows = self.conn.execute(
            "SELECT weight_kg FROM measurements WHERE profile_id = ? ORDER BY measured_at DESC LIMIT ?",
            (profile_id, limit),
        ).fetchall()
        return [row["weight_kg"] for row in rows]

    # google -----------------------------------------------------------
    def google_link(self, profile_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM google_links WHERE profile_id = ?", (profile_id,)
        ).fetchone()

    def save_google_link(
        self,
        profile_id: int,
        refresh_token: str,
        access_token: str | None,
        expires_at: float | None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO google_links (profile_id, refresh_token, access_token, expires_at, linked_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(profile_id) DO UPDATE SET refresh_token = excluded.refresh_token, access_token = excluded.access_token, "
            "expires_at = excluded.expires_at, linked_at = excluded.linked_at, last_error = NULL",
            (profile_id, refresh_token, access_token, expires_at, now_iso()),
        )
        self.conn.commit()

    def update_google_token(
        self, profile_id: int, access_token: str, expires_at: float
    ) -> None:
        self.conn.execute(
            "UPDATE google_links SET access_token = ?, expires_at = ? WHERE profile_id = ?",
            (access_token, expires_at, profile_id),
        )
        self.conn.commit()

    def mark_google(self, profile_id: int, *, error: str | None) -> None:
        if error is None:
            self.conn.execute(
                "UPDATE google_links SET last_ok_at = ?, last_error = NULL WHERE profile_id = ?",
                (now_iso(), profile_id),
            )
        else:
            self.conn.execute(
                "UPDATE google_links SET last_error = ? WHERE profile_id = ?",
                (error, profile_id),
            )
        self.conn.commit()

    def delete_google_link(self, profile_id: int) -> None:
        self.conn.execute(
            "DELETE FROM google_links WHERE profile_id = ?", (profile_id,)
        )
        self.conn.commit()

    def add_oauth_pending(self, state: str, profile_id: int, verifier: str) -> None:
        self.conn.execute(
            "DELETE FROM oauth_pending WHERE profile_id = ?", (profile_id,)
        )
        self.conn.execute(
            "INSERT INTO oauth_pending (state, profile_id, verifier, created_at) VALUES (?, ?, ?, ?)",
            (state, profile_id, verifier, now_iso()),
        )
        self.conn.commit()

    def take_oauth_pending(self, state: str) -> sqlite3.Row | None:
        row = self.conn.execute(
            "SELECT * FROM oauth_pending WHERE state = ?", (state,)
        ).fetchone()
        if row:
            self.conn.execute("DELETE FROM oauth_pending WHERE state = ?", (state,))
            self.conn.commit()
        return row

    def oauth_pending_for(self, profile_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM oauth_pending WHERE profile_id = ?", (profile_id,)
        ).fetchone()

    # measurements -----------------------------------------------------
    def insert_measurement(self, values: dict[str, Any]) -> int | None:
        """Insert a weigh. Returns the new id, or None when it was already stored."""
        columns = list(values)
        try:
            cur = self.conn.execute(
                f"INSERT INTO measurements ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [values[column] for column in columns],
            )
        except sqlite3.IntegrityError:
            return None
        self.conn.commit()
        return int(cur.lastrowid)

    def measurement(self, measurement_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM measurements WHERE id = ?", (measurement_id,)
        ).fetchone()

    def measurements(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT m.*, p.name AS profile_name FROM measurements m LEFT JOIN profiles p ON p.id = m.profile_id "
            "ORDER BY m.measured_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def profile_measurements(
        self, profile_id: int, *, since: str | None = None, limit: int | None = None
    ) -> list[sqlite3.Row]:
        """A person's weighs, newest first."""
        sql = "SELECT * FROM measurements WHERE profile_id = ?"
        params: list[Any] = [profile_id]
        if since:
            sql += " AND measured_at >= ?"
            params.append(since)
        sql += " ORDER BY measured_at DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return self.conn.execute(sql, params).fetchall()

    def unassigned(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM measurements WHERE profile_id IS NULL ORDER BY measured_at DESC"
        ).fetchall()

    def latest_measurement(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM measurements ORDER BY measured_at DESC LIMIT 1"
        ).fetchone()

    def update_measurement(self, measurement_id: int, values: dict[str, Any]) -> None:
        sets = ", ".join(f"{column} = ?" for column in values)
        self.conn.execute(
            f"UPDATE measurements SET {sets} WHERE id = ?",
            [*values.values(), measurement_id],
        )
        self.conn.commit()

    def delete_measurement(self, measurement_id: int) -> None:
        self.conn.execute("DELETE FROM measurements WHERE id = ?", (measurement_id,))
        self.conn.commit()

    def pending_uploads(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM measurements WHERE google_status IN ('pending', 'error') AND profile_id IS NOT NULL ORDER BY measured_at"
        ).fetchall()
