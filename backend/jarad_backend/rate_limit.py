from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request

from .request_address import client_addr


_attempts: dict[str, Deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def client_key(request: Request, bucket: str) -> str:
    client_host = client_addr(request) or "unknown"
    auth_digest = hashlib.sha256((request.headers.get("authorization") or "").encode("utf-8")).hexdigest()[:16]
    return f"{bucket}:{client_host}:{auth_digest}"


def enforce_rate_limit(request: Request, *, bucket: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    key = client_key(request, bucket)

    with _lock:
        attempts = _attempts[key]
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()

        if len(attempts) >= limit:
            retry_after = max(1, round(window_seconds - (now - attempts[0])))
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )

        attempts.append(now)
