from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request

from .request_address import client_addr


_attempts: dict[str, Deque[float]] = defaultdict(deque)
_key_expires_at: dict[str, float] = {}
_key_last_seen: dict[str, float] = {}
_lock = threading.Lock()
_last_prune = 0.0
MAX_RATE_LIMIT_KEYS = 4096
PRUNE_INTERVAL_SECONDS = 30


def client_key(request: Request, bucket: str) -> str:
    client_host = client_addr(request) or "unknown"
    actor = getattr(request.state, "auth_actor", None)
    if actor:
        identity = actor
    else:
        identity = hashlib.sha256((request.headers.get("authorization") or "").encode("utf-8")).hexdigest()[:16]
    return f"{bucket}:{client_host}:{identity}"


def prune_rate_limit_keys(now: float, incoming_key: str) -> None:
    global _last_prune
    if now - _last_prune < PRUNE_INTERVAL_SECONDS and len(_attempts) < MAX_RATE_LIMIT_KEYS:
        return

    for stale_key, expires_at in list(_key_expires_at.items()):
        if expires_at > now:
            continue
        _attempts.pop(stale_key, None)
        _key_expires_at.pop(stale_key, None)
        _key_last_seen.pop(stale_key, None)

    if incoming_key not in _attempts and len(_attempts) >= MAX_RATE_LIMIT_KEYS:
        oldest_key = min(_key_last_seen, key=_key_last_seen.get)
        _attempts.pop(oldest_key, None)
        _key_expires_at.pop(oldest_key, None)
        _key_last_seen.pop(oldest_key, None)
    _last_prune = now


def enforce_rate_limit(request: Request, *, bucket: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    key = client_key(request, bucket)

    with _lock:
        prune_rate_limit_keys(now, key)
        attempts = _attempts[key]
        _key_last_seen[key] = now
        _key_expires_at[key] = now + window_seconds
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
