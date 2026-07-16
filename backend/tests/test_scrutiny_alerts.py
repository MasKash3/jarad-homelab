from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("JARAD_APP_TOKEN", "test-token-with-sufficient-randomness")
os.environ.setdefault("JARAD_WEBAUTHN_ORIGIN", "https://app.example.com")
os.environ.setdefault("JARAD_WEBAUTHN_RP_ID", "example.com")
os.environ.setdefault("JARAD_ALLOWED_ORIGINS", "https://app.example.com")
os.environ.setdefault("JARAD_DB_PATH", os.path.join(tempfile.gettempdir(), f"jarad-scrutiny-alerts-{os.getpid()}.sqlite3"))

from jarad_backend import routes
from jarad_backend.config import loopback_http_url
from jarad_backend.scrutiny import alerts_from_summary, snapshot_from_summary
from jarad_backend.services import alerts_for


def scrutiny_payload(status: int = 0, collector_date: str = "2026-07-16T20:00:00Z") -> dict:
    return {
        "success": True,
        "data": {
            "summary": {
                "disk-id": {
                    "device": {
                        "archived": False,
                        "device_status": status,
                        "device_name": "/dev/sdz",
                        "model_name": "Example Disk",
                        "capacity": 2_000_000_000_000,
                        "device_protocol": "ATA",
                        "serial_number": "PRIVATE-SERIAL",
                    },
                    "smart": {
                        "collector_date": collector_date,
                        "temp": 31,
                        "power_on_hours": 12345,
                    },
                }
            }
        },
    }


class ScrutinyAlertTests(unittest.TestCase):
    def test_failed_status_becomes_active_jarad_alert_without_serial(self):
        snapshot = snapshot_from_summary(
            scrutiny_payload(status=3),
            now=datetime(2026, 7, 16, 21, 0, tzinfo=timezone.utc),
        )
        alerts = snapshot["alerts"]

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["state"], "bad")
        self.assertEqual(alerts[0]["title"], "Disk health alert: Example Disk")
        self.assertIn("SMART reports a failure", alerts[0]["body"])
        self.assertIn("Scrutiny's failure threshold was exceeded", alerts[0]["body"])
        self.assertNotIn("PRIVATE-SERIAL", str(alerts))
        self.assertEqual(snapshot["items"][0]["state"], "bad")
        self.assertEqual(snapshot["items"][0]["statusLabel"], "SMART + Scrutiny failure")
        self.assertNotIn("PRIVATE-SERIAL", str(snapshot["items"]))

    def test_healthy_fresh_summary_adds_no_alert(self):
        snapshot = snapshot_from_summary(
            scrutiny_payload(),
            now=datetime(2026, 7, 16, 21, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(snapshot["alerts"], [])
        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["summary"], {"healthy": 1, "warning": 0, "critical": 0})
        self.assertEqual(
            snapshot["items"][0],
            {
                "label": "Example Disk",
                "deviceName": "/dev/sdz",
                "model": "Example Disk",
                "interface": "ATA",
                "capacityBytes": 2_000_000_000_000,
                "temperatureC": 31,
                "powerOnHours": 12345,
                "lastCollectedAt": "2026-07-16T20:00:00Z",
                "state": "good",
                "statusLabel": "Healthy",
            },
        )

    def test_stale_summary_becomes_warning(self):
        snapshot = snapshot_from_summary(
            scrutiny_payload(collector_date="2026-07-14T20:00:00Z"),
            now=datetime(2026, 7, 16, 21, 0, tzinfo=timezone.utc),
        )
        alerts = snapshot["alerts"]

        self.assertEqual(alerts[0]["state"], "warn")
        self.assertEqual(alerts[0]["title"], "Disk health data is stale")
        self.assertEqual(snapshot["items"][0]["state"], "warn")
        self.assertEqual(snapshot["items"][0]["statusLabel"], "Data stale")

    def test_invalid_summary_reports_unavailable(self):
        alerts = alerts_from_summary({"success": True, "data": {}})

        self.assertEqual(alerts[0]["title"], "Disk monitoring data unavailable")

    def test_invalid_device_status_does_not_silently_look_healthy(self):
        payload = scrutiny_payload()
        payload["data"]["summary"]["disk-id"]["device"]["device_status"] = "unexpected"

        alerts = alerts_from_summary(payload)

        self.assertEqual(alerts[0]["title"], "Disk monitoring data unavailable")

    def test_scrutiny_api_url_is_restricted_to_loopback(self):
        self.assertEqual(
            loopback_http_url(
                "http://127.0.0.1:8080/api/summary",
                "TEST_URL",
                "/api/summary",
            ),
            "http://127.0.0.1:8080/api/summary",
        )
        with self.assertRaises(RuntimeError):
            loopback_http_url(
                "https://scrutiny.example.com/api/summary",
                "TEST_URL",
                "/api/summary",
            )

    def test_disk_alerts_are_included_in_existing_alert_feed(self):
        disk_alert = {
            "state": "bad",
            "title": "Disk health alert: Example Disk",
            "time": "Active",
            "body": "SMART reports a failure.",
        }

        alerts = alerts_for([], 10, "Healthy", [disk_alert])

        self.assertEqual(alerts, [disk_alert])

    def test_mobile_state_surfaces_disk_alert_and_reduces_health_score(self):
        disk_alert = {
            "state": "bad",
            "title": "Disk health alert: Example Disk",
            "time": "Active",
            "body": "SMART reports a failure.",
        }
        services = [{"id": "scrutiny", "health": "healthy"}]
        drive_snapshot = {
            "available": True,
            "state": "bad",
            "message": "1 of 1 monitored drives needs attention.",
            "summary": {"healthy": 0, "warning": 0, "critical": 1},
            "items": [
                {
                    "id": "disk-id",
                    "label": "Example Disk",
                    "state": "bad",
                    "statusLabel": "SMART failure",
                }
            ],
            "alerts": [disk_alert],
        }

        with (
            patch.object(routes, "read_disk", return_value=(10, "10% used")),
            patch.object(routes, "read_backup_state", return_value={"state": "Healthy", "cloud": "Healthy"}),
            patch.object(routes, "build_services", return_value=services),
            patch.object(routes, "scrutiny_snapshot", return_value=drive_snapshot),
            patch.object(routes, "read_temp_c", return_value=40),
            patch.object(routes, "read_cpu_pct", return_value=10),
            patch.object(routes, "read_ram_pct", return_value=20),
            patch.object(routes, "read_uptime", return_value="1 day"),
            patch.object(routes, "read_raid_state", return_value="Healthy"),
            patch.object(routes, "recent_logs", return_value=[]),
            patch.object(routes, "network_state", return_value=[]),
        ):
            state = routes.mobile_state()

        self.assertEqual(state["server"]["status"], "Attention needed")
        self.assertEqual(state["server"]["healthScore"], 80)
        self.assertIn(disk_alert, state["alerts"])
        self.assertEqual(state["drives"]["summary"]["critical"], 1)
        self.assertNotIn("alerts", state["drives"])


if __name__ == "__main__":
    unittest.main()
