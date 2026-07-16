from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("JARAD_APP_TOKEN", "test-token-with-sufficient-randomness")
os.environ.setdefault("JARAD_WEBAUTHN_ORIGIN", "https://app.example.com")
os.environ.setdefault("JARAD_WEBAUTHN_RP_ID", "example.com")
os.environ.setdefault("JARAD_ALLOWED_ORIGINS", "https://app.example.com")
os.environ.setdefault("JARAD_DB_PATH", os.path.join(tempfile.gettempdir(), f"jarad-device-lock-{os.getpid()}.sqlite3"))

from fastapi import Response
from starlette.requests import Request

from jarad_backend import routes


class DeviceLockTests(unittest.TestCase):
    @patch.object(routes, "audit_event")
    @patch.object(routes, "enforce_rate_limit")
    @patch.object(routes, "revoke_device_token", return_value=True)
    def test_lock_revokes_device_and_expires_cookie(self, revoke_device_token, _rate_limit, audit_event):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/auth/devices/current/lock",
                "headers": [],
                "client": ("127.0.0.1", 1234),
                "server": ("test", 443),
                "scheme": "https",
            }
        )
        request.state.auth_actor = "device:test-device"
        response = Response()

        result = routes.auth_device_lock(
            request=request,
            response=response,
            device={"device_id": "test-device"},
        )

        self.assertEqual(result, {"status": "locked"})
        revoke_device_token.assert_called_once_with("test-device")
        self.assertIn("jarad_device=", response.headers["set-cookie"])
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        audit_event.assert_called()


if __name__ == "__main__":
    unittest.main()
