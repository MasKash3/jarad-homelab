from __future__ import annotations

import platform
import re
import socket
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .audit import audit_event
from .auth import DEVICE_COOKIE_NAME, require_device_token, require_token, verify_action_auth, verify_totp_for_actor
from .config import (
    ALLOW_PASSKEY_BOOTSTRAP_WITHOUT_TOTP,
    DEVICE_TOKEN_TTL_DAYS,
    LAN_IP,
    PUBLIC_HOST,
    REDUCED_SERVICE_METADATA,
    SERVICES,
    TOTP_SECRET,
)
from .device_tokens import create_browser_session, create_device_token, list_device_tokens, revoke_device_token, rotate_device_token
from .dns_access import approve_client, deny_client, list_clients as list_dns_clients, revoke_client, update_client_label
from .docker import docker_action, docker_logs, is_allowed_action
from .metrics import read_backup_state, read_cpu_pct, read_disk, read_raid_state, read_ram_pct, read_temp_c, read_uptime
from .models import (
    ActionRequest,
    DeviceTokenRegisterRequest,
    DeviceTokenRevokeRequest,
    DeviceTokenRotateRequest,
    DnsClientApproveRequest,
    DnsClientLabelRequest,
    WebAuthnAuthenticateOptionsRequest,
    WebAuthnAuthenticateVerifyRequest,
    WebAuthnCredentialDeleteRequest,
    WebAuthnRegisterOptionsRequest,
    WebAuthnRegisterVerifyRequest,
)
from .rate_limit import enforce_rate_limit
from .redaction import redact_sensitive_text
from .scrutiny import scrutiny_snapshot
from .services import alerts_for, build_services, network_state, recent_logs
from .webauthn_auth import (
    begin_authentication,
    begin_registration,
    configuration_diagnostics,
    finish_authentication,
    finish_registration,
    list_registered_credentials,
    remove_registered_credential,
)

router = APIRouter()
protected = [Depends(require_token)]


def diagnostic_state(value: str) -> str:
    text = value.lower()
    fail_terms = ("stopped", "failed", "unavailable", "error", "not running")
    warn_terms = ("degraded", "warning", "elevated", "unchecked", "unknown")
    if any(term in text for term in fail_terms):
        return "fail"
    if any(term in text for term in warn_terms):
        return "warn"
    return "pass"


def require_credential_management_auth(totp_code: str | None, request: Request, *, consume: bool) -> None:
    credentials_exist = bool(list_registered_credentials())
    if credentials_exist or TOTP_SECRET:
        if not verify_totp_for_actor(totp_code or "", request, consume=consume):
            raise HTTPException(status_code=401, detail="TOTP is required to manage passkeys")
        return
    if ALLOW_PASSKEY_BOOTSTRAP_WITHOUT_TOTP:
        return
    raise HTTPException(
        status_code=403,
        detail="First passkey enrollment requires TOTP or explicit server-side bootstrap mode",
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "host": socket.gethostname()}


@router.get("/api/auth/devices", dependencies=protected)
def auth_devices(request: Request) -> dict[str, Any]:
    return {
        "devices": list_device_tokens(),
        "currentDeviceId": getattr(request.state, "auth_device_id", None),
    }


def set_device_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=DEVICE_COOKIE_NAME,
        value=token,
        max_age=DEVICE_TOKEN_TTL_DAYS * 24 * 60 * 60,
        path="/api/auth",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_device_cookie(response: Response) -> None:
    response.delete_cookie(
        key=DEVICE_COOKIE_NAME,
        path="/api/auth",
        secure=True,
        httponly=True,
        samesite="strict",
    )


@router.post("/api/auth/session")
def auth_session_create(
    request: Request,
    response: Response,
    device: dict[str, Any] = Depends(require_device_token),
) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="browser-session-create", limit=20, window_seconds=300)
    result = create_browser_session(device["device_id"], request)
    header_token = request.headers.get("authorization", "").partition(" ")[2]
    if header_token and getattr(request.state, "auth_device_token_source", None) == "header":
        set_device_cookie(response, header_token)
    audit_event(
        "browser_session.created",
        "success",
        request=request,
        details={
            "device_id": device["device_id"],
            "session_id": result["session"]["sessionId"],
            "expires_at": result["session"]["expiresAt"],
        },
    )
    return result


