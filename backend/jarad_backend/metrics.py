from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .config import BACKUP_LOG, DATA_MOUNT
from .logtail import tail_lines


def read_uptime() -> str:
    try:
        seconds = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (FileNotFoundError, ValueError, IndexError):
        return "Development mode"

    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    if days:
        return f"{days} days, {hours} hours"
    return f"{hours} hours"


def read_ram_pct() -> int:
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0])
        total = values["MemTotal"]
        available = values["MemAvailable"]
        return round((1 - available / total) * 100)
    except (FileNotFoundError, KeyError, ValueError):
        return 0


def read_cpu_pct() -> int:
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    cpus = os.cpu_count() or 1
    return min(100, round((load / cpus) * 100))


def read_temp_c() -> int:
    for temp_file in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = int(temp_file.read_text(encoding="utf-8").strip())
            if value > 1000:
                value = round(value / 1000)
            if 0 < value < 120:
                return value
        except (OSError, ValueError):
            continue
    return 0


def read_disk() -> tuple[int, str]:
    target = DATA_MOUNT if DATA_MOUNT.exists() else Path.cwd()
    usage = shutil.disk_usage(target)
    used_pct = round((usage.used / usage.total) * 100)
    used_tb = usage.used / 1024**4
    total_tb = usage.total / 1024**4
    return used_pct, f"{used_tb:.2f} TB used of {total_tb:.2f} TB"


def read_raid_state() -> str:
    mdstat = Path("/proc/mdstat")
    if not mdstat.exists():
        return "RAID unavailable"
    text = mdstat.read_text(encoding="utf-8", errors="ignore")
    if "[UU]" in text:
        return "RAID clean"
    if "_U" in text or "U_" in text:
        return "RAID degraded"
    return "RAID check"


def read_backup_state() -> dict[str, str]:
    if not BACKUP_LOG.exists():
        return {
            "state": "Unknown",
            "quick": "No log",
            "full": "No log",
            "cloud": "No log",
            "next": "Cron schedule",
        }

    lines = tail_lines(BACKUP_LOG, 200)
    quick = latest_matching(lines, ("Quick backup complete", "Quick backup completed"))
    full = latest_matching(lines, ("Full backup complete", "Full backup completed"))
    photos = latest_matching(lines, ("Photos backup complete", "Photos backup completed"))
    latest_start = latest_matching_with_index(lines, ("Quick backup started", "Full backup started"))
    latest_done = latest_matching_with_index(lines, ("Quick backup complete", "Quick backup completed", "Full backup complete", "Full backup completed", "Photos backup complete", "Photos backup completed"))
    failed = any("ERROR" in line or "failed" in line.lower() for line in lines[-30:])
    has_completion = bool(quick or full or photos)
    running = bool(latest_start and (not latest_done or latest_start[0] > latest_done[0]))
    running_label = running_backup_label(latest_start[1]) if latest_start else "Backup running"
    return {
        "state": "Degraded" if failed else "Running" if running else "Healthy" if has_completion else "Unknown",
        "quick": running_label if running and "Quick" in running_label else format_backup_line(quick, "Quick") if quick else "No quick log",
        "full": running_label if running and "Full" in running_label else format_backup_line(full, "Full") if full else format_backup_line(photos, "Photos") if photos else "No full log",
        "cloud": format_backup_line(photos, "Photos") if photos else "Cloud backup unchecked",
        "next": "Running now" if running else "Cron schedule",
    }


def latest_matching(lines: list[str], phrases: tuple[str, ...]) -> str | None:
    return next((line for line in reversed(lines) if any(phrase in line for phrase in phrases)), None)


def latest_matching_with_index(lines: list[str], phrases: tuple[str, ...]) -> tuple[int, str] | None:
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index]
        if any(phrase in line for phrase in phrases):
            return index, line
    return None


def running_backup_label(line: str) -> str:
    label = "Full" if "Full backup" in line else "Quick"
    return format_backup_line(line, f"{label} running")


def format_backup_line(line: str | None, label: str) -> str:
    if not line:
        return "Not checked"

    clean = line.strip("= ").strip()
    timestamp = clean.split(":", 1)[1].strip() if ":" in clean else clean
    match = re.search(
        r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{1,2})[:h](\d{2})",
        timestamp,
    )
    if match:
        hour = int(match.group(4))
        minute = match.group(5)
        suffix = "AM" if hour < 12 else "PM"
        hour_12 = hour % 12 or 12
        return f"{label} {match.group(2)} {match.group(3)} {hour_12}:{minute} {suffix}"

    iso_match = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})[ T](\d{2}):(\d{2})", timestamp)
    if iso_match:
        hour = int(iso_match.group(4))
        suffix = "AM" if hour < 12 else "PM"
        hour_12 = hour % 12 or 12
        return f"{label} {iso_match.group(2)}/{iso_match.group(3)} {hour_12}:{iso_match.group(5)} {suffix}"

    return f"{label} {timestamp[-24:] if len(timestamp) > 24 else timestamp}"
