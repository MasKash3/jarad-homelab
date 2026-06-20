from __future__ import annotations

from typing import Any


TRUSTED_PROXY_HOSTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"}


def client_addr(request: Any | None, *, limit: int = 80) -> str | None:
    if not request or not request.client:
        return None

    socket_host = _clean(request.client.host)
    if socket_host in TRUSTED_PROXY_HOSTS:
        forwarded = _trusted_forwarded_addr(request)
        if forwarded:
            return forwarded[:limit]

    return socket_host[:limit] if socket_host else None


def _trusted_forwarded_addr(request: Any) -> str | None:
    real_ip = _clean(request.headers.get("x-real-ip"))
    if real_ip:
        return real_ip

    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return None

    # Caddy appends the immediate client to X-Forwarded-For. If a client supplied
    # a spoofed first hop, the last hop is still the value added by our proxy.
    for value in reversed(forwarded_for.split(",")):
        candidate = _clean(value)
        if candidate:
            return candidate
    return None


def _clean(value: str | None) -> str:
    return (value or "").strip()
