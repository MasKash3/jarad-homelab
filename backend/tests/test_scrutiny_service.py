from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("JARAD_APP_TOKEN", "test-token-with-sufficient-randomness")
os.environ.setdefault("JARAD_WEBAUTHN_ORIGIN", "https://app.example.com")
os.environ.setdefault("JARAD_WEBAUTHN_RP_ID", "example.com")
os.environ.setdefault("JARAD_ALLOWED_ORIGINS", "https://app.example.com")
os.environ.setdefault("JARAD_DB_PATH", os.path.join(tempfile.gettempdir(), f"jarad-scrutiny-{os.getpid()}.sqlite3"))

from jarad_backend.config import SERVICES
from jarad_backend.docker import allowed_containers, is_allowed_action
from jarad_backend.services import diagnostics_for


class ScrutinyServiceTests(unittest.TestCase):
    def test_scrutiny_is_explicitly_catalogued_and_managed(self):
        service = SERVICES["scrutiny"]
        helper = (Path(__file__).parents[2] / "scripts" / "server" / "jarad-docker").read_text(encoding="utf-8")

        self.assertEqual(service["container"], "scrutiny")
        self.assertEqual(service["image"], "ghcr.io/analogj/scrutiny:v0.9.2-omnibus")
        self.assertEqual(service["healthy_label"], "Monitor online")
        self.assertIn("scrutiny", allowed_containers())
        self.assertIn('"scrutiny"', helper)
        self.assertTrue(is_allowed_action("scrutiny", "restart"))
        self.assertFalse(is_allowed_action("scrutiny", "exec"))

    def test_scrutiny_diagnostics_do_not_claim_drive_health(self):
        diagnostics = diagnostics_for("scrutiny", running=True, health="healthy", docker_unavailable=False)

        self.assertIn(
            [
                "Drive SMART health",
                "Unchecked here; open Scrutiny for disk-specific health and history",
            ],
            diagnostics,
        )


if __name__ == "__main__":
    unittest.main()
