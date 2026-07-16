from __future__ import annotations

import base64
import json
import logging
import secrets
from typing import Any

from fastapi import HTTPException
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    UserVerificationRequirement,
)

from .config import REDUCED_CREDENTIAL_METADATA, WEBAUTHN_ORIGIN, WEBAUTHN_RP_ID
from .webauthn_store import ACTION_AUTH_TTL_SECONDS, CHALLENGE_TTL_SECONDS, WebAuthnStore


RP_NAME = "Jarad"
ADMIN_USER_NAME = "jarad-admin"
ADMIN_DISPLAY_NAME = "Jarad Admin"
logger = logging.getLogger(__name__)


store = WebAuthnStore()


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padded = value + ("=" * ((4 - len(value) % 4) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def options_payload(options: Any) -> dict[str, Any]:
    return json.loads(options_to_json(options))


def begin_registration(device_label: str | None, actor_id: str) -> dict[str, Any]:
    user_handle = secrets.token_urlsafe(16)
    existing_credentials = [
        PublicKeyCredentialDescriptor(id=b64url_decode(item["credential_id"]))
        for item in store.list_credentials()
    ]
    options = generate_registration_options(
        rp_id=WEBAUTHN_RP_ID,
        rp_name=RP_NAME,
        user_id=user_handle.encode("utf-8"),
        user_name=ADMIN_USER_NAME,
        user_display_name=ADMIN_DISPLAY_NAME,
        exclude_credentials=existing_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    payload = options_payload(options)
    challenge_id = store.create_challenge(
        challenge=b64url_decode(payload["challenge"]),
        purpose="registration",
        user_handle=user_handle,
        actor_id=actor_id,
    )
    return {
        "challengeId": challenge_id,
        "options": payload,
        "rpId": WEBAUTHN_RP_ID,
        "origin": WEBAUTHN_ORIGIN,
        "deviceLabel": device_label or "This device",
    }


def finish_registration(
    challenge_id: str, credential: dict[str, Any], device_label: str | None, actor_id: str
) -> dict[str, Any]:
    challenge = store.consume_challenge(challenge_id, "registration", actor_id)
    if not challenge:
        raise HTTPException(status_code=400, detail="Registration challenge expired or already used")

    try:
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge["challenge"],
            expected_origin=WEBAUTHN_ORIGIN,
            expected_rp_id=WEBAUTHN_RP_ID,
            require_user_verification=True,
        )
    except Exception as exc:
        logger.warning("WebAuthn registration verification failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=401, detail="WebAuthn registration verification failed") from exc

    credential_id = b64url_encode(verification.credential_id)
    try:
        store.add_credential(
            credential_id=credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            user_handle=challenge["user_handle"],
            device_label=(device_label or "This device").strip()[:80] or "This device",
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail="This passkey is already registered") from exc

    return {"credentialId": credential_id, "deviceLabel": device_label or "This device"}


def begin_authentication(action_id: str | None, service_id: str | None, actor_id: str) -> dict[str, Any]:
    credentials = store.list_credentials()
    if not credentials:
        raise HTTPException(status_code=400, detail="No passkeys are registered")

    options = generate_authentication_options(
        rp_id=WEBAUTHN_RP_ID,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=b64url_decode(item["credential_id"]))
            for item in credentials
        ],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    payload = options_payload(options)
    challenge_id = store.create_challenge(
        challenge=b64url_decode(payload["challenge"]),
        purpose="authentication",
        action_id=action_id,
        service_id=service_id,
        actor_id=actor_id,
    )
    return {
        "challengeId": challenge_id,
        "options": payload,
        "rpId": WEBAUTHN_RP_ID,
        "origin": WEBAUTHN_ORIGIN,
    }


def finish_authentication(
    *,
    challenge_id: str,
    credential: dict[str, Any],
    action_id: str | None,
    service_id: str | None,
    actor_id: str,
) -> dict[str, Any]:
    challenge = store.consume_challenge(challenge_id, "authentication", actor_id)
    if not challenge:
        raise HTTPException(status_code=400, detail="Authentication challenge expired or already used")
    if challenge["action_id"] and challenge["action_id"] != action_id:
        raise HTTPException(status_code=400, detail="Authentication challenge does not match this action")
    if challenge["service_id"] and challenge["service_id"] != service_id:
        raise HTTPException(status_code=400, detail="Authentication challenge does not match this service")

    credential_id = credential.get("id") or credential.get("rawId")
    stored_credential = store.get_credential(credential_id)
    if not stored_credential:
        raise HTTPException(status_code=401, detail="Unknown or disabled passkey")

    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge["challenge"],
            expected_origin=WEBAUTHN_ORIGIN,
            expected_rp_id=WEBAUTHN_RP_ID,
            credential_public_key=stored_credential["public_key"],
            credential_current_sign_count=stored_credential["sign_count"],
            require_user_verification=True,
        )
    except Exception as exc:
        logger.warning("WebAuthn authentication verification failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=401, detail="WebAuthn authentication verification failed") from exc

    store.update_credential_use(credential_id, verification.new_sign_count)
    action_token = None
    if action_id:
        action_token = store.create_action_authorization(action_id=action_id, service_id=service_id, actor_id=actor_id)
    return {"verified": True, "credentialId": credential_id, "actionAuthToken": action_token}


def list_registered_credentials() -> list[dict[str, Any]]:
    credentials = store.list_credentials()
    return [
        {
            "credentialId": item["credential_id"],
            "deviceLabel": f"Passkey {index}" if REDUCED_CREDENTIAL_METADATA else item["device_label"],
            "createdAt": None if REDUCED_CREDENTIAL_METADATA else item["created_at"],
            "lastUsedAt": None if REDUCED_CREDENTIAL_METADATA else item["last_used_at"],
            "enabled": bool(item["enabled"]),
        }
        for index, item in enumerate(credentials, start=1)
    ]


def configuration_diagnostics() -> dict[str, Any]:
    return {
        "configured": True,
        "rpId": WEBAUTHN_RP_ID,
        "origin": WEBAUTHN_ORIGIN,
        "originMatchesRpId": True,
        "userVerification": "required",
        "challengeTtlSeconds": CHALLENGE_TTL_SECONDS,
        "actionAuthorizationTtlSeconds": ACTION_AUTH_TTL_SECONDS,
    }


def remove_registered_credential(credential_id: str) -> None:
    if not store.disable_credential(credential_id):
        raise HTTPException(status_code=404, detail="Unknown passkey")


def consume_action_token(token: str, action_id: str, service_id: str | None, actor_id: str) -> bool:
    return store.consume_action_authorization(
        token=token, action_id=action_id, service_id=service_id, actor_id=actor_id
    )
