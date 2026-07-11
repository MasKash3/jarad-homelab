from __future__ import annotations

import os
import stat
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


def verify_private_database_path(path: Path) -> None:
    """Fail closed when a sensitive SQLite database is not privately owned."""
    if os.name == "nt":
        return

    parent = path.parent
    parent_stat = parent.stat()
    if not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != os.geteuid():
        raise RuntimeError(f"Database directory must be owned by the backend user: {parent}")
    if stat.S_IMODE(parent_stat.st_mode) & 0o022:
        raise RuntimeError(f"Database directory must not be writable by group or other users: {parent}")

    if path.is_symlink():
        raise RuntimeError(f"Database path must not be a symbolic link: {path}")
    if not path.exists():
        return

    path_stat = path.stat()
    if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_uid != os.geteuid():
        raise RuntimeError(f"Database file must be a regular file owned by the backend user: {path}")
    if stat.S_IMODE(path_stat.st_mode) != OWNER_ONLY_FILE_MODE:
        raise RuntimeError(f"Database file permissions must be 0600: {path}")
