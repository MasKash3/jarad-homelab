from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import DB_PATH


CHALLENGE_TTL_SECONDS = 180
ACTION_AUTH_TTL_SECONDS = 60


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class WebAuthnStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.init()

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS webauthn_credentials (
                    credential_id TEXT PRIMARY KEY,
                    public_key BLOB NOT NULL,
                    sign_count INTEGER NOT NULL DEFAULT 0,
                    user_handle TEXT NOT NULL,
                    device_label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS webauthn_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    challenge BLOB NOT NULL,
                    purpose TEXT NOT NULL,
                    user_handle TEXT,
                    action_id TEXT,
                    service_id TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS action_authorizations (
                    token TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    service_id TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                )
                """
            )

    def create_challenge(
        self,
        *,
        challenge: bytes,
        purpose: str,
        user_handle: str | None = None,
        action_id: str | None = None,
        service_id: str | None = None,
    ) -> str:
        now = utc_now()
        challenge_id = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO webauthn_challenges
                    (challenge_id, challenge, purpose, user_handle, action_id, service_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    challenge_id,
                    challenge,
                    purpose,
                    user_handle,
                    action_id,
                    service_id,
                    iso(now),
                    iso(now + timedelta(seconds=CHALLENGE_TTL_SECONDS)),
                ),
            )
        return challenge_id

    def consume_challenge(self, challenge_id: str, purpose: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as db:
            row = db.execute(
                """
                SELECT * FROM webauthn_challenges
                WHERE challenge_id = ? AND purpose = ? AND used_at IS NULL
                """,
                (challenge_id, purpose),
            ).fetchone()
            if not row or parse_iso(row["expires_at"]) <= now:
                return None
            db.execute("UPDATE webauthn_challenges SET used_at = ? WHERE challenge_id = ?", (iso(now), challenge_id))
            return dict(row)

    def add_credential(
        self,
        *,
        credential_id: str,
        public_key: bytes,
        sign_count: int,
        user_handle: str,
        device_label: str,
    ) -> None:
        now = iso(utc_now())
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO webauthn_credentials
                    (credential_id, public_key, sign_count, user_handle, device_label, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (credential_id, public_key, sign_count, user_handle, device_label, now),
            )

    def list_credentials(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM webauthn_credentials"
        params: tuple[Any, ...] = ()
        if not include_disabled:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at DESC"
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def get_credential(self, credential_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM webauthn_credentials WHERE credential_id = ? AND enabled = 1",
                (credential_id,),
            ).fetchone()
            return dict(row) if row else None

    def disable_credential(self, credential_id: str) -> bool:
        with self.connect() as db:
            result = db.execute("UPDATE webauthn_credentials SET enabled = 0 WHERE credential_id = ?", (credential_id,))
            return result.rowcount > 0

    def update_credential_use(self, credential_id: str, sign_count: int) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE webauthn_credentials
                SET sign_count = ?, last_used_at = ?
                WHERE credential_id = ?
                """,
                (sign_count, iso(utc_now()), credential_id),
            )

    def create_action_authorization(self, *, action_id: str, service_id: str | None) -> str:
        now = utc_now()
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO action_authorizations
                    (token, action_id, service_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token, action_id, service_id, iso(now), iso(now + timedelta(seconds=ACTION_AUTH_TTL_SECONDS))),
            )
        return token

    def consume_action_authorization(self, *, token: str, action_id: str, service_id: str | None) -> bool:
        now = utc_now()
        with self.connect() as db:
            row = db.execute(
                """
                SELECT * FROM action_authorizations
                WHERE token = ? AND action_id = ? AND used_at IS NULL
                """,
                (token, action_id),
            ).fetchone()
            if not row or parse_iso(row["expires_at"]) <= now:
                return False
            if row["service_id"] and row["service_id"] != service_id:
                return False
            db.execute("UPDATE action_authorizations SET used_at = ? WHERE token = ?", (iso(now), token))
            return True
