from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("JARAD_APP_TOKEN", "test-token-with-sufficient-randomness")
os.environ.setdefault("JARAD_WEBAUTHN_ORIGIN", "https://app.example.com")
os.environ.setdefault("JARAD_WEBAUTHN_RP_ID", "example.com")
os.environ.setdefault("JARAD_ALLOWED_ORIGINS", "https://app.example.com")
os.environ.setdefault("JARAD_REDUCED_CREDENTIAL_METADATA", "1")
os.environ.setdefault("JARAD_DB_PATH", os.path.join(tempfile.gettempdir(), f"jarad-credential-privacy-{os.getpid()}.sqlite3"))

from jarad_backend import device_tokens, webauthn_auth


DEVICE_ROW = {
    "device_id": "device-id",
    "device_label": "Jordan Personal Phone",
    "created_at": "2026-07-01T10:00:00+00:00",
    "last_used_at": "2026-07-16T08:00:00+00:00",
    "revoked_at": None,
    "expires_at": "2026-10-01T10:00:00+00:00",
    "rotated_at": "2026-07-10T10:00:00+00:00",
    "remote_addr": "100.64.0.10",
    "user_agent": "Private handset user agent",
}


class CredentialPrivacyTests(unittest.TestCase):
    @patch.object(device_tokens.store, "list_device_tokens", return_value=[DEVICE_ROW])
    def test_device_list_uses_alias_and_hides_usage_metadata(self, _list_devices):
        device = device_tokens.list_device_tokens()[0]

        self.assertEqual(device["deviceLabel"], "Device 1")
        self.assertIsNone(device["createdAt"])
        self.assertIsNone(device["lastUsedAt"])
        self.assertIsNone(device["remoteAddr"])
        self.assertIsNone(device["userAgent"])
        self.assertEqual(device["expiresAt"], DEVICE_ROW["expires_at"])

    @patch.object(
        webauthn_auth.store,
        "list_credentials",
        return_value=[
            {
                "credential_id": "credential-id",
                "device_label": "Jordan Personal Phone passkey",
                "created_at": "2026-07-01T10:00:00+00:00",
                "last_used_at": "2026-07-16T08:00:00+00:00",
                "enabled": 1,
            }
        ],
    )
    def test_passkey_list_uses_alias_and_hides_timestamps(self, _list_credentials):
        credential = webauthn_auth.list_registered_credentials()[0]

        self.assertEqual(credential["deviceLabel"], "Passkey 1")
        self.assertIsNone(credential["createdAt"])
        self.assertIsNone(credential["lastUsedAt"])


if __name__ == "__main__":
    unittest.main()