@router.post("/api/auth/devices/register", dependencies=protected)
def auth_device_register(payload: DeviceTokenRegisterRequest, request: Request, response: Response) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="device-token-register", limit=6, window_seconds=300)
    if not verify_totp_for_actor(payload.totpCode, request, consume=True):
        audit_event(
            "device_token.registration",
            "failure",
            request=request,
            details={"detail": "Invalid TOTP code"},
        )
        raise HTTPException(status_code=401, detail="Invalid TOTP code")
    result = create_device_token(payload.deviceLabel, request)
    set_device_cookie(response, result["token"])
    audit_event(
        "device_token.registration",
        "success",
        request=request,
        details={"device_id": result["device"]["deviceId"], "device_label": result["device"]["deviceLabel"]},
    )
    return {"device": result["device"]}


@router.post("/api/auth/devices/current/lock")
def auth_device_lock(
    request: Request,
    response: Response,
    device: dict[str, Any] = Depends(require_device_token),
) -> dict[str, str]:
    enforce_rate_limit(request, bucket="device-lock", limit=5, window_seconds=300)
    device_id = device["device_id"]
    if not revoke_device_token(device_id):
        audit_event(
            "device_token.lock",
            "failure",
            request=request,
            details={"device_id": device_id, "detail": "Unknown or already revoked device token"},
        )
        clear_device_cookie(response)
        raise HTTPException(status_code=404, detail="Unknown or already revoked device token")
    clear_device_cookie(response)
    audit_event("device_token.lock", "success", request=request, details={"device_id": device_id})
    return {"status": "locked"}


@router.delete("/api/auth/devices/{device_id}", dependencies=protected)
def auth_device_revoke(device_id: str, payload: DeviceTokenRevokeRequest, request: Request) -> dict[str, str]:
    enforce_rate_limit(request, bucket="device-token-revoke", limit=5, window_seconds=300)
    if not verify_totp_for_actor(payload.totpCode, request, consume=True):
        audit_event(
            "device_token.revocation",
            "failure",
            request=request,
            details={"device_id": device_id, "detail": "Invalid TOTP code"},
        )
        raise HTTPException(status_code=401, detail="Invalid TOTP code")
    if not revoke_device_token(device_id):
        audit_event(
            "device_token.revocation",
            "failure",
            request=request,
            details={"device_id": device_id, "detail": "Unknown or already revoked device token"},
        )
        raise HTTPException(status_code=404, detail="Unknown or already revoked device token")
    audit_event("device_token.revocation", "success", request=request, details={"device_id": device_id})
    return {"status": "revoked"}


@router.post("/api/auth/devices/current/rotate")
def auth_device_rotate(
    payload: DeviceTokenRotateRequest,
    request: Request,
    response: Response,
    device: dict[str, Any] = Depends(require_device_token),
) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="device-token-rotate", limit=5, window_seconds=300)
    device_id = device["device_id"]
    if not verify_totp_for_actor(payload.totpCode, request, consume=True):
        audit_event(
            "device_token.rotation",
            "failure",
            request=request,
            details={"device_id": device_id, "detail": "Invalid TOTP code"},
        )
        raise HTTPException(status_code=401, detail="Invalid TOTP code")
    result = rotate_device_token(device_id, request)
    if not result:
        audit_event(
            "device_token.rotation",
            "failure",
            request=request,
            details={"device_id": device_id, "detail": "Unknown or expired device token"},
        )
        raise HTTPException(status_code=404, detail="Unknown or expired device token")
    set_device_cookie(response, result["token"])
    audit_event(
        "device_token.rotation",
        "success",
        request=request,
        details={
            "old_device_id": device_id,
            "new_device_id": result["device"]["deviceId"],
            "device_label": result["device"]["deviceLabel"],
            "expires_at": result["device"]["expiresAt"],
        },
    )
    return {"device": result["device"]}


@router.post("/api/auth/webauthn/register/options", dependencies=protected)
def webauthn_register_options(payload: WebAuthnRegisterOptionsRequest, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="webauthn-register-options", limit=20, window_seconds=300)
    try:
        require_credential_management_auth(payload.totpCode, request, consume=False)
        return begin_registration(payload.deviceLabel, request.state.auth_actor)
    except HTTPException as exc:
        audit_event(
            "passkey.registration",
            "failure",
            request=request,
            details={"stage": "options", "status_code": exc.status_code, "detail": exc.detail},
        )
        raise


