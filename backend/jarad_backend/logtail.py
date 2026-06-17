from __future__ import annotations

from pathlib import Path


def tail_lines(path: Path, max_lines: int, max_bytes: int = 262_144) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read()
    except OSError:
        return []

    return data.decode("utf-8", errors="ignore").splitlines()[-max_lines:]
