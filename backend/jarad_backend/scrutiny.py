from __future__ import annotations

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
_cached_alerts: list[dict[str, str]] = []


def unavailable_alert(body: str) -> list[dict[str, str]]:
    return [
        {
            "state": "warn",
            "title": "Disk monitoring data unavailable",
            "time": "Active",
            "body": body,
        }
    ]


def safe_device_label(device: dict[str, Any]) -> str:
    for key in ("label", "device_label", "model_name", "device_name"):
        value = device.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:80]
    return "monitored drive"


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


def alerts_from_summary(payload: Any, now: datetime | None = None) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return unavailable_alert("Scrutiny returned an invalid health response.")

    data = payload.get("data")
    summary = data.get("summary") if isinstance(data, dict) else None
    if not isinstance(summary, dict):
        return unavailable_alert("Scrutiny returned an invalid disk summary.")
    if not summary:
        return unavailable_alert("Scrutiny has not reported any disks yet.")

    alerts: list[dict[str, str]] = []
    collector_dates: list[datetime] = []
    active_devices = 0
    missing_collection_count = 0

    for entry in summary.values():
        if not isinstance(entry, dict):
            continue
        device = entry.get("device")
        if not isinstance(device, dict) or device.get("archived") is True:
            continue

        active_devices += 1
        smart = entry.get("smart")
        if isinstance(smart, dict):
            collector_date = parse_collector_date(smart.get("collector_date"))
            if collector_date is not None:
                collector_dates.append(collector_date)
            else:
                missing_collection_count += 1
        else:
            missing_collection_count += 1

        raw_status = device.get("device_status", 0)
        try:
            status = int(raw_status)
        except (TypeError, ValueError):
            return unavailable_alert("Scrutiny returned an invalid disk status.")
        if status == 0:
            continue

        reasons: list[str] = []
        if status & 1:
            reasons.append("SMART reports a failure")
        if status & 2:
            reasons.append("Scrutiny's failure threshold was exceeded")
        if not reasons:
            reasons.append("Scrutiny reports a non-healthy status")

        alerts.append(
            {
                "state": "bad",
                "title": f"Disk health alert: {safe_device_label(device)}",
                "time": "Active",
                "body": f"{'; '.join(reasons)}. Open Scrutiny for the affected attributes and history.",
            }
        )

    if active_devices == 0:
        return unavailable_alert("Scrutiny has no active disks to monitor.")

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

    if collector_dates:
        reference_time = now or datetime.now(timezone.utc)
        oldest_collection = min(collector_dates)
        age_hours = max(0, int((reference_time - oldest_collection).total_seconds() // 3600))
        if age_hours >= SCRUTINY_STALE_HOURS:
            alerts.append(
                {
                    "state": "warn",
                    "title": "Disk health data is stale",
                    "time": "Active",
                    "body": (
                        f"One or more disks were last collected {age_hours} hours ago. "
                        "Check the Scrutiny collector before relying on current health."
                    ),
                }
            )

    return alerts


def fetch_scrutiny_alerts() -> list[dict[str, str]]:
    request = Request(
        SCRUTINY_API_URL,
        headers={"Accept": "application/json", "User-Agent": "Jarad-Backend/1"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError):
        return unavailable_alert("Jarad could not read Scrutiny's local API.")

    if len(body) > MAX_RESPONSE_BYTES:
        return unavailable_alert("Scrutiny's disk summary was unexpectedly large.")

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return unavailable_alert("Scrutiny returned an invalid disk summary.")
    return alerts_from_summary(payload)


def scrutiny_alerts(force: bool = False) -> list[dict[str, str]]:
    global _cache_expires_at, _cached_alerts

    current_time = time.monotonic()
    with _cache_lock:
        if not force and current_time < _cache_expires_at:
            return [dict(alert) for alert in _cached_alerts]

        alerts = fetch_scrutiny_alerts()
        _cached_alerts = [dict(alert) for alert in alerts]
        _cache_expires_at = current_time + CACHE_SECONDS
        return alerts
