from __future__ import annotations

import platform
import socket
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import require_token, verify_action_auth, verify_totp
from .command import run_command
from .config import LAN_IP, PUBLIC_HOST, SERVICES, TOTP_SECRET
from .docker import docker_logs
from .metrics import read_backup_state, read_cpu_pct, read_disk, read_raid_state, read_ram_pct, read_temp_c, read_uptime
from .models import ActionRequest, TotpCheckRequest
from .services import alerts_for, build_services, network_state, recent_logs

router = APIRouter()
protected = [Depends(require_token)]


def diagnostic_state(value: str) -> str:
    text = value.lower()
    fail_terms = ("stopped", "failed", "unavailable", "error", "not running")
    warn_terms = ("degraded", "warning", "elevated", "unchecked", "unknown")
    if any(term in text for term in fail_terms):
        return "fail"
    if any(term in text for term in warn_terms):
        return "warn"
    return "pass"


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "host": socket.gethostname()}


@router.post("/api/auth/totp/check", dependencies=protected)
def check_totp(payload: TotpCheckRequest) -> dict[str, Any]:
    configured = bool(TOTP_SECRET)
    valid = verify_totp(payload.code) if configured else False
    return {
        "configured": configured,
        "valid": valid,
        "serverTime": datetime.now(timezone.utc).isoformat(),
        "codeWindowSeconds": 30,
    }


@router.get("/api/mobile/state", dependencies=protected)
def mobile_state() -> dict[str, Any]:
    disk_pct, disk_label = read_disk()
    backup = read_backup_state()
    services = build_services()
    temp = read_temp_c()
    metrics = [
        {"label": "CPU", "value": read_cpu_pct(), "unit": "%", "state": "good"},
        {"label": "RAM", "value": read_ram_pct(), "unit": "%", "state": "good"},
        {
            "label": "Disk",
            "value": disk_pct,
            "unit": "%",
            "state": "warn" if disk_pct >= 70 else "good",
            "badge": f"{disk_pct}% used",
        },
        {"label": "Temp", "value": temp, "unit": "C", "state": "warn" if temp >= 70 else "good"},
    ]

    down_count = sum(1 for service in services if service["health"] == "down")
    degraded_count = sum(1 for service in services if service["health"] == "degraded")
    status = "Operational" if down_count == 0 and degraded_count == 0 else "Attention needed"
    score = max(0, 100 - (down_count * 20) - (degraded_count * 8))

    return {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "server": {
            "name": "Jarad",
            "host": PUBLIC_HOST,
            "lan": LAN_IP,
            "uptime": read_uptime(),
            "healthScore": score,
            "status": status,
            "platform": platform.platform(),
        },
        "metrics": metrics,
        "storage": {
            "usedPct": disk_pct,
            "label": disk_label,
            "cloudBackup": backup.get("cloud", "Cloud backup unchecked"),
            "raid": read_raid_state(),
        },
        "backups": backup,
        "services": services,
        "logs": recent_logs(),
        "alerts": alerts_for(services, disk_pct, backup["state"]),
        "network": network_state(),
    }


@router.get("/api/services/{service_id}/logs", dependencies=protected)
def service_logs(service_id: str, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    service = SERVICES.get(service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Unknown service")
    result = docker_logs(service["container"], limit)
    if not result:
        return {
            "service": service_id,
            "logs": [
                {
                    "level": "error",
                    "time": "Recent",
                    "message": "Docker logs unavailable from backend environment",
                }
            ],
        }

    returncode, combined = result
    if returncode != 0:
        return {
            "service": service_id,
            "logs": [
                {
                    "level": "error",
                    "time": "Recent",
                    "message": combined.strip() or f"docker logs failed for {service['container']}",
                }
            ],
        }
    return {
        "service": service_id,
        "logs": [
            {"level": "error" if "error" in line.lower() else "info", "time": "Recent", "message": line}
            for line in combined.splitlines()[-limit:]
        ],
    }


@router.get("/api/services/{service_id}/diagnostics", dependencies=protected)
def service_diagnostics(service_id: str) -> dict[str, Any]:
    service = next((item for item in build_services() if item["id"] == service_id), None)
    if not service:
        raise HTTPException(status_code=404, detail="Unknown service")
    return {
        "service": service_id,
        "checks": [
            {"label": label, "state": diagnostic_state(value), "detail": value}
            for label, value in service["diagnostics"]
        ],
        "suggestedFix": None if service["health"] == "healthy" else "Open service logs and verify container dependencies.",
    }


@router.post("/api/admin/actions/{action_id}", dependencies=protected)
def service_action(action_id: str, payload: ActionRequest) -> dict[str, Any]:
    action, service_id = split_action(action_id)
    service = SERVICES.get(service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Unknown service")
    if action not in {"start", "restart", "stop"}:
        raise HTTPException(status_code=400, detail="Unsupported action")
    verify_action_auth(payload)

    result = run_command(["docker", action, service["container"]], timeout=20)
    if not result or result.returncode != 0:
        detail = result.stderr.strip() if result else "Docker command unavailable"
        raise HTTPException(status_code=500, detail=detail)
    refreshed = next((item for item in build_services() if item["id"] == service_id), None)
    return {
        "status": "accepted",
        "action": action,
        "service": service_id,
        "target": service["container"],
        "source": payload.source,
        "current": refreshed,
    }


def split_action(action_id: str) -> tuple[str, str]:
    for action in ("restart", "start", "stop"):
        prefix = f"{action}-"
        if action_id.startswith(prefix):
            return action, action_id.removeprefix(prefix)
    raise HTTPException(status_code=400, detail="Unsupported action id")
