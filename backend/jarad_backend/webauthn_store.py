from __future__ import annotations

import secrets
import sqlite3
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import BROWSER_SESSION_TTL_MINUTES, DB_PATH, DEVICE_TOKEN_TTL_DAYS
from .file_security import ensure_owner_only_file


CHALLENGE_TTL_SECONDS = 180
ACTION_AUTH_TTL_SECONDS = 60


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def hash_action_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


class WebAuthnStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.init()

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        ensure_owner_only_file(self.db_path)
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
                    actor_id TEXT,
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
                    actor_id TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                )
                """
            )
            self.ensure_webauthn_security_columns(db)
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    audit_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action_id TEXT,
                    service_id TEXT,
                    credential_id TEXT,
                    remote_addr TEXT,
                    user_agent TEXT,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_event_type ON audit_events(event_type)")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS device_tokens (
                    device_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    device_label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    revoked_at TEXT,
                    expires_at TEXT,
                    rotated_at TEXT,
                    remote_addr TEXT,
                    user_agent TEXT
                )
                """
            )
            self.ensure_device_token_columns(db)
            db.execute("CREATE INDEX IF NOT EXISTS idx_device_tokens_token_hash ON device_tokens(token_hash)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_device_tokens_created_at ON device_tokens(created_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_device_tokens_expires_at ON device_tokens(expires_at)")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS browser_sessions (
                    session_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    device_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    remote_addr TEXT,
                    user_agent TEXT,
                    FOREIGN KEY(device_id) REFERENCES device_tokens(device_id)
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_browser_sessions_token_hash ON browser_sessions(token_hash)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_browser_sessions_device_id ON browser_sessions(device_id)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_browser_sessions_expires_at ON browser_sessions(expires_at)")
            self.cleanup_expired_auth_rows(db)

    def ensure_webauthn_security_columns(self, db: sqlite3.Connection) -> None:
        challenge_columns = {row["name"] for row in db.execute("PRAGMA table_info(webauthn_challenges)").fetchall()}
        if "actor_id" not in challenge_columns:
            db.execute("ALTER TABLE webauthn_challenges ADD COLUMN actor_id TEXT")
        authorization_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(action_authorizations)").fetchall()
        }
        if "actor_id" not in authorization_columns:
            db.execute("ALTER TABLE action_authorizations ADD COLUMN actor_id TEXT")

    def ensure_device_token_columns(self, db: sqlite3.Connection) -> None:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(device_tokens)").fetchall()}
        now = utc_now()
        default_expiry = iso(now + timedelta(days=DEVICE_TOKEN_TTL_DAYS))
        if "expires_at" not in columns:
            db.execute("ALTER TABLE device_tokens ADD COLUMN expires_at TEXT")
            db.execute("UPDATE device_tokens SET expires_at = ? WHERE expires_at IS NULL", (default_expiry,))
        if "rotated_at" not in columns:
            db.execute("ALTER TABLE device_tokens ADD COLUMN rotated_at TEXT")
        db.execute("UPDATE device_tokens SET expires_at = ? WHERE expires_at IS NULL", (default_expiry,))

    def create_challenge(
        self,
        *,
        challenge: bytes,
        purpose: str,
        user_handle: str | None = None,
        action_id: str | None = None,
        service_id: str | None = None,
        actor_id: str,
    ) -> str:
        now = utc_now()
        challenge_id = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO webauthn_challenges
                    (challenge_id, challenge, purpose, user_handle, action_id, service_id, actor_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    challenge_id,
                    challenge,
                    purpose,
                    user_handle,
                    action_id,
                    service_id,
                    actor_id,
                    iso(now),
                    iso(now + timedelta(seconds=CHALLENGE_TTL_SECONDS)),
                ),
            )
        return challenge_id

    def consume_challenge(self, challenge_id: str, purpose: str, actor_id: str) -> dict[str, Any] | None:
        now = utc_now()
        now_iso = iso(now)
        with self.connect() as db:
            row = db.execute(
                """
                SELECT * FROM webauthn_challenges
                WHERE challenge_id = ? AND purpose = ? AND actor_id = ? AND used_at IS NULL
                """,
                (challenge_id, purpose, actor_id),
            ).fetchone()
            if not row or parse_iso(row["expires_at"]) <= now:
                return None
            result = db.execute(
                """
                UPDATE webauthn_challenges
                SET used_at = ?
                WHERE challenge_id = ?
                  AND purpose = ?
                  AND actor_id = ?
                  AND used_at IS NULL
                  AND expires_at > ?
                """,
                (now_iso, challenge_id, purpose, actor_id, now_iso),
            )
            if result.rowcount != 1:
                return None
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

    def create_action_authorization(self, *, action_id: str, service_id: str | None, actor_id: str) -> str:
        now = utc_now()
        token = secrets.token_urlsafe(32)
        token_hash = hash_action_token(token)
        with self.connect() as db:
            self.cleanup_expired_auth_rows(db)
            db.execute(
                """
                INSERT INTO action_authorizations
                    (token, action_id, service_id, actor_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token_hash, action_id, service_id, actor_id, iso(now), iso(now + timedelta(seconds=ACTION_AUTH_TTL_SECONDS))),
            )
        return token

    def consume_action_authorization(
        self, *, token: str, action_id: str, service_id: str | None, actor_id: str
    ) -> bool:
        now = utc_now()
        now_iso = iso(now)
        token_hash = hash_action_token(token)
        with self.connect() as db:
            result = db.execute(
                """
                UPDATE action_authorizations
                SET used_at = ?
                WHERE token = ?
                  AND action_id = ?
                  AND actor_id = ?
                  AND used_at IS NULL
                  AND expires_at > ?
                  AND ((service_id IS NULL AND ? IS NULL) OR service_id = ?)
                """,
                (now_iso, token_hash, action_id, actor_id, now_iso, service_id, service_id),
            )
            return result.rowcount == 1

    def cleanup_expired_auth_rows(self, db: sqlite3.Connection) -> None:
        now = iso(utc_now())
        db.execute("DELETE FROM webauthn_challenges WHERE expires_at <= ?", (now,))
        db.execute("DELETE FROM action_authorizations WHERE expires_at <= ?", (now,))

    def add_audit_event(
        self,
        *,
        event_type: str,
        outcome: str,
        actor: str,
        action_id: str | None = None,
        service_id: str | None = None,
        credential_id: str | None = None,
        remote_addr: str | None = None,
        user_agent: str | None = None,
        details_json: str = "{}",
    ) -> str:
        audit_id = secrets.token_urlsafe(18)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO audit_events
                    (
                        audit_id, event_type, outcome, actor, action_id, service_id,
                        credential_id, remote_addr, user_agent, details_json, created_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    event_type,
                    outcome,
                    actor,
                    action_id,
                    service_id,
                    credential_id,
                    remote_addr,
                    user_agent,
                    details_json,
                    iso(utc_now()),
                ),
            )
        return audit_id

    def create_device_token(
        self,
        *,
        token_hash: str,
        device_label: str,
        remote_addr: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        now_dt = utc_now()
        now = iso(now_dt)
        expires_at = iso(now_dt + timedelta(days=DEVICE_TOKEN_TTL_DAYS))
        device_id = secrets.token_urlsafe(18)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO device_tokens
                    (device_id, token_hash, device_label, created_at, expires_at, remote_addr, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (device_id, token_hash, device_label, now, expires_at, remote_addr, user_agent),
            )
        return {
            "device_id": device_id,
            "device_label": device_label,
            "created_at": now,
            "last_used_at": None,
            "revoked_at": None,
            "expires_at": expires_at,
            "rotated_at": None,
            "remote_addr": remote_addr,
            "user_agent": user_agent,
        }

    def get_active_device_token(self, token_hash: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as db:
            row = db.execute(
                """
                SELECT * FROM device_tokens
                WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > ?
                """,
                (token_hash, iso(now)),
            ).fetchone()
            if not row:
                return None
            db.execute("UPDATE device_tokens SET last_used_at = ? WHERE device_id = ?", (iso(now), row["device_id"]))
            return dict(row)

    def create_browser_session(
        self,
        *,
        device_id: str,
        token_hash: str,
        remote_addr: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        now_dt = utc_now()
        now = iso(now_dt)
        expires_at = iso(now_dt + timedelta(minutes=BROWSER_SESSION_TTL_MINUTES))
        session_id = secrets.token_urlsafe(18)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO browser_sessions
                    (session_id, token_hash, device_id, created_at, expires_at, remote_addr, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, token_hash, device_id, now, expires_at, remote_addr, user_agent),
            )
        return {
            "session_id": session_id,
            "device_id": device_id,
            "created_at": now,
            "last_used_at": None,
            "expires_at": expires_at,
            "revoked_at": None,
            "remote_addr": remote_addr,
            "user_agent": user_agent,
        }

    def get_active_browser_session(self, token_hash: str) -> dict[str, Any] | None:
        now = utc_now()
        now_iso = iso(now)
        with self.connect() as db:
            row = db.execute(
                """
                SELECT
                    browser_sessions.*,
                    device_tokens.device_label
                FROM browser_sessions
                JOIN device_tokens ON browser_sessions.device_id = device_tokens.device_id
                WHERE
                    browser_sessions.token_hash = ?
                    AND browser_sessions.revoked_at IS NULL
                    AND browser_sessions.expires_at > ?
                    AND device_tokens.revoked_at IS NULL
                    AND device_tokens.expires_at > ?
                """,
                (token_hash, now_iso, now_iso),
            ).fetchone()
            if not row:
                return None
            db.execute("UPDATE browser_sessions SET last_used_at = ? WHERE session_id = ?", (now_iso, row["session_id"]))
            db.execute("UPDATE device_tokens SET last_used_at = ? WHERE device_id = ?", (now_iso, row["device_id"]))
            return dict(row)

    def revoke_browser_sessions_for_device(self, device_id: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE browser_sessions
                SET revoked_at = ?
                WHERE device_id = ? AND revoked_at IS NULL
                """,
                (iso(utc_now()), device_id),
            )

    def has_active_device_tokens(self) -> bool:
        now = iso(utc_now())
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM device_tokens WHERE revoked_at IS NULL AND expires_at > ? LIMIT 1",
                (now,),
            ).fetchone()
            return bool(row)

    def list_device_tokens(self, include_revoked: bool = False) -> list[dict[str, Any]]:
        where_clause = "" if include_revoked else "WHERE revoked_at IS NULL AND expires_at > ?"
        params: tuple[Any, ...] = () if include_revoked else (iso(utc_now()),)
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    f"""
                    SELECT
                        device_id, device_label, created_at, last_used_at,
                        revoked_at, expires_at, rotated_at, remote_addr, user_agent
                    FROM device_tokens
                    {where_clause}
                    ORDER BY revoked_at IS NOT NULL, last_used_at DESC, created_at DESC
                    """,
                    params,
                ).fetchall()
            ]

    def revoke_device_token(self, device_id: str) -> bool:
        with self.connect() as db:
            now = iso(utc_now())
            result = db.execute(
                """
                UPDATE device_tokens
                SET revoked_at = ?
                WHERE device_id = ? AND revoked_at IS NULL
                """,
                (now, device_id),
            )
            if result.rowcount > 0:
                db.execute(
                    """
                    UPDATE browser_sessions
                    SET revoked_at = ?
                    WHERE device_id = ? AND revoked_at IS NULL
                    """,
                    (now, device_id),
                )
            return result.rowcount > 0

    def rotate_device_token(
        self,
        *,
        device_id: str,
        token_hash: str,
        remote_addr: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any] | None:
        now_dt = utc_now()
        now = iso(now_dt)
        expires_at = iso(now_dt + timedelta(days=DEVICE_TOKEN_TTL_DAYS))
        new_device_id = secrets.token_urlsafe(18)
        with self.connect() as db:
            current = db.execute(
                """
                SELECT * FROM device_tokens
                WHERE device_id = ? AND revoked_at IS NULL AND expires_at > ?
                """,
                (device_id, now),
            ).fetchone()
            if not current:
                return None
            db.execute(
                """
                UPDATE device_tokens
                SET revoked_at = ?, rotated_at = ?
                WHERE device_id = ? AND revoked_at IS NULL
                """,
                (now, now, device_id),
            )
            db.execute(
                """
                UPDATE browser_sessions
                SET revoked_at = ?
                WHERE device_id = ? AND revoked_at IS NULL
                """,
                (now, device_id),
            )
            db.execute(
                """
                INSERT INTO device_tokens
                    (device_id, token_hash, device_label, created_at, expires_at, remote_addr, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_device_id,
                    token_hash,
                    current["device_label"],
                    now,
                    expires_at,
                    remote_addr,
                    user_agent,
                ),
            )
        return {
            "device_id": new_device_id,
            "device_label": current["device_label"],
            "created_at": now,
            "last_used_at": None,
            "revoked_at": None,
            "expires_at": expires_at,
            "rotated_at": None,
            "remote_addr": remote_addr,
            "user_agent": user_agent,
        }
