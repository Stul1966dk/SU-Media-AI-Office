"""Sprint 40.2 tests for bounded, idempotent Plausible imports."""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

from connectors.plausible_connector import PlausibleConnectorError
from core.data_refresh_service import DataRefreshService
from core.database import Database
from core.plausible_import import PlausibleImportService


class FakePlausible:
    def __init__(self, *, failing: set[str] | None = None) -> None:
        self.failing = failing or set()
        self.calls: list[tuple[str, date, date]] = []

    def get_daily_visitors_range(
        self, website: str, start: date, end: date
    ) -> dict[str, int]:
        self.calls.append((website, start, end))
        if website in self.failing:
            raise PlausibleConnectorError("Plausible afviste API-tokenet.")
        return {
            "2026-06-28": 1,
            "2026-06-29": 2,
            "2026-06-30": 3,
        }


class RangePlausible(FakePlausible):
    def get_daily_visitors_range(
        self, website: str, start: date, end: date
    ) -> dict[str, int]:
        self.calls.append((website, start, end))
        if website in self.failing:
            raise PlausibleConnectorError("Plausible afviste API-tokenet.")
        current = start
        result = {}
        while current <= end:
            result[current.isoformat()] = current.day
            current += timedelta(days=1)
        return result


class PlausibleImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        for website, active, status in (
            ("a.dk", True, "active"),
            ("b.dk", True, "active"),
            ("missing", True, "active"),
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

        self.assertEqual(5, first["websites_evaluated"])
        self.assertEqual(2, first["websites_attempted"])
        self.assertEqual(3, first["websites_skipped"])
        self.assertEqual(2, first["websites_updated"])
        self.assertEqual(6, first["datapoints_saved"])
        self.assertEqual(6, first["rows_created"])
        self.assertEqual(0, first["rows_updated"])
        self.assertEqual(6, len(self.database.get_plausible_daily_metrics()))
        self.assertEqual(0, second["rows_created"])
        self.assertEqual(6, second["rows_updated"])
        self.assertEqual(6, len(self.database.get_plausible_daily_metrics()))

    def test_first_import_uses_56_completed_days(self) -> None:
        connector = RangePlausible()
        result = PlausibleImportService(
            self.database, connector=connector
        ).import_active_websites(
            date(2026, 7, 25),
            website_ids=["a.dk"],
            force_full_refresh=False,
        )
        self.assertEqual(
            [("a.dk", date(2026, 5, 30), date(2026, 7, 24))],
            connector.calls,
        )
        self.assertEqual("full", result["import_mode"])
        self.assertEqual("2026-05-30", result["earliest_fetched_date"])
        self.assertEqual("2026-07-24", result["latest_fetched_date"])
        self.assertEqual(56, result["rows_created"])
        self.assertEqual(
            56,
            len(self.database.get_plausible_daily_metrics(
                website_id="a.dk"
            )),
        )

    def test_short_history_is_backfilled_per_website(self) -> None:
        for website, metric_date in (
            ("a.dk", "2026-07-24"), ("b.dk", "2026-07-20")
        ):
            self.database.upsert_plausible_daily_metric(
                website_id=website, metric_date=metric_date, visitors=1
            )
        connector = RangePlausible()
        result = PlausibleImportService(
            self.database, connector=connector
        ).import_active_websites(
            date(2026, 7, 25),
            force_full_refresh=False,
            website_ids=["a.dk", "b.dk"],
        )
        self.assertEqual(
            [
                ("a.dk", date(2026, 5, 30), date(2026, 7, 24)),
                ("b.dk", date(2026, 5, 30), date(2026, 7, 24)),
            ],
            connector.calls,
        )
        self.assertEqual("full", result["import_mode"])
        self.assertEqual("2026-05-30", result["earliest_fetched_date"])
        self.assertEqual(110, result["rows_created"])
        self.assertEqual(2, result["rows_updated"])
        self.assertEqual(
            112, len(self.database.get_plausible_daily_metrics())
        )

    def test_force_full_refresh_uses_56_days_and_upserts(self) -> None:
        self.database.upsert_plausible_daily_metric(
            website_id="a.dk", metric_date="2026-07-24", visitors=1
        )
        connector = RangePlausible()
        result = PlausibleImportService(
            self.database, connector=connector
        ).import_active_websites(
            date(2026, 7, 25),
            website_ids=["a.dk"],
            force_full_refresh=True,
        )
        self.assertEqual(
            [("a.dk", date(2026, 5, 30), date(2026, 7, 24))],
            connector.calls,
        )
        self.assertEqual("full", result["import_mode"])
        self.assertEqual(55, result["rows_created"])
        self.assertEqual(1, result["rows_updated"])
        self.assertEqual(
            56,
            len(self.database.get_plausible_daily_metrics(
                website_id="a.dk"
            )),
        )

    def test_missing_site_id_and_inactive_websites_are_skipped(self) -> None:
        connector = FakePlausible()
        result = PlausibleImportService(
            self.database, connector=connector, days=3
        ).import_active_websites(date(2026, 7, 1))
        skipped = {
            item["website_id"]: item
            for item in result["website_results"]
            if item["status"] == "skipped"
        }
        self.assertEqual(
            "Plausible-site-id mangler", skipped["missing"]["reason"]
        )
        self.assertEqual(
            "Website er inaktivt", skipped["inactive.dk"]["reason"]
        )
        self.assertEqual(
            "Website er inaktivt", skipped["old.dk"]["reason"]
        )
        self.assertEqual(
            {"a.dk", "b.dk"},
            {website for website, _start, _end in connector.calls},
        )

    def test_explicitly_disabled_plausible_is_skipped(self) -> None:
        configuration = PlausibleImportService._configuration({
            "website": "a.dk",
            "active": True,
            "status": "active",
            "plausible_enabled": False,
            "plausible_site_id": "a.dk",
        })
        self.assertEqual(
            "Plausible er ikke aktiveret",
            configuration["skip_reason"],
        )

    def test_missing_plausible_integration_is_skipped_not_failed(
        self,
    ) -> None:
        connector = FakePlausible()
        connector.get_daily_visitors_range = Mock(
            side_effect=PlausibleConnectorError(
                "Plausible kunne ikke finde statistik for det valgte website."
            )
        )
        result = PlausibleImportService(
            self.database, connector=connector, days=3
        ).import_active_websites(
            date(2026, 7, 1), website_ids=["a.dk"]
        )
        self.assertEqual(1, result["websites_skipped"])
        self.assertEqual(0, result["websites_processed"])
        self.assertEqual(0, result["websites_failed"])
        self.assertEqual("skipped", result["overall_status"])
        self.assertEqual(
            "Plausible er ikke aktiveret",
            result["website_results"][0]["reason"],
        )

    def test_website_filter_only_processes_selected_website(self) -> None:
        connector = FakePlausible()
        result = PlausibleImportService(
            self.database, connector=connector, days=3
        ).import_active_websites(
            date(2026, 7, 1),
            website_ids=["b.dk"],
            force_full_refresh=False,
        )
        self.assertEqual(1, result["websites_evaluated"])
        self.assertEqual(
            ["b.dk"],
            [website for website, _start, _end in connector.calls],
        )

    def test_one_website_failure_does_not_stop_the_rest(self) -> None:
        service = PlausibleImportService(
            self.database, connector=FakePlausible(failing={"a.dk"}), days=3
        )
        result = service.import_active_websites(date(2026, 7, 1))

        self.assertEqual(2, result["websites_attempted"])
        self.assertEqual(1, result["websites_updated"])
        self.assertEqual(1, result["websites_failed"])
        self.assertEqual("a.dk", result["errors"][0]["website"])
        self.assertEqual(
            "PlausibleConnectorError",
            result["errors"][0]["error_type"],
        )
        self.assertEqual(
            "Plausible afviste API-tokenet.",
            result["errors"][0]["message"],
        )
        self.assertEqual(
            "completed_with_warnings", result["overall_status"]
        )
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
