from __future__ import annotations

from pydantic import BaseModel


class ActionRequest(BaseModel):
    source: str = "mobile-pwa"
    serviceId: str | None = None
    authorized: bool = False
    authMethod: str | None = None
    totpCode: str | None = None
    fingerprintVerified: bool = False
    actionAuthToken: str | None = None


class TotpCheckRequest(BaseModel):
    code: str


class WebAuthnRegisterOptionsRequest(BaseModel):
    deviceLabel: str | None = None
    totpCode: str | None = None


class WebAuthnRegisterVerifyRequest(BaseModel):
    challengeId: str
    deviceLabel: str | None = None
    credential: dict
    totpCode: str | None = None


class WebAuthnCredentialDeleteRequest(BaseModel):
    totpCode: str | None = None


class WebAuthnAuthenticateOptionsRequest(BaseModel):
    actionId: str | None = None
    serviceId: str | None = None


class WebAuthnAuthenticateVerifyRequest(BaseModel):
    challengeId: str
    actionId: str | None = None
    serviceId: str | None = None
    credential: dict
