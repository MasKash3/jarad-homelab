from __future__ import annotations

import secrets
from typing import Any

from fastapi import Request

from .auth import hash_access_token
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


def list_device_tokens() -> list[dict[str, Any]]:
    return [public_device(device) for device in store.list_device_tokens()]


def revoke_device_token(device_id: str) -> bool:
    return store.revoke_device_token(device_id)


def public_device(device: dict[str, Any]) -> dict[str, Any]:
    return {
        "deviceId": device["device_id"],
        "deviceLabel": device["device_label"],
        "createdAt": device["created_at"],
        "lastUsedAt": device["last_used_at"],
        "revokedAt": device["revoked_at"],
        "remoteAddr": device["remote_addr"],
        "userAgent": device["user_agent"],
    }


def client_addr(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:80]
    return request.client.host[:80] if request.client else None
