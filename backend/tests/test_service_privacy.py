from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("JARAD_APP_TOKEN", "test-token-with-sufficient-randomness")
os.environ.setdefault("JARAD_WEBAUTHN_ORIGIN", "https://app.example.com")
os.environ.setdefault("JARAD_WEBAUTHN_RP_ID", "example.com")
os.environ.setdefault("JARAD_ALLOWED_ORIGINS", "https://app.example.com")
os.environ.setdefault("JARAD_REDUCED_SERVICE_METADATA", "1")
os.environ.setdefault("JARAD_DB_PATH", os.path.join(tempfile.gettempdir(), f"jarad-service-privacy-{os.getpid()}.sqlite3"))

from jarad_backend.services import public_service_metadata


class ServicePrivacyTests(unittest.TestCase):
    def test_reduced_metadata_hides_internal_container_and_image(self):
        public = public_service_metadata(
            {
                "id": "example",
                "container": "internal_container_name",
                "image": "registry.example/private/image:tag",
                "health": "degraded",
                "lastError": "internal dependency failed",
            }
        )

        self.assertEqual(public["id"], "example")
        self.assertEqual(public["container"], "Managed service")
        self.assertEqual(public["image"], "Image details hidden")
        self.assertEqual(public["lastError"], "Service needs attention")


if __name__ == "__main__":
    unittest.main()
