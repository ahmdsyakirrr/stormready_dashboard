"""Behavioural checks for evidence integrity and missing-data handling."""

import csv
import io
import tempfile
import unittest
from pathlib import Path

from app import create_app
from simulator import make_packet


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "simulation.sqlite3"
        self.now = 1_800_000_000.0
        self.app = create_app(database_path=self.path, clock=lambda: self.now)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.folder.cleanup()

    def packet(self, sequence=0, scenario="normal", boot="test-boot"):
        return make_packet(sequence, boot, sequence * 1000, scenario)

    def send(self, sequence=0, scenario="normal", boot="test-boot", **changes):
        payload = self.packet(sequence, scenario, boot)
        payload.update(changes)
        return self.client.post("/api/readings", json=payload)

    def status(self):
        return self.client.get("/api/status").get_json()

    def test_empty_database_is_unknown_not_zero_or_safe(self):
        status = self.status()
        self.assertIsNone(status["latest"])
        self.assertEqual(status["summary"]["connection"], "waiting")
        self.assertEqual(status["summary"]["water_state"], "unknown")
        self.assertIsNone(status["summary"]["coverage_percent"])

    def test_current_reading_and_persistence_after_restart(self):
        self.assertEqual(self.send().status_code, 201)
        restarted = create_app(database_path=self.path, clock=lambda: self.now).test_client()
        status = restarted.get("/api/status").get_json()
        self.assertEqual(status["summary"]["total_readings"], 1)
        self.assertEqual(status["latest"]["upstream_quality"], "good")
        self.assertEqual(status["summary"]["water_state"], "below_threshold")

    def test_lost_packets_become_offline_and_coverage_falls(self):
        self.send()
        self.now += 11
        status = self.status()
        self.assertEqual(status["summary"]["connection"], "offline")
        self.assertEqual(status["summary"]["water_state"], "unknown")
        self.assertEqual(status["latest"]["upstream_current_quality"], "offline")
        self.assertLess(status["summary"]["coverage_percent"], 10)

    def test_invalid_sensor_is_preserved_and_cannot_be_safe(self):
        self.assertEqual(self.send(scenario="sensor-fault").status_code, 201)
        status = self.status()
        self.assertIsNone(status["latest"]["upstream_mm"])
        self.assertEqual(status["summary"]["water_state"], "unknown")
        self.assertEqual(status["latest"]["downstream_quality"], "good")
        self.assertEqual(status["summary"]["coverage_percent"], 0)

    def test_implausible_value_is_stored_as_invalid_evidence(self):
        self.send(scenario="out-of-range")
        latest = self.status()["latest"]
        self.assertEqual(latest["upstream_mm"], 300)
        self.assertEqual(latest["upstream_quality"], "out_of_range")
        self.assertEqual(self.status()["summary"]["water_state"], "unknown")

    def test_old_sample_in_new_packet_is_unreliable(self):
        self.send(scenario="stale-sample")
        status = self.status()
        self.assertEqual(status["summary"]["connection"], "online")
        self.assertEqual(status["latest"]["upstream_quality"], "stale_sample")
        self.assertEqual(status["summary"]["water_state"], "unknown")

    def test_high_water_requires_five_seconds_of_evidence(self):
        for index in range(5):
            self.now = 1_800_000_000 + index
            self.send(index, "high-water")
        self.assertEqual(self.status()["summary"]["water_state"], "confirming")
        self.now += 1
        self.send(5, "high-water")
        self.assertEqual(self.status()["summary"]["water_state"], "high_water")

    def test_gap_restarts_confirmation(self):
        self.send(0, "high-water")
        self.now += 8
        self.send(8, "high-water")
        self.assertEqual(self.status()["summary"]["water_state"], "confirming")
        self.assertEqual(self.status()["summary"]["confirmation_seconds"], 0)

    def test_downstream_fault_does_not_hide_upstream_high_water(self):
        for index in range(6):
            self.now = 1_800_000_000 + index
            self.send(index, "high-water", downstream_mm=None, downstream_valid=False)
        status = self.status()
        self.assertEqual(status["summary"]["water_state"], "high_water")
        self.assertEqual(status["summary"]["coverage_percent"], 0)

    def test_high_water_hysteresis_and_clear(self):
        for index in range(6):
            self.now = 1_800_000_000 + index
            self.send(index, "high-water")
        self.now += 1
        self.send(6, upstream_mm=95)
        self.assertEqual(self.status()["summary"]["water_state"], "high_water")
        self.now += 1
        self.send(7, upstream_mm=85)
        self.assertEqual(self.status()["summary"]["water_state"], "below_threshold")

    def test_high_water_state_survives_history_window_and_restart(self):
        for index in range(140):
            self.now = 1_800_000_000 + index
            self.send(index, upstream_mm=112 if index < 6 else 95)
        restarted = create_app(database_path=self.path, clock=lambda: self.now).test_client()
        status = restarted.get("/api/status").get_json()
        self.assertEqual(status["summary"]["water_state"], "high_water")
        self.assertTrue(all(row["upstream_mm"] == 95 for row in status["history"]))

    def test_retry_is_idempotent_and_does_not_refresh_packet_age(self):
        self.send()
        self.now += 11
        self.assertEqual(self.send().status_code, 200)
        status = self.status()
        self.assertEqual(status["summary"]["total_readings"], 1)
        self.assertEqual(status["summary"]["connection"], "offline")

    def test_conflicting_sequence_is_rejected(self):
        self.send()
        self.assertEqual(self.send(upstream_mm=80).status_code, 409)
        self.assertEqual(self.status()["summary"]["total_readings"], 1)

    def test_out_of_order_and_old_boot_are_rejected(self):
        self.send(2)
        self.assertEqual(self.send(1).status_code, 409)
        self.assertEqual(self.send(0, boot="new-boot").status_code, 201)
        self.assertEqual(self.send(3).status_code, 409)

    def test_new_boot_restarts_high_water_confirmation(self):
        for index in range(6):
            self.now = 1_800_000_000 + index
            self.send(index, "high-water")
        self.now += 1
        self.send(0, "high-water", boot="new-boot")
        self.assertEqual(self.status()["summary"]["water_state"], "confirming")

    def test_zero_level_is_a_valid_measurement(self):
        self.send(upstream_mm=0, downstream_mm=0)
        self.assertEqual(self.status()["latest"]["upstream_quality"], "good")
        self.assertEqual(self.status()["latest"]["upstream_mm"], 0)

    def test_strict_packet_validation(self):
        cases = [
            {"upstream_valid": "false"}, {"sequence": True}, {"upstream_mm": "45"},
            {"upstream_mm": float("nan")}, {"downstream_mm": float("inf")},
            {"source": "esp32"}, {"schema_version": True}, {"device_id": "other-device"},
            {"boot_id": "=BAD"}, {"sample_age_ms": -1}, {"sequence": -1},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.send(**changes).status_code, 400)
        payload = self.packet()
        del payload["upstream_valid"]
        self.assertEqual(self.client.post("/api/readings", json=payload).status_code, 400)
        self.assertEqual(self.client.post("/api/readings", json=[]).status_code, 400)
        self.assertEqual(self.client.post("/api/readings", data="{}").status_code, 415)
        self.assertEqual(self.status()["summary"]["total_readings"], 0)

    def test_hardware_mode_has_separate_source_and_database(self):
        self.send()
        hardware_path = Path(self.folder.name) / "hardware.sqlite3"
        hardware = create_app("hardware", hardware_path, lambda: self.now).test_client()
        self.assertEqual(hardware.get("/api/status").get_json()["summary"]["total_readings"], 0)
        self.assertEqual(hardware.post("/api/readings", json=self.packet()).status_code, 400)
        payload = self.packet()
        payload["source"] = "esp32"
        self.assertEqual(hardware.post("/api/readings", json=payload).status_code, 201)
        with self.assertRaises(ValueError):
            create_app("hardware", self.path)

    def test_export_retains_source_quality_and_utc_times(self):
        self.send(scenario="out-of-range")
        response = self.client.get("/api/export.csv")
        rows = list(csv.DictReader(io.StringIO(response.data.decode())))
        self.assertEqual(rows[0]["source"], "simulator")
        self.assertEqual(rows[0]["upstream_quality"], "out_of_range")
        self.assertEqual(rows[0]["upstream_mm"], "300.0")
        self.assertTrue(rows[0]["received_at_utc"].endswith("+00:00"))
        self.assertIn("simulation", response.headers["Content-Disposition"])

    def test_cycle_packets_exercise_all_scenarios_without_losing_history(self):
        for index in range(80):
            self.now = 1_800_000_000 + index
            self.assertEqual(self.send(index, "cycle").status_code, 201)
        status = self.status()
        self.assertEqual(status["summary"]["total_readings"], 80)
        self.assertEqual(status["summary"]["window_valid_pairs"], 60)
        self.assertEqual(status["summary"]["water_state"], "below_threshold")

    def test_dashboard_and_static_assets_are_served_without_cdns(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertIn("SIMULATION", html)
        self.assertNotIn("https://", html)
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        for path in ("/static/style.css", "/static/dashboard.js", "/static/mark.svg", "/api/health"):
            with self.client.get(path) as asset_response:
                self.assertEqual(asset_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
