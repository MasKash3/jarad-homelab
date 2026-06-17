from __future__ import annotations

import socket
from typing import Any

from .command import run_command
from .config import BACKUP_LOG, DATA_MOUNT, DNS_SERVER, PUBLIC_HOST, SERVICES
from .docker import docker_ps, docker_restarts, docker_stats


def build_services() -> list[dict[str, Any]]:
    containers = docker_ps()
    stats = docker_stats()
    services: list[dict[str, Any]] = []

    for service_id, meta in SERVICES.items():
        container = meta["container"]
        docker_info = containers.get(container) if containers is not None else None
        stat = stats.get(container, {})
        docker_unavailable = containers is None
        running = bool(docker_info and docker_info["status"].lower().startswith("up"))
        health = "degraded" if docker_unavailable else "healthy" if running else "down"
        last_error = (
            "Docker unavailable"
            if docker_unavailable
            else "No recent errors"
            if running
            else "Container not running"
        )

        if service_id == "pihole" and running and not dns_ok():
            health = "degraded"
            last_error = "DNS probe failed"

        memory = round(float(stat.get("memory", 0)))
        resources: dict[str, float | int | None] = {
            "cpu": round(float(stat.get("cpu", 0))),
            "memory": memory,
            "memoryLimit": max(memory, 512),
            "disk": None,
            "diskLimit": None,
        }

        services.append(
            {
                "id": service_id,
                **meta,
                "status": "unknown" if docker_unavailable else "running" if running else "stopped",
                "health": health,
                "restarts": docker_restarts(container) if docker_info else 0,
                "cpu": round(float(stat.get("cpu", 0))),
                "ram": memory,
                "lastError": last_error,
                "diagnostics": diagnostics_for(service_id, running, health, docker_unavailable),
                "resources": resources,
            }
        )

    return services


def diagnostics_for(service_id: str, running: bool, health: str, docker_unavailable: bool) -> list[list[str]]:
    checks = [
        ["Container", "Docker unavailable" if docker_unavailable else "Running" if running else "Stopped"],
        ["Health", health.title()],
        ["Restart policy", "Docker managed"],
        ["Recent errors", "Docker CLI unavailable" if docker_unavailable else "None" if running else "Container unavailable"],
    ]
    if service_id == "pihole":
        checks.insert(2, ["DNS test", "Pass" if dns_ok() else "Failed"])
    return checks


def dns_ok() -> bool:
    result = run_command(["nslookup", "cloudflare.com", DNS_SERVER], timeout=4)
    return bool(result and result.returncode == 0)


def recent_logs(limit: int = 80) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if BACKUP_LOG.exists():
        for line in BACKUP_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]:
            level = "error" if "error" in line.lower() or "failed" in line.lower() else "info"
            rows.append({"level": level, "service": "backup", "time": "Recent", "message": line[-180:]})

    if not rows:
        rows.append(
            {
                "level": "info",
                "service": "backend",
                "time": "Now",
                "message": "Backend online; no server logs available in this environment",
            }
        )
    return rows[-limit:]


def network_state() -> list[list[str]]:
    return [
        ["DNS", "OK" if dns_ok() else "Degraded"],
        ["Gateway", "Unchecked"],
        ["Private network", "Configured" if PUBLIC_HOST else "Unknown"],
        ["Host", socket.gethostname()],
    ]


def alerts_for(services: list[dict[str, Any]], disk_pct: int, backup_state: str) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    for service in services:
        if service["health"] == "down":
            alerts.append(
                {
                    "state": "bad",
                    "title": f"{service['name']} is down",
                    "time": "Active",
                    "body": service["lastError"],
                }
            )
        elif service["health"] == "degraded":
            alerts.append(
                {
                    "state": "warn",
                    "title": f"{service['name']} degraded",
                    "time": "Active",
                    "body": service["lastError"],
                }
            )

    if disk_pct >= 85:
        alerts.append(
            {
                "state": "warn",
                "title": "High disk usage",
                "time": "Active",
                "body": f"{DATA_MOUNT} is at {disk_pct}%.",
            }
        )
    if backup_state != "Healthy":
        alerts.append(
            {
                "state": "warn",
                "title": "Backup state unknown",
                "time": "Active",
                "body": "Check backup log and Cloud backup sync status.",
            }
        )
    if not alerts:
        alerts.append(
            {
                "state": "good",
                "title": "All monitored services healthy",
                "time": "Now",
                "body": "No active alerts from the backend.",
            }
        )
    return alerts
