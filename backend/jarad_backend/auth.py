from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time

from fastapi import Header, HTTPException, Request

from .config import APP_TOKEN, TOTP_SECRET
from .models import ActionRequest
from .webauthn_auth import consume_action_token
from .webauthn_store import WebAuthnStore


store = WebAuthnStore()
BOOTSTRAP_ALLOWED_PATHS = {"/api/auth/devices/register"}


def hash_access_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    token = bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")

    device = store.get_active_device_token(hash_access_token(token))
    if device:
        request.state.auth_actor = f"device:{device['device_id']}"
        request.state.auth_device_id = device["device_id"]
        request.state.auth_device_label = device["device_label"]
        return

    if secrets.compare_digest(token, APP_TOKEN):
        active_devices_exist = store.has_active_device_tokens()
        if active_devices_exist and request.url.path not in BOOTSTRAP_ALLOWED_PATHS:
            raise HTTPException(status_code=401, detail="Use a registered device token for this request")
        request.state.auth_actor = "bootstrap-token"
        request.state.auth_device_id = None
        request.state.auth_device_label = "Bootstrap token"
        return

    raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def verify_action_auth(payload: ActionRequest, action_id: str, service_id: str) -> None:
    method = (payload.authMethod or "").lower()
    if method == "totp":
        if not verify_totp(payload.totpCode or ""):
            raise HTTPException(status_code=401, detail="Invalid TOTP code")
        return
    if method == "fingerprint":
        if not payload.actionAuthToken:
            raise HTTPException(status_code=401, detail="Missing WebAuthn action authorization")
        if not consume_action_token(payload.actionAuthToken, action_id, service_id):
            raise HTTPException(status_code=401, detail="Invalid or expired WebAuthn action authorization")
        return
    raise HTTPException(status_code=400, detail="Choose TOTP before running this action")


def verify_totp(code: str) -> bool:
    if not TOTP_SECRET:
        raise HTTPException(status_code=500, detail="TOTP is not configured on the backend")
    if not code.isdigit() or len(code) != 6:
        return False

    timestep = int(time.time() // 30)
    return any(hmac.compare_digest(code, totp_for_step(TOTP_SECRET, timestep + offset)) for offset in (-1, 0, 1))


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
