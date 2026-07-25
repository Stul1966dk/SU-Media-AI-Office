"""Sprint 40.2 tests for bounded, idempotent Plausible imports."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from core.data_refresh_service import DataRefreshService
from core.database import Database
from core.plausible_import import PlausibleImportService


class FakePlausible:
    def __init__(self, *, failing: set[str] | None = None) -> None:
        self.failing = failing or set()
        self.calls: list[str] = []

    def get_daily_visitors_range(
        self, website: str, _start: date, _end: date
    ) -> dict[str, int]:
        self.calls.append(website)
        if website in self.failing:
            raise RuntimeError("Plausible-fejl")
        return {
            "2026-06-28": 1,
            "2026-06-29": 2,
            "2026-06-30": 3,
        }


class PlausibleImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        for website, active, status in (
            ("a.dk", True, "active"),
            ("b.dk", True, "active"),
            ("inactive.dk", False, "inactive"),
            ("old.dk", True, "phasing_out"),
        ):
            self.database.upsert_website({
                "website": website, "display_name": website, "active": active,
                "monetized": False, "priority": "normal",
                "primary_income_source": "", "niche": "test",
                "domain_age": "", "notes": "", "status": status,
            })

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def test_known_data_is_saved_and_rerun_has_no_duplicates(self) -> None:
        connector = FakePlausible()
        service = PlausibleImportService(
            self.database, connector=connector, days=3
        )
        first = service.import_active_websites(date(2026, 7, 1))
        second = service.import_active_websites(date(2026, 7, 1))

        self.assertEqual(2, first["websites_attempted"])
        self.assertEqual(2, first["websites_updated"])
        self.assertEqual(6, first["datapoints_saved"])
        self.assertEqual(6, first["rows_created"])
        self.assertEqual(0, first["rows_updated"])
        self.assertEqual(6, len(self.database.get_plausible_daily_metrics()))
        self.assertEqual(0, second["rows_created"])
        self.assertEqual(6, second["rows_updated"])
        self.assertEqual(6, len(self.database.get_plausible_daily_metrics()))

    def test_one_website_failure_does_not_stop_the_rest(self) -> None:
        service = PlausibleImportService(
            self.database, connector=FakePlausible(failing={"a.dk"}), days=3
        )
        result = service.import_active_websites(date(2026, 7, 1))

        self.assertEqual(2, result["websites_attempted"])
        self.assertEqual(1, result["websites_updated"])
        self.assertEqual(1, result["websites_failed"])
        self.assertEqual("a.dk", result["errors"][0]["website"])
        self.assertEqual(3, result["datapoints_saved"])
        self.assertEqual(
            {"b.dk"},
            {
                row["website_id"]
                for row in self.database.get_plausible_daily_metrics()
            },
        )

    def test_refresh_order_and_dashboard_result_labels(self) -> None:
        self.assertLess(
            DataRefreshService.STEPS.index("Search Console-sider og søgeord"),
            DataRefreshService.STEPS.index("Plausible"),
        )
        dashboard_source = (
            Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
        ).read_text(encoding="utf-8")
        for label in (
            "Websites forsøgt", "Websites opdateret", "Datapunkter gemt",
            "Plausible-fejl pr. website",
        ):
            self.assertIn(label, dashboard_source)
        self.assertIn(
            "_refresh_status_label(plausible.get('status', ''))",
            dashboard_source,
        )


if __name__ == "__main__":
    unittest.main()
