from __future__ import annotations

from .command import run_command


def docker_ps() -> dict[str, dict[str, str]] | None:
    result = run_command(
        ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"],
        timeout=6,
    )
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
    result = run_command(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"],
        timeout=8,
    )
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
    result = run_command(["docker", "inspect", "-f", "{{.RestartCount}}", container], timeout=4)
    if not result or result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def docker_logs(container: str, limit: int) -> tuple[int, str] | None:
    result = run_command(["docker", "logs", "--tail", str(limit), container], timeout=8)
    if not result:
        return None
    combined = "\n".join(part for part in [result.stdout, result.stderr] if part.strip())
    return result.returncode, combined