@router.post("/api/auth/webauthn/register/verify", dependencies=protected)
def webauthn_register_verify(payload: WebAuthnRegisterVerifyRequest, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="webauthn-register-verify", limit=20, window_seconds=300)
    try:
        require_credential_management_auth(payload.totpCode, request, consume=True)
        result = finish_registration(
            payload.challengeId, payload.credential, payload.deviceLabel, request.state.auth_actor
        )
    except HTTPException as exc:
        audit_event(
            "passkey.registration",
            "failure",
            request=request,
            details={"stage": "verify", "status_code": exc.status_code, "detail": exc.detail},
        )
        raise
    audit_event(
        "passkey.registration",
        "success",
        request=request,
        credential_id=result.get("credentialId"),
        details={"device_label": result.get("deviceLabel", "This device")},
    )
    return result


@router.get("/api/auth/webauthn/credentials", dependencies=protected)
def webauthn_credentials() -> dict[str, Any]:
    return {"credentials": list_registered_credentials()}


@router.get("/api/auth/webauthn/diagnostics", dependencies=protected)
def webauthn_configuration_diagnostics() -> dict[str, Any]:
    return configuration_diagnostics()


@router.delete("/api/auth/webauthn/credentials/{credential_id}", dependencies=protected)
def webauthn_delete_credential(credential_id: str, payload: WebAuthnCredentialDeleteRequest, request: Request) -> dict[str, str]:
    enforce_rate_limit(request, bucket="webauthn-credential-delete", limit=5, window_seconds=300)
    try:
        require_credential_management_auth(payload.totpCode, request, consume=True)
        remove_registered_credential(credential_id)
    except HTTPException as exc:
        audit_event(
            "passkey.removal",
            "failure",
            request=request,
            credential_id=credential_id,
            details={"status_code": exc.status_code, "detail": exc.detail},
        )
        raise
    audit_event("passkey.removal", "success", request=request, credential_id=credential_id)
    return {"status": "deleted"}


@router.post("/api/auth/webauthn/authenticate/options", dependencies=protected)
def webauthn_authenticate_options(payload: WebAuthnAuthenticateOptionsRequest, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="webauthn-authenticate", limit=12, window_seconds=60)
    try:
        return begin_authentication(payload.actionId, payload.serviceId, request.state.auth_actor)
    except HTTPException as exc:
        audit_event(
            "webauthn.authentication",
            "failure",
            request=request,
            action_id=payload.actionId,
            service_id=payload.serviceId,
            details={"stage": "options", "status_code": exc.status_code, "detail": exc.detail},
        )
        raise


@router.post("/api/auth/webauthn/authenticate/verify", dependencies=protected)
def webauthn_authenticate_verify(payload: WebAuthnAuthenticateVerifyRequest, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="webauthn-authenticate", limit=12, window_seconds=60)
    try:
        result = finish_authentication(
            challenge_id=payload.challengeId,
            credential=payload.credential,
            action_id=payload.actionId,
            service_id=payload.serviceId,
            actor_id=request.state.auth_actor,
        )
    except HTTPException as exc:
        audit_event(
            "webauthn.authentication",
            "failure",
            request=request,
            action_id=payload.actionId,
            service_id=payload.serviceId,
            details={"stage": "verify", "status_code": exc.status_code, "detail": exc.detail},
        )
        raise
    audit_event(
        "webauthn.authentication",
        "success",
        request=request,
        action_id=payload.actionId,
        service_id=payload.serviceId,
        credential_id=result.get("credentialId"),
    )
    if result.get("actionAuthToken"):
        audit_event(
            "action_token.created",
            "success",
            request=request,
            action_id=payload.actionId,
            service_id=payload.serviceId,
            credential_id=result.get("credentialId"),
        )
    return result


