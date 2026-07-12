from __future__ import annotations

import re


REDACTED = "[REDACTED]"
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_BEARER_TOKEN = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_CREDENTIAL_URL = re.compile(r"(?i)\b(https?://)[^\s/:@]+:[^\s/@]+@")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|cookie|set-cookie|password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)"
    r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)


def redact_sensitive_text(value: object) -> str:
    text = str(value)
    text = _PEM_PRIVATE_KEY.sub(REDACTED, text)
    text = _BEARER_TOKEN.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    text = _CREDENTIAL_URL.sub(lambda match: f"{match.group(1)}{REDACTED}@", text)
    return _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        text,
    )
