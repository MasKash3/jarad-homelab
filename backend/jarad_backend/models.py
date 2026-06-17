from __future__ import annotations

from pydantic import BaseModel


class ActionRequest(BaseModel):
    source: str = "mobile-pwa"
    serviceId: str | None = None
    authorized: bool = False
    authMethod: str | None = None
    totpCode: str | None = None
    fingerprintVerified: bool = False


class TotpCheckRequest(BaseModel):
    code: str