@router.get("/api/mobile/state", dependencies=protected)
def mobile_state() -> dict[str, Any]:
    disk_pct, disk_label = read_disk()
    backup = read_backup_state()
    services = build_services()
    scrutiny_service = next((service for service in services if service.get("id") == "scrutiny"), None)
    if scrutiny_service and scrutiny_service.get("health") == "healthy":
        drive_snapshot = scrutiny_snapshot()
    else:
        drive_snapshot = {
            "available": False,
            "state": "bad",
            "message": "Scrutiny is not running, so drive health is unavailable.",
            "summary": {"healthy": 0, "warning": 0, "critical": 0},
            "items": [],
            "alerts": [],
        }
    disk_health_alerts = drive_snapshot["alerts"]
    temp = read_temp_c()
    metrics = [
        {"label": "CPU", "value": read_cpu_pct(), "unit": "%", "state": "good"},
        {"label": "RAM", "value": read_ram_pct(), "unit": "%", "state": "good"},
        {
            "label": "Disk",
            "value": disk_pct,
            "unit": "%",
            "state": "warn" if disk_pct >= 70 else "good",
            "badge": f"{disk_pct}% used",
        },
        {"label": "Temp", "value": temp, "unit": "C", "state": "warn" if temp >= 70 else "good"},
    ]

    down_count = sum(1 for service in services if service["health"] == "down")
    degraded_count = sum(1 for service in services if service["health"] == "degraded")
    disk_bad_count = sum(1 for alert in disk_health_alerts if alert.get("state") == "bad")
    disk_warn_count = sum(1 for alert in disk_health_alerts if alert.get("state") == "warn")
    status = (
        "Operational"
        if down_count == 0 and degraded_count == 0 and disk_bad_count == 0 and disk_warn_count == 0
        else "Attention needed"
    )
    score = max(
        0,
        100 - (down_count * 20) - (degraded_count * 8) - (disk_bad_count * 20) - (disk_warn_count * 8),
    )

    return {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "server": {
            "name": "Jarad",
            "host": "Private host" if REDUCED_SERVICE_METADATA else PUBLIC_HOST,
            "lan": "Private network" if REDUCED_SERVICE_METADATA else LAN_IP,
            "uptime": read_uptime(),
            "healthScore": score,
            "status": status,
            "platform": "Private Linux host" if REDUCED_SERVICE_METADATA else platform.platform(),
        },
        "metrics": metrics,
        "storage": {
            "usedPct": disk_pct,
            "label": disk_label,
            "cloudBackup": backup.get("cloud", "Cloud backup unchecked"),
            "raid": read_raid_state(),
        },
        "backups": backup,
        "services": services,
        "logs": recent_logs(),
        "alerts": alerts_for(services, disk_pct, backup["state"], disk_health_alerts),
        "drives": {key: value for key, value in drive_snapshot.items() if key != "alerts"},
        "network": network_state(),
    }


@router.get("/api/dns/clients", dependencies=protected)
def dns_clients() -> dict[str, Any]:
    return list_dns_clients()


