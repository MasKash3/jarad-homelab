from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from typing import Deque

from fastapi import Cookie, Header, HTTPException, Request

from .audit import audit_event
from .config import ALLOWED_ORIGINS, APP_TOKEN, TOTP_SECRET
from .models import ActionRequest
from .webauthn_auth import consume_action_token
from .webauthn_store import WebAuthnStore


store = WebAuthnStore()
DEVICE_COOKIE_NAME = "jarad_device"
BOOTSTRAP_ALLOWED_PATHS = {"/api/auth/devices/register"}
TOTP_STEP_SECONDS = 30
TOTP_FAILURE_WINDOW_SECONDS = 300
TOTP_FAILURE_LIMIT = 5
TOTP_LOCKOUT_BASE_SECONDS = 60
TOTP_LOCKOUT_MAX_SECONDS = 900
TOTP_USED_RETENTION_SECONDS = 120

_totp_lock = threading.Lock()
_totp_failures: dict[str, Deque[float]] = {}
_totp_lockouts: dict[str, float] = {}
_totp_lockout_counts: dict[str, int] = {}
_used_totp_steps: dict[tuple[str, int, str], float] = {}


def hash_access_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    token = bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")

    token_hash = hash_access_token(token)
    session = store.get_active_browser_session(token_hash)
    if session:
        request.state.auth_actor = f"session:{session['session_id']}"
        request.state.auth_token_kind = "session"
        request.state.auth_session_id = session["session_id"]
        request.state.auth_device_id = session["device_id"]
        request.state.auth_device_label = session["device_label"]
        return

    device = store.get_active_device_token(token_hash)
    if device:
        request.state.auth_actor = f"device:{device['device_id']}"
        request.state.auth_token_kind = "device"
        request.state.auth_device_id = device["device_id"]
        request.state.auth_device_label = device["device_label"]
        return

    if secrets.compare_digest(token, APP_TOKEN):
        active_devices_exist = store.has_active_device_tokens()
        if active_devices_exist and request.url.path not in BOOTSTRAP_ALLOWED_PATHS:
            raise HTTPException(status_code=401, detail="Use a registered device token or browser session for this request")
        request.state.auth_actor = "bootstrap-token"
        request.state.auth_token_kind = "bootstrap"
        request.state.auth_device_id = None
        request.state.auth_device_label = "Bootstrap token"
        return

    raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


def require_device_token(
    request: Request,
    authorization: str | None = Header(default=None),
    device_cookie: str | None = Cookie(default=None, alias=DEVICE_COOKIE_NAME),
) -> dict:
    token = bearer_token(authorization)
    token_source = "header"
    if not token and device_cookie:
        require_allowed_cookie_origin(request)
        token = device_cookie
        token_source = "cookie"
    if not token:
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")

    device = store.get_active_device_token(hash_access_token(token))
    if device:
        request.state.auth_actor = f"device:{device['device_id']}"
        request.state.auth_token_kind = "device"
        request.state.auth_device_id = device["device_id"]
        request.state.auth_device_label = device["device_label"]
        request.state.auth_device_token_source = token_source
        return device

    raise HTTPException(status_code=401, detail="Use a registered device token for this request")


def require_allowed_cookie_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin or origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Device cookie requires an allowed same-origin request")


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def verify_action_auth(payload: ActionRequest, action_id: str, service_id: str, request: Request) -> None:
    method = (payload.authMethod or "").lower()
    if method == "totp":
        if not verify_totp_for_actor(payload.totpCode or "", request, consume=True):
            raise HTTPException(status_code=401, detail="Invalid TOTP code")
        return
    if method == "fingerprint":
        if not payload.actionAuthToken:
            raise HTTPException(status_code=401, detail="Missing WebAuthn action authorization")
        if not consume_action_token(payload.actionAuthToken, action_id, service_id):
            raise HTTPException(status_code=401, detail="Invalid or expired WebAuthn action authorization")
        return
    raise HTTPException(status_code=400, detail="Choose TOTP before running this action")


