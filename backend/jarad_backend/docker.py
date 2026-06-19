from __future__ import annotations

import subprocess

from .command import run_command
from .config import SERVICES


ALLOWED_DOCKER_ACTIONS = {"start", "restart", "stop"}


def allowed_containers() -> set[str]:
    return {service["container"] for service in SERVICES.values()}


def is_allowed_container(container: str) -> bool:
    return container in allowed_containers()


def docker_command(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str] | None:
    if not args:
        return None

    command = args[0]
    if command in ALLOWED_DOCKER_ACTIONS:
        if len(args) != 2 or not is_allowed_container(args[1]):
            return None
    elif command == "logs":
        if (
            len(args) != 5
            or args[1] != "--timestamps"
            or args[2] != "--tail"
            or not args[3].isdigit()
            or not is_allowed_container(args[4])
        ):
            return None
    elif command == "inspect":
        if len(args) != 4 or args[1] != "-f" or args[2] != "{{.RestartCount}}" or not is_allowed_container(args[3]):
            return None
    elif command == "ps":
        if args != ["ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"]:
            return None
    elif command == "stats":
        if args != ["stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"]:
            return None
    else:
        return None

    return run_command(["docker", *args], timeout=timeout)


def docker_ps() -> dict[str, dict[str, str]] | None:
    result = docker_command(["ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"], timeout=6)
    if not result or result.returncode != 0:
        return None

    containers: dict[str, dict[str, str]] = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        name, status, image = parts
        containers[name] = {"status": status, "image": image}
    return containers


def docker_stats() -> dict[str, dict[str, float]]:
    result = docker_command(["stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"], timeout=8)
    if not result or result.returncode != 0:
        return {}

    stats: dict[str, dict[str, float]] = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        name, cpu_raw, mem_raw = parts
        stats[name] = {
            "cpu": parse_percent(cpu_raw),
            "memory": parse_memory_mb(mem_raw.split("/")[0].strip()),
        }
    return stats


def parse_percent(value: str) -> float:
    try:
        return round(float(value.strip().rstrip("%")), 1)
    except ValueError:
        return 0.0


def parse_memory_mb(value: str) -> float:
    units = {"gib": 1024, "mib": 1, "kib": 1 / 1024, "b": 1 / 1024**2}
    raw = value.strip().lower()
    for suffix, multiplier in units.items():
        if raw.endswith(suffix):
            try:
                return round(float(raw.removesuffix(suffix).strip()) * multiplier, 1)
            except ValueError:
                return 0.0
    return 0.0


def docker_restarts(container: str) -> int:
    result = docker_command(["inspect", "-f", "{{.RestartCount}}", container], timeout=4)
    if not result or result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def docker_logs(container: str, limit: int) -> tuple[int, str] | None:
    result = docker_command(["logs", "--timestamps", "--tail", str(limit), container], timeout=8)
    if not result:
        return None
    combined = "\n".join(part for part in [result.stdout, result.stderr] if part.strip())
    return result.returncode, combined


def docker_action(action: str, container: str) -> subprocess.CompletedProcess[str] | None:
    return docker_command([action, container], timeout=20)
