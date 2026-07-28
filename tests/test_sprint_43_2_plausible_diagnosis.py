"""Sprint 43.2 tests for deterministic Plausible traffic analysis."""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from core.database import Database
from core.plausible_diagnosis import (
    PlausibleDiagnosisService,
    build_plausible_diagnosis,
)


def metrics(previous: int, current: int, *, days: int = 56):
    start = date(2026, 1, 1)
    return [
        {
            "metric_date": (start + timedelta(days=index)).isoformat(),
            "visitors": previous if index < 28 else current,
        }
        for index in range(days)
    ]


class PlausibleDiagnosisUnitTests(unittest.TestCase):
    def test_significant_decline_uses_two_non_overlapping_periods(self):
        result = build_plausible_diagnosis(
            "example.dk", metrics(10, 6)
        )
        self.assertEqual("significant_decline", result["status"])
        self.assertEqual(280, result["previous_visitors"])
        self.assertEqual(168, result["current_visitors"])
        self.assertEqual(-112, result["visitor_change"])
        self.assertEqual(-40.0, result["visitor_change_percent"])
        self.assertEqual("2026-01-28", result["previous_period_end"])
        self.assertEqual("2026-01-29", result["period_start"])

    def test_growth_is_classified(self):
        result = build_plausible_diagnosis(
            "example.dk", metrics(10, 12)
        )
        self.assertEqual("growth", result["status"])

    def test_low_volume_is_insufficient(self):
        result = build_plausible_diagnosis(
            "example.dk", metrics(2, 1)
        )
        self.assertEqual("insufficient_data", result["status"])

    def test_small_decline_is_noise(self):
        rows = metrics(10, 10)
        rows[-1]["visitors"] = 0
        result = build_plausible_diagnosis("example.dk", rows)
        self.assertEqual("minor_decline", result["status"])

    def test_missing_day_rejects_incomplete_periods(self):
        rows = metrics(10, 6)
        del rows[20]
        result = build_plausible_diagnosis("example.dk", rows)
        self.assertEqual("missing_periods", result["status"])


class PlausibleDiagnosisPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.tempdir.name) / "test.db")
        self.database.initialize()
        self.database.upsert_website({
            "website": "example.dk",
            "display_name": "Example",
            "active": True,
            "monetized": True,
            "priority": "high",
            "primary_income_source": "affiliate",
            "niche": "test",
            "domain_age": "1",
            "notes": "",
            "status": "active",
        })
        for item in metrics(10, 6):
            self.database.upsert_plausible_daily_metric(
                website_id="example.dk",
                metric_date=item["metric_date"],
                visitors=item["visitors"],
            )

    def tearDown(self):
        self.database.close()
        self.tempdir.cleanup()

    def test_analysis_is_persisted_idempotently(self):
        service = PlausibleDiagnosisService(self.database)
        first = service.analyze_site("example.dk")
        second = service.analyze_site("example.dk")
        saved = self.database.get_latest_plausible_diagnosis("example.dk")
        self.assertEqual("created", first["write_action"])
        self.assertEqual("unchanged", second["write_action"])
        self.assertEqual("significant_decline", saved["status"])

    def test_missing_periods_are_not_persisted(self):
        result = PlausibleDiagnosisService(self.database).analyze_site(
            "missing.dk"
        )
        self.assertEqual("skipped", result["write_action"])
        self.assertIsNone(
            self.database.get_latest_plausible_diagnosis("missing.dk")
        )


if __name__ == "__main__":
    unittest.main()