@router.post("/api/dns/clients/{client_ip}/approve", dependencies=protected)
def dns_client_approve(client_ip: str, payload: DnsClientApproveRequest, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="dns-access-action", limit=12, window_seconds=60)
    action_id = f"dns-approve-{client_ip}"
    method = (payload.authMethod or "").lower()
    try:
        verify_action_auth(payload, action_id, "dns-access", request)
        client, apply_result = approve_client(client_ip, payload.duration)
    except ValueError as exc:
        audit_event("dns_access.approve", "failure", request=request, action_id=action_id, service_id="dns-access", details={"detail": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException as exc:
        audit_event(
            action_auth_event_type(method),
            "failure",
            request=request,
            action_id=action_id,
            service_id="dns-access",
            details={"method": method or "missing", "status_code": exc.status_code, "detail": exc.detail},
        )
        raise
    audit_event(
        "dns_access.approve",
        "success",
        request=request,
        action_id=action_id,
        service_id="dns-access",
        details={"client_ip": client_ip, "duration": payload.duration, "apply": apply_result},
    )
    return {"status": "approved", "client": client, "firewall": apply_result}


@router.post("/api/dns/clients/{client_ip}/deny", dependencies=protected)
def dns_client_deny(client_ip: str, payload: ActionRequest, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="dns-access-action", limit=12, window_seconds=60)
    action_id = f"dns-deny-{client_ip}"
    method = (payload.authMethod or "").lower()
    try:
        verify_action_auth(payload, action_id, "dns-access", request)
        client, apply_result = deny_client(client_ip)
    except ValueError as exc:
        audit_event("dns_access.deny", "failure", request=request, action_id=action_id, service_id="dns-access", details={"detail": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException as exc:
        audit_event(
            action_auth_event_type(method),
            "failure",
            request=request,
            action_id=action_id,
            service_id="dns-access",
            details={"method": method or "missing", "status_code": exc.status_code, "detail": exc.detail},
        )
        raise
    audit_event(
        "dns_access.deny",
        "success",
        request=request,
        action_id=action_id,
        service_id="dns-access",
        details={"client_ip": client_ip, "apply": apply_result},
    )
    return {"status": "denied", "client": client, "firewall": apply_result}


@router.post("/api/dns/clients/{client_ip}/revoke", dependencies=protected)
def dns_client_revoke(client_ip: str, payload: ActionRequest, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="dns-access-action", limit=12, window_seconds=60)
    action_id = f"dns-revoke-{client_ip}"
    method = (payload.authMethod or "").lower()
    try:
        verify_action_auth(payload, action_id, "dns-access", request)
        client, apply_result = revoke_client(client_ip)
    except ValueError as exc:
        audit_event("dns_access.revoke", "failure", request=request, action_id=action_id, service_id="dns-access", details={"detail": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException as exc:
        audit_event(
            action_auth_event_type(method),
            "failure",
            request=request,
            action_id=action_id,
            service_id="dns-access",
            details={"method": method or "missing", "status_code": exc.status_code, "detail": exc.detail},
        )
        raise
    audit_event(
        "dns_access.revoke",
        "success",
        request=request,
        action_id=action_id,
        service_id="dns-access",
        details={"client_ip": client_ip, "apply": apply_result},
    )
    return {"status": "revoked", "client": client, "firewall": apply_result}


@router.post("/api/dns/clients/{client_ip}/label", dependencies=protected)
def dns_client_label(client_ip: str, payload: DnsClientLabelRequest, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="dns-access-label", limit=20, window_seconds=60)
    try:
        client = update_client_label(client_ip, payload.displayName)
    except ValueError as exc:
        audit_event("dns_access.label", "failure", request=request, service_id="dns-access", details={"detail": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_event(
        "dns_access.label",
        "success",
        request=request,
        service_id="dns-access",
        details={"client_ip": client_ip, "has_display_name": bool(client.get("displayName"))},
    )
    return {"status": "updated", "client": client}


@router.post("/api/services/{service_id}/logs", dependencies=protected)
def service_logs(service_id: str, payload: ActionRequest, request: Request, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="sensitive-view", limit=12, window_seconds=60)
    service = SERVICES.get(service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Unknown service")
    action_id = f"view-logs-{service_id}"
    try:
        verify_action_auth(payload, action_id, service_id, request)
    except HTTPException as exc:
        audit_event(
            action_auth_event_type((payload.authMethod or "").lower()),
            "failure",
            request=request,
            action_id=action_id,
            service_id=service_id,
            details={"method": payload.authMethod or "missing", "status_code": exc.status_code, "detail": exc.detail},
        )
        raise
    audit_event(
        "sensitive_view.logs",
        "success",
        request=request,
        action_id=action_id,
        service_id=service_id,
        details={"method": payload.authMethod or "missing"},
    )
    result = docker_logs(service["container"], limit)
    if not result:
        return {
            "service": service_id,
            "logs": [
                {
                    "level": "error",
                    "time": "Recent",
                    "message": "Docker logs unavailable from backend environment",
                }
            ],
        }

    returncode, combined = result
    if returncode != 0:
        return {
            "service": service_id,
            "logs": [
                {
                    "level": "error",
                    "time": "Recent",
                    "message": combined.strip() or "Docker logs failed for the managed service",
                }
            ],
        }
    return {
        "service": service_id,
        "logs": [
            service_log_row(line)
            for line in combined.splitlines()[-limit:]
        ],
    }


@router.post("/api/services/{service_id}/diagnostics", dependencies=protected)
def service_diagnostics(service_id: str, payload: ActionRequest, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="sensitive-view", limit=12, window_seconds=60)
    service = next((item for item in build_services() if item["id"] == service_id), None)
    if not service:
        raise HTTPException(status_code=404, detail="Unknown service")
    action_id = f"view-diagnostics-{service_id}"
    try:
        verify_action_auth(payload, action_id, service_id, request)
    except HTTPException as exc:
        audit_event(
            action_auth_event_type((payload.authMethod or "").lower()),
            "failure",
            request=request,
            action_id=action_id,
            service_id=service_id,
            details={"method": payload.authMethod or "missing", "status_code": exc.status_code, "detail": exc.detail},
        )
        raise
    audit_event(
        "sensitive_view.diagnostics",
        "success",
        request=request,
        action_id=action_id,
        service_id=service_id,
        details={"method": payload.authMethod or "missing"},
    )
    return {
        "service": service_id,
        "checks": [
            {"label": label, "state": diagnostic_state(value), "detail": value}
            for label, value in service["diagnostics"]
        ],
        "suggestedFix": None if service["health"] == "healthy" else "Open service logs and verify container dependencies.",
    }


@router.post("/api/admin/actions/{action_id}", dependencies=protected)
def service_action(action_id: str, payload: ActionRequest, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, bucket="admin-action", limit=8, window_seconds=60)
    action, service_id = split_action(action_id)
    service = SERVICES.get(service_id)
    if not service:
        audit_event(
            "docker.policy",
            "failure",
            request=request,
            action_id=action_id,
            service_id=service_id,
            details={"action": action, "detail": "Unknown service"},
        )
        raise HTTPException(status_code=404, detail="Unknown service")
    if not is_allowed_action(service_id, action):
        audit_event(
            "docker.policy",
            "failure",
            request=request,
            action_id=action_id,
            service_id=service_id,
            details={"action": action, "detail": "Action denied by service policy"},
        )
        raise HTTPException(status_code=400, detail="Unsupported action")
    method = (payload.authMethod or "").lower()
    try:
        verify_action_auth(payload, action_id, service_id, request)
    except HTTPException as exc:
        audit_event(
            action_auth_event_type(method),
            "failure",
            request=request,
            action_id=action_id,
            service_id=service_id,
            details={"method": method or "missing", "status_code": exc.status_code, "detail": exc.detail},
        )
        raise
    audit_event(
        action_auth_event_type(method),
        "success",
        request=request,
        action_id=action_id,
        service_id=service_id,
        details={"method": method or "missing"},
    )

    result = docker_action(action, service_id)
    if not result or result.returncode != 0:
        detail = redact_sensitive_text(result.stderr.strip()) if result else "Docker command unavailable"
        audit_event(
            "docker.action",
            "failure",
            request=request,
            action_id=action_id,
            service_id=service_id,
            details={"action": action, "container": service["container"], "detail": detail},
        )
        raise HTTPException(status_code=500, detail=detail)
    audit_event(
        "docker.action",
        "success",
        request=request,
        action_id=action_id,
        service_id=service_id,
        details={"action": action, "container": service["container"]},
    )
    refreshed = next((item for item in build_services() if item["id"] == service_id), None)
    return {
        "status": "accepted",
        "action": action,
        "service": service_id,
        "target": service_id if REDUCED_SERVICE_METADATA else service["container"],
        "source": payload.source,
        "current": refreshed,
    }


def split_action(action_id: str) -> tuple[str, str]:
    for action in ("restart", "start", "stop"):
        prefix = f"{action}-"
        if action_id.startswith(prefix):
            return action, action_id.removeprefix(prefix)
    raise HTTPException(status_code=400, detail="Unsupported action id")


def action_auth_event_type(method: str) -> str:
    if method == "fingerprint":
        return "action_token.consumed"
    if method == "totp":
        return "totp.action_auth"
    return "action_auth"


def service_log_row(line: str) -> dict[str, str]:
    log_time, message = split_docker_log_line(line)
    return {
        "level": "error" if "error" in message.lower() else "info",
        "time": log_time,
        "message": message,
    }


def split_docker_log_line(line: str) -> tuple[str, str]:
    match = re.match(r"^(\d{4}-\d{2}-\d{2}T[^\s]+)\s+(.*)$", line)
    if not match:
        return "Recent", line

    return format_docker_timestamp(match.group(1)), match.group(2)


def format_docker_timestamp(raw_timestamp: str) -> str:
    timestamp = raw_timestamp.removesuffix("Z")
    if "." in timestamp:
        base, fraction = timestamp.split(".", 1)
        timestamp = f"{base}.{fraction[:6]}"
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return raw_timestamp[:19].replace("T", " ")

    return f"{parsed.strftime('%b')} {parsed.day} {parsed.strftime('%H:%M')} UTC"
