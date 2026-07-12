from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("JARAD_APP_TOKEN", "test-token-with-sufficient-randomness")
os.environ.setdefault("JARAD_WEBAUTHN_ORIGIN", "https://app.example.com")
os.environ.setdefault("JARAD_WEBAUTHN_RP_ID", "example.com")
os.environ.setdefault("JARAD_ALLOWED_ORIGINS", "https://app.example.com")
os.environ.setdefault("JARAD_DB_PATH", os.path.join(tempfile.gettempdir(), f"jarad-route-test-{os.getpid()}.sqlite3"))

from fastapi import HTTPException
from starlette.requests import Request

from jarad_backend import routes
from jarad_backend.models import WebAuthnAuthenticateOptionsRequest, WebAuthnAuthenticateVerifyRequest


def authenticated_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 443),
            "scheme": "https",
        }
    )
    request.state.auth_actor = "session:test-session"
    return request


class WebAuthnRouteTests(unittest.TestCase):
    @patch.object(routes, "audit_event")
    @patch.object(routes, "enforce_rate_limit")
    @patch.object(routes, "finish_authentication")
    def test_verify_passes_authenticated_actor_to_verifier(self, finish_authentication, _rate_limit, _audit):
        finish_authentication.return_value = {
            "verified": True,
            "credentialId": "credential-id",
            "actionAuthToken": "action-token",
        }
        payload = WebAuthnAuthenticateVerifyRequest(
            challengeId="challenge-id",
            credential={"id": "credential-id"},
            actionId="stop-uptime-kuma",
            serviceId="uptime-kuma",
        )

        routes.webauthn_authenticate_verify(payload, authenticated_request())

        self.assertEqual(finish_authentication.call_args.kwargs["actor_id"], "session:test-session")

    @patch.object(routes, "audit_event")
    @patch.object(routes, "enforce_rate_limit")
    @patch.object(routes, "begin_authentication", side_effect=HTTPException(status_code=400, detail="test failure"))
    def test_options_failure_is_audited_without_unsupported_arguments(self, _begin, _rate_limit, audit_event):
        payload = WebAuthnAuthenticateOptionsRequest(actionId="stop-uptime-kuma", serviceId="uptime-kuma")

        with self.assertRaises(HTTPException):
            routes.webauthn_authenticate_options(payload, authenticated_request())

        self.assertNotIn("actor_id", audit_event.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
