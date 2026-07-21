from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("JARAD_APP_TOKEN", "test-token-with-sufficient-randomness")
os.environ.setdefault("JARAD_WEBAUTHN_ORIGIN", "https://app.example.com")
os.environ.setdefault("JARAD_WEBAUTHN_RP_ID", "example.com")
os.environ.setdefault("JARAD_ALLOWED_ORIGINS", "https://app.example.com")
os.environ.setdefault("JARAD_DB_PATH", os.path.join(tempfile.gettempdir(), f"jarad-dns-protection-{os.getpid()}.sqlite3"))

from jarad_backend import dns_access


class DnsAccessProtectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp_dir.cleanup)
        self.patches = [
            patch.object(dns_access, "DB_PATH", Path(self.temp_dir.name) / "jarad.sqlite3"),
            patch.object(dns_access, "DNS_ACCESS_LAN_SUBNET", "10.0.0.0/24"),
            patch.object(dns_access, "DNS_ACCESS_SERVER_IP", "10.0.0.10"),
            patch.object(dns_access, "DNS_ACCESS_PROTECTED_CLIENT_IPS", ("10.0.0.20", "10.0.0.21")),
        ]
        for active_patch in self.patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        dns_access.init()

    def test_protected_clients_are_permanently_approved(self) -> None:
        self.assertEqual(dns_access.approved_client_ips(), ["10.0.0.20", "10.0.0.21"])
        client = dns_access.get_client("10.0.0.20")
        self.assertIsNotNone(client)
        self.assertTrue(client["protected"])
        self.assertEqual(client["effectiveStatus"], "approved")
        self.assertIsNone(client["approvedUntil"])

    def test_protected_client_cannot_be_denied_or_revoked(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be denied"):
            dns_access.deny_client("10.0.0.20")
        with self.assertRaisesRegex(ValueError, "cannot be revoked"):
            dns_access.revoke_client("10.0.0.20")

    def test_protected_client_temporary_approval_stays_permanent(self) -> None:
        with patch.object(dns_access, "apply_firewall_rules", return_value={"applied": True}):
            client, _ = dns_access.approve_client("10.0.0.20", "2h")
        self.assertIsNone(client["approvedUntil"])
        self.assertEqual(client["effectiveStatus"], "approved")

    def test_unprotected_client_can_still_be_revoked(self) -> None:
        with patch.object(dns_access, "apply_firewall_rules", return_value={"applied": True}):
            dns_access.approve_client("10.0.0.30", "permanent")
            client, _ = dns_access.revoke_client("10.0.0.30")
        self.assertFalse(client["protected"])
        self.assertEqual(client["effectiveStatus"], "pending")


if __name__ == "__main__":
    unittest.main()
