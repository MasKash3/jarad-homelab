from __future__ import annotations

import ipaddress
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from .command import run_command
from .config import DB_PATH, DNS_ACCESS_ENABLED, DNS_ACCESS_HELPER, DNS_ACCESS_LAN_SUBNET, DNS_ACCESS_SERVER_IP


VALID_STATUSES = {"pending", "approved", "denied"}
VALID_DURATIONS = {"2h": timedelta(hours=2), "24h": timedelta(hours=24), "permanent": None}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS dns_clients (
                client_ip TEXT PRIMARY KEY,
                hostname TEXT,
                mac_address TEXT,
                status TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                approved_at TEXT,
                approved_until TEXT,
                denied_at TEXT,
                revoked_at TEXT,
                source TEXT NOT NULL DEFAULT 'manual'
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_dns_clients_status ON dns_clients(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_dns_clients_last_seen_at ON dns_clients(last_seen_at)")


def validate_client_ip(client_ip: str) -> str:
    try:
        ip = ipaddress.ip_address(client_ip)
        subnet = ipaddress.ip_network(DNS_ACCESS_LAN_SUBNET, strict=False)
    except ValueError as exc:
        raise ValueError("Invalid client IP or DNS LAN subnet") from exc
    if ip.version != 4:
        raise ValueError("Only IPv4 DNS clients are supported")
    if ip not in subnet:
        raise ValueError("Client IP is outside the configured DNS LAN subnet")
    if str(ip) == DNS_ACCESS_SERVER_IP:
        raise ValueError("DNS server IP cannot be managed as a client")
    return str(ip)


def validate_duration(duration: str) -> str:
    normalized = duration.strip().lower()
    if normalized not in VALID_DURATIONS:
        raise ValueError("Unsupported approval duration")
    return normalized


def record_pending_client(client_ip: str, *, hostname: str | None = None, mac_address: str | None = None, source: str = "detected") -> dict[str, Any]:
    client_ip = validate_client_ip(client_ip)
    now = utc_now()
    with connect() as db:
        existing = db.execute("SELECT * FROM dns_clients WHERE client_ip = ?", (client_ip,)).fetchone()
        if existing:
            db.execute(
                """
                UPDATE dns_clients
                SET hostname = COALESCE(?, hostname),
                    mac_address = COALESCE(?, mac_address),
                    last_seen_at = ?,
                    source = ?
                WHERE client_ip = ?
                """,
                (clean_text(hostname), clean_text(mac_address), iso(now), source, client_ip),
            )
        else:
            db.execute(
                """
                INSERT INTO dns_clients
                    (client_ip, hostname, mac_address, status, first_seen_at, last_seen_at, source)
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (client_ip, clean_text(hostname), clean_text(mac_address), iso(now), iso(now), source),
            )
    return get_client(client_ip) or {}


def approve_client(client_ip: str, duration: str) -> tuple[dict[str, Any], dict[str, Any]]:
    client_ip = validate_client_ip(client_ip)
    duration = validate_duration(duration)
    now = utc_now()
    delta = VALID_DURATIONS[duration]
    approved_until = now + delta if delta else None
    with connect() as db:
        db.execute(
            """
            INSERT INTO dns_clients
                (client_ip, status, first_seen_at, last_seen_at, approved_at, approved_until, source)
            VALUES (?, 'approved', ?, ?, ?, ?, 'manual')
            ON CONFLICT(client_ip) DO UPDATE SET
                status = 'approved',
                last_seen_at = excluded.last_seen_at,
                approved_at = excluded.approved_at,
                approved_until = excluded.approved_until,
                denied_at = NULL,
                revoked_at = NULL
            """,
            (client_ip, iso(now), iso(now), iso(now), iso(approved_until)),
        )
    apply_result = apply_firewall_rules()
    return get_client(client_ip) or {}, apply_result


def deny_client(client_ip: str) -> tuple[dict[str, Any], dict[str, Any]]:
    client_ip = validate_client_ip(client_ip)
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            INSERT INTO dns_clients
                (client_ip, status, first_seen_at, last_seen_at, denied_at, source)
            VALUES (?, 'denied', ?, ?, ?, 'manual')
            ON CONFLICT(client_ip) DO UPDATE SET
                status = 'denied',
                last_seen_at = excluded.last_seen_at,
                denied_at = excluded.denied_at,
                approved_at = NULL,
                approved_until = NULL,
                revoked_at = NULL
            """,
            (client_ip, iso(now), iso(now), iso(now)),
        )
    apply_result = apply_firewall_rules()
    return get_client(client_ip) or {}, apply_result


def revoke_client(client_ip: str) -> tuple[dict[str, Any], dict[str, Any]]:
    client_ip = validate_client_ip(client_ip)
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            UPDATE dns_clients
            SET status = 'pending',
                last_seen_at = ?,
                approved_at = NULL,
                approved_until = NULL,
                revoked_at = ?
            WHERE client_ip = ?
            """,
            (iso(now), iso(now), client_ip),
        )
        if db.total_changes == 0:
            db.execute(
                """
                INSERT INTO dns_clients
                    (client_ip, status, first_seen_at, last_seen_at, revoked_at, source)
                VALUES (?, 'pending', ?, ?, ?, 'manual')
                """,
                (client_ip, iso(now), iso(now), iso(now)),
            )
    apply_result = apply_firewall_rules()
    return get_client(client_ip) or {}, apply_result


def list_clients() -> dict[str, Any]:
    expire_clients()
    detected = collect_detected_clients()
    now = utc_now()
    with connect() as db:
        rows = db.execute("SELECT * FROM dns_clients ORDER BY last_seen_at DESC").fetchall()
    clients = [serialize_client(row, now) for row in rows]
    return {
        "enabled": DNS_ACCESS_ENABLED,
        "lanSubnet": DNS_ACCESS_LAN_SUBNET,
        "serverIp": DNS_ACCESS_SERVER_IP,
        "helper": DNS_ACCESS_HELPER,
        "detected": detected,
        "clients": clients,
        "summary": {
            "pending": sum(1 for client in clients if client["effectiveStatus"] == "pending"),
            "approved": sum(1 for client in clients if client["effectiveStatus"] == "approved"),
            "denied": sum(1 for client in clients if client["effectiveStatus"] == "denied"),
            "expired": sum(1 for client in clients if client["effectiveStatus"] == "expired"),
        },
    }


def approved_client_ips() -> list[str]:
    expire_clients()
    now = utc_now()
    with connect() as db:
        rows = db.execute(
            """
            SELECT client_ip FROM dns_clients
            WHERE status = 'approved'
              AND (approved_until IS NULL OR approved_until > ?)
            ORDER BY client_ip
            """,
            (iso(now),),
        ).fetchall()
    return [row["client_ip"] for row in rows]


def expire_clients() -> None:
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            UPDATE dns_clients
            SET status = 'pending', approved_at = NULL, revoked_at = COALESCE(revoked_at, ?)
            WHERE status = 'approved'
              AND approved_until IS NOT NULL
              AND approved_until <= ?
            """,
            (iso(now), iso(now)),
        )


def get_client(client_ip: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM dns_clients WHERE client_ip = ?", (client_ip,)).fetchone()
    return serialize_client(row, utc_now()) if row else None


def collect_detected_clients() -> dict[str, Any]:
    if not DNS_ACCESS_ENABLED:
        return {"enabled": False, "processed": 0, "error": None}
    result = run_command([DNS_ACCESS_HELPER, "detect"], timeout=5)
    if result is None:
        return {"enabled": True, "processed": 0, "error": "DNS access helper unavailable"}
    if result.returncode != 0:
        return {"enabled": True, "processed": 0, "error": result.stderr.strip() or "DNS detection failed"}
    processed = 0
    try:
        clients = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return {"enabled": True, "processed": 0, "error": "DNS detection returned invalid JSON"}
    for item in clients if isinstance(clients, list) else []:
        if not isinstance(item, dict) or not item.get("clientIp"):
            continue
        try:
            record_pending_client(
                str(item["clientIp"]),
                hostname=item.get("hostname"),
                mac_address=item.get("macAddress"),
                source="firewall",
            )
            processed += 1
        except ValueError:
            continue
    return {"enabled": True, "processed": processed, "error": None}


def apply_firewall_rules() -> dict[str, Any]:
    allowed_ips = approved_client_ips()
    if not DNS_ACCESS_ENABLED:
        return {"enabled": False, "applied": False, "allowedIps": allowed_ips, "detail": "DNS access enforcement is disabled"}
    payload = json.dumps(
        {
            "lanSubnet": DNS_ACCESS_LAN_SUBNET,
            "serverIp": DNS_ACCESS_SERVER_IP,
            "allowedIps": allowed_ips,
        }
    )
    result = run_command([DNS_ACCESS_HELPER, "apply", payload], timeout=10)
    if result is None:
        return {"enabled": True, "applied": False, "allowedIps": allowed_ips, "detail": "DNS access helper unavailable"}
    if result.returncode != 0:
        return {
            "enabled": True,
            "applied": False,
            "allowedIps": allowed_ips,
            "detail": result.stderr.strip() or "DNS access helper failed",
        }
    return {"enabled": True, "applied": True, "allowedIps": allowed_ips, "detail": (result.stdout or "").strip()}


def serialize_client(row: sqlite3.Row, now: datetime) -> dict[str, Any]:
    approved_until = parse_iso(row["approved_until"])
    expired = row["status"] == "approved" and approved_until is not None and approved_until <= now
    effective_status = "expired" if expired else row["status"]
    return {
        "clientIp": row["client_ip"],
        "hostname": row["hostname"],
        "macAddress": row["mac_address"],
        "status": row["status"],
        "effectiveStatus": effective_status,
        "firstSeenAt": row["first_seen_at"],
        "lastSeenAt": row["last_seen_at"],
        "approvedAt": row["approved_at"],
        "approvedUntil": row["approved_until"],
        "deniedAt": row["denied_at"],
        "revokedAt": row["revoked_at"],
        "source": row["source"],
        "expiresInSeconds": max(0, int((approved_until - now).total_seconds())) if approved_until else None,
    }


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9_.: -]", "", str(value)).strip()
    return cleaned[:120] or None


init()
