from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import Request

from .webauthn_store import WebAuthnStore


logger = logging.getLogger(__name__)
store = WebAuthnStore()


def audit_event(
    event_type: str,
    outcome: str,
    *,
    request: Request | None = None,
    action_id: str | None = None,
    service_id: str | None = None,
    credential_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        store.add_audit_event(
            event_type=_clamp(event_type, 80),
            outcome=_clamp(outcome, 24),
            actor=_actor(request),
            action_id=_clamp(action_id, 120),
            service_id=_clamp(service_id, 120),
            credential_id=_clamp(credential_id, 180),
            remote_addr=_client_addr(request),
            user_agent=_clamp(request.headers.get("user-agent") if request else None, 240),
            details_json=json.dumps(_safe_details(details or {}), sort_keys=True),
        )
    except Exception:
        logger.warning("failed to write audit event", exc_info=True)


def _client_addr(request: Request | None) -> str | None:
    if not request:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return _clamp(forwarded.split(",", 1)[0].strip(), 80)
    return _clamp(request.client.host if request.client else None, 80)


def _actor(request: Request | None) -> str:
    if not request:
        return "unknown"
    return _clamp(getattr(request.state, "auth_actor", None), 120) or "unknown"


def _safe_details(details: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in details.items():
        if value is None:
            continue
        safe[_clamp(str(key), 80)] = _clamp(str(value), 240)
    return safe


def _clamp(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value[:limit]
