from __future__ import annotations

from copy import deepcopy
import json
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen

from .config import SCRUTINY_API_URL, SCRUTINY_STALE_HOURS

MAX_RESPONSE_BYTES = 1024 * 1024
CACHE_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = 2

_cache_lock = threading.Lock()
_cache_expires_at = 0.0
_cached_snapshot: dict[str, Any] = {}


def unavailable_alert(body: str) -> list[dict[str, str]]:
    return [
        {
            "state": "warn",
            "title": "Disk monitoring data unavailable",
            "time": "Active",
            "body": body,
        }
    ]


def unavailable_snapshot(body: str) -> dict[str, Any]:
    return {
        "available": False,
        "state": "warn",
        "message": body,
        "summary": {"healthy": 0, "warning": 0, "critical": 0},
        "items": [],
        "alerts": unavailable_alert(body),
    }


def clean_text(value: Any, limit: int = 80) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def safe_device_label(device: dict[str, Any]) -> str:
    for key in ("label", "device_label", "model_name", "device_name"):
        value = clean_text(device.get(key))
        if value:
            return value
    return "monitored drive"


def optional_int(value: Any, *, minimum: int | None = None) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None and parsed < minimum:
        return None
    return parsed


def parse_collector_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def snapshot_from_summary(payload: Any, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return unavailable_snapshot("Scrutiny returned an invalid health response.")

    data = payload.get("data")
    summary = data.get("summary") if isinstance(data, dict) else None
    if not isinstance(summary, dict):
        return unavailable_snapshot("Scrutiny returned an invalid disk summary.")
    if not summary:
        return unavailable_snapshot("Scrutiny has not reported any disks yet.")

    alerts: list[dict[str, str]] = []
    drives: list[dict[str, Any]] = []
    missing_collection_count = 0
    stale_collection_count = 0
    reference_time = now or datetime.now(timezone.utc)

    for entry in summary.values():
        if not isinstance(entry, dict):
            continue
        device = entry.get("device")
        if not isinstance(device, dict) or device.get("archived") is True:
            continue

        smart = entry.get("smart")
        collector_date = None
        temperature_c = None
        power_on_hours = None
        if isinstance(smart, dict):
            collector_date = parse_collector_date(smart.get("collector_date"))
            temperature_c = optional_int(smart.get("temp"))
            power_on_hours = optional_int(smart.get("power_on_hours"), minimum=0)
        if collector_date is None:
            missing_collection_count += 1
            age_hours = None
        else:
            age_hours = max(0, int((reference_time - collector_date).total_seconds() // 3600))

        raw_status = device.get("device_status", 0)
        try:
            status = int(raw_status)
        except (TypeError, ValueError):
            return unavailable_snapshot("Scrutiny returned an invalid disk status.")

        reasons: list[str] = []
        if status & 1:
            reasons.append("SMART reports a failure")
        if status & 2:
            reasons.append("Scrutiny's failure threshold was exceeded")
        if status != 0 and not reasons:
            reasons.append("Scrutiny reports a non-healthy status")

        stale = age_hours is not None and age_hours >= SCRUTINY_STALE_HOURS
        if stale:
            stale_collection_count += 1

        if status != 0:
            drive_state = "bad"
            if status & 1 and status & 2:
                status_label = "SMART + Scrutiny failure"
            elif status & 1:
                status_label = "SMART failure"
            elif status & 2:
                status_label = "Scrutiny threshold"
            else:
                status_label = "Needs attention"
        elif collector_date is None:
            drive_state = "warn"
            status_label = "Awaiting data"
        elif stale:
            drive_state = "warn"
            status_label = "Data stale"
        else:
            drive_state = "good"
            status_label = "Healthy"

        label = safe_device_label(device)
        drives.append(
            {
                "label": label,
                "deviceName": clean_text(device.get("device_name")),
                "model": clean_text(device.get("model_name")),
                "interface": clean_text(device.get("device_protocol") or device.get("interface_type"), 24),
                "capacityBytes": optional_int(device.get("capacity"), minimum=0),
                "temperatureC": temperature_c,
                "powerOnHours": power_on_hours,
                "lastCollectedAt": (
                    collector_date.isoformat().replace("+00:00", "Z") if collector_date is not None else None
                ),
                "state": drive_state,
                "statusLabel": status_label,
            }
        )

        if status != 0:
            alerts.append(
                {
                    "state": "bad",
                    "title": f"Disk health alert: {label}",
                    "time": "Active",
                    "body": f"{'; '.join(reasons)}. Open Scrutiny for the affected attributes and history.",
                }
            )

    if not drives:
        return unavailable_snapshot("Scrutiny has no active disks to monitor.")

    if missing_collection_count:
        alerts.append(
            {
                "state": "warn",
                "title": "Disk health collection incomplete",
                "time": "Active",
                "body": (
                    f"{missing_collection_count} monitored disk"
                    f"{'s have' if missing_collection_count != 1 else ' has'} no valid collection timestamp. "
                    "Check the Scrutiny collector before relying on current health."
                ),
            }
        )

    if stale_collection_count:
        alerts.append(
            {
                "state": "warn",
                "title": "Disk health data is stale",
                "time": "Active",
                "body": (
                    f"{stale_collection_count} monitored disk"
                    f"{'s have' if stale_collection_count != 1 else ' has'} stale data. "
                    "Check the Scrutiny collector before relying on current health."
                ),
            }
        )

    drives.sort(key=lambda drive: (drive["deviceName"], drive["label"]))
    counts = {
        "healthy": sum(1 for drive in drives if drive["state"] == "good"),
        "warning": sum(1 for drive in drives if drive["state"] == "warn"),
        "critical": sum(1 for drive in drives if drive["state"] == "bad"),
    }
    overall_state = "bad" if counts["critical"] else "warn" if counts["warning"] else "good"
    attention_count = counts["critical"] + counts["warning"]
    message = (
        f"{attention_count} of {len(drives)} monitored drives "
        f"{'needs' if attention_count == 1 else 'need'} attention."
        if attention_count
        else f"All {len(drives)} monitored drives are healthy."
    )
    return {
        "available": True,
        "state": overall_state,
        "message": message,
        "summary": counts,
        "items": drives,
        "alerts": alerts,
    }


def alerts_from_summary(payload: Any, now: datetime | None = None) -> list[dict[str, str]]:
    return snapshot_from_summary(payload, now)["alerts"]


def fetch_scrutiny_snapshot() -> dict[str, Any]:
    request = Request(
        SCRUTINY_API_URL,
        headers={"Accept": "application/json", "User-Agent": "Jarad-Backend/1"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError):
        return unavailable_snapshot("Jarad could not read Scrutiny's local API.")

    if len(body) > MAX_RESPONSE_BYTES:
        return unavailable_snapshot("Scrutiny's disk summary was unexpectedly large.")

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return unavailable_snapshot("Scrutiny returned an invalid disk summary.")
    return snapshot_from_summary(payload)


def scrutiny_snapshot(force: bool = False) -> dict[str, Any]:
    global _cache_expires_at, _cached_snapshot

    current_time = time.monotonic()
    with _cache_lock:
        if not force and current_time < _cache_expires_at:
            return deepcopy(_cached_snapshot)

        snapshot = fetch_scrutiny_snapshot()
        _cached_snapshot = deepcopy(snapshot)
        _cache_expires_at = current_time + CACHE_SECONDS
        return snapshot


def fetch_scrutiny_alerts() -> list[dict[str, str]]:
    return fetch_scrutiny_snapshot()["alerts"]


def scrutiny_alerts(force: bool = False) -> list[dict[str, str]]:
    return scrutiny_snapshot(force)["alerts"]
