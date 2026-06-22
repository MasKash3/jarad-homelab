from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path


OWNER_ONLY_FILE_MODE = 0o600


def ensure_owner_only_file(path: Path) -> None:
    """Keep sensitive runtime files readable and writable only by the owner."""
    if os.name == "nt":
        return

    with suppress(OSError):
        if path.exists():
            path.chmod(OWNER_ONLY_FILE_MODE)

    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = path.with_name(f"{path.name}{suffix}")
        with suppress(OSError):
            if sidecar.exists():
                sidecar.chmod(OWNER_ONLY_FILE_MODE)