def verify_totp_for_actor(code: str, request: Request, *, consume: bool) -> bool:
    actor = totp_actor(request)
    now = time.monotonic()
    ensure_totp_not_locked(actor, now, request)

    matched_step = matching_totp_step(code)
    if matched_step is None:
        lockout_seconds = record_totp_failure(actor, now)
        if lockout_seconds:
            audit_event(
                "totp.lockout",
                "activated",
                request=request,
                details={"retry_after_seconds": lockout_seconds},
            )
        return False

    if consume and not consume_totp_step(actor, matched_step, code, now):
        lockout_seconds = record_totp_failure(actor, now)
        if lockout_seconds:
            audit_event(
                "totp.lockout",
                "activated",
                request=request,
                details={"retry_after_seconds": lockout_seconds},
            )
        return False

    record_totp_success(actor)
    return True


def matching_totp_step(code: str) -> int | None:
    if not TOTP_SECRET:
        raise HTTPException(status_code=500, detail="TOTP is not configured on the backend")
    if not code.isdigit() or len(code) != 6:
        return None

    timestep = int(time.time() // TOTP_STEP_SECONDS)
    for offset in (-1, 0, 1):
        candidate_step = timestep + offset
        if hmac.compare_digest(code, totp_for_step(TOTP_SECRET, candidate_step)):
            return candidate_step
    return None


def totp_actor(request: Request) -> str:
    return getattr(request.state, "auth_actor", None) or "unknown"


def ensure_totp_not_locked(actor: str, now: float, request: Request) -> None:
    with _totp_lock:
        locked_until = _totp_lockouts.get(actor, 0.0)
        if locked_until <= now:
            if locked_until:
                _totp_lockouts.pop(actor, None)
            return
        retry_after = max(1, round(locked_until - now))
    audit_event(
        "totp.lockout",
        "blocked",
        request=request,
        details={"retry_after_seconds": retry_after},
    )
    raise HTTPException(
        status_code=429,
        detail="Too many invalid TOTP attempts. Try again shortly.",
        headers={"Retry-After": str(retry_after)},
    )


def record_totp_failure(actor: str, now: float) -> int | None:
    cutoff = now - TOTP_FAILURE_WINDOW_SECONDS
    with _totp_lock:
        failures = _totp_failures.setdefault(actor, deque())
        while failures and failures[0] <= cutoff:
            failures.popleft()
        failures.append(now)
        if len(failures) < TOTP_FAILURE_LIMIT:
            return None

        lockout_count = _totp_lockout_counts.get(actor, 0) + 1
        lockout_seconds = min(TOTP_LOCKOUT_BASE_SECONDS * (2 ** (lockout_count - 1)), TOTP_LOCKOUT_MAX_SECONDS)
        _totp_lockout_counts[actor] = lockout_count
        _totp_lockouts[actor] = now + lockout_seconds
        failures.clear()
        return lockout_seconds


def record_totp_success(actor: str) -> None:
    with _totp_lock:
        _totp_failures.pop(actor, None)
        _totp_lockouts.pop(actor, None)
        _totp_lockout_counts.pop(actor, None)


def consume_totp_step(actor: str, timestep: int, code: str, now: float) -> bool:
    key = (actor, timestep, hashlib.sha256(code.encode("utf-8")).hexdigest())
    cutoff = now - TOTP_USED_RETENTION_SECONDS
    with _totp_lock:
        for used_key, used_at in list(_used_totp_steps.items()):
            if used_at <= cutoff:
                _used_totp_steps.pop(used_key, None)
        if key in _used_totp_steps:
            return False
        _used_totp_steps[key] = now
        return True


def totp_for_step(secret: str, timestep: int) -> str:
    try:
        normalized = secret.upper()
        padded = normalized + ("=" * ((8 - len(normalized) % 8) % 8))
        key = base64.b32decode(padded, casefold=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Backend TOTP secret is invalid") from exc

    counter = timestep.to_bytes(8, "big")
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}"
