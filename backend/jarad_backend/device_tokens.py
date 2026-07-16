from __future__ import annotations

import secrets
from typing import Any

from fastapi import Request

from .auth import hash_access_token
from .config import REDUCED_CREDENTIAL_METADATA
from .request_address import client_addr
from .webauthn_store import WebAuthnStore


store = WebAuthnStore()


def create_device_token(device_label: str | None, request: Request) -> dict[str, Any]:
    raw_token = secrets.token_urlsafe(32)
    label = (device_label or "Registered device").strip()[:80] or "Registered device"
    device = store.create_device_token(
        token_hash=hash_access_token(raw_token),
        device_label=label,
        remote_addr=client_addr(request),
        user_agent=(request.headers.get("user-agent") or "")[:240],
    )
    return {
        "token": raw_token,
        "device": public_device(device),
    }


def rotate_device_token(device_id: str, request: Request) -> dict[str, Any] | None:
    raw_token = secrets.token_urlsafe(32)
    device = store.rotate_device_token(
        device_id=device_id,
        token_hash=hash_access_token(raw_token),
        remote_addr=client_addr(request),
        user_agent=(request.headers.get("user-agent") or "")[:240],
    )
    if not device:
        return None
    return {
        "token": raw_token,
        "device": public_device(device),
    }


def create_browser_session(device_id: str, request: Request) -> dict[str, Any]:
    raw_token = secrets.token_urlsafe(32)
    session = store.create_browser_session(
        device_id=device_id,
        token_hash=hash_access_token(raw_token),
        remote_addr=client_addr(request),
        user_agent=(request.headers.get("user-agent") or "")[:240],
    )
    return {
        "token": raw_token,
        "session": {
            "sessionId": session["session_id"],
            "deviceId": session["device_id"],
            "createdAt": session["created_at"],
            "expiresAt": session["expires_at"],
        },
    }


def list_device_tokens() -> list[dict[str, Any]]:
    devices = store.list_device_tokens(include_revoked=False)
    return [
        public_device(device, alias=f"Device {index}")
        for index, device in enumerate(devices, start=1)
    ]


def revoke_device_token(device_id: str) -> bool:
    return store.revoke_device_token(device_id)


def public_device(device: dict[str, Any], alias: str | None = None) -> dict[str, Any]:
    if REDUCED_CREDENTIAL_METADATA:
        return {
            "deviceId": device["device_id"],
            "deviceLabel": alias or "Registered device",
            "createdAt": None,
            "lastUsedAt": None,
            "revokedAt": device["revoked_at"],
            "expiresAt": device["expires_at"],
            "rotatedAt": None,
            "remoteAddr": None,
            "userAgent": None,
        }
    return {
        "deviceId": device["device_id"],
        "deviceLabel": device["device_label"],
        "createdAt": device["created_at"],
        "lastUsedAt": device["last_used_at"],
        "revokedAt": device["revoked_at"],
        "expiresAt": device["expires_at"],
        "rotatedAt": device["rotated_at"],
        "remoteAddr": device["remote_addr"],
        "userAgent": device["user_agent"],
    }
