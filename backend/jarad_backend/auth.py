from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time

from fastapi import Header, HTTPException

from .config import APP_TOKEN, TOTP_SECRET
from .models import ActionRequest
from .webauthn_auth import consume_action_token


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {APP_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


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
