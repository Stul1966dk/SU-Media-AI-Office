"""Sprint 6 tests for property-specific Search Console dimension throttling."""

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from core.database import Database
from core.search_console_service import SearchConsoleService
from core.website_registry import WebsiteRegistry


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


class DimensionConnector:
    def __init__(self, failing_site: str | None = None) -> None:
        self.failing_site = failing_site
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def get_search_analytics_dimensions(
        self, site_url: str, _start: str, _end: str,
        dimensions: list[str], _limit: int,
    ) -> list[dict]:
        self.calls.append((site_url, tuple(dimensions)))
        if site_url == self.failing_site:
            raise RuntimeError("dimension API failed")
        return [{
            "page_url": f"{site_url}side/" if "page" in dimensions else None,
            "query": "query" if "query" in dimensions else None,
            "clicks": 1, "impressions": 10, "ctr": 0.1,
            "average_position": 2.0,
        }]


class Sprint6DimensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        for website in ("a.dk", "b.dk", "c.dk"):
            self.database.upsert_website({
                "website": website, "display_name": website, "active": True,
                "monetized": True, "priority": "medium",
                "primary_income_source": "affiliate", "niche": "test",
                "domain_age": "1", "notes": "", "status": "active",
            })
            self.database.upsert_search_console_property(
                site_url=f"https://{website}/",
                permission_level="siteOwner",
                website_id=website,
                active=True,
            )

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def service(
        self, connector: DimensionConnector | None = None
    ) -> tuple[SearchConsoleService, DimensionConnector]:
        connector = connector or DimensionConnector()
        return (
            SearchConsoleService(
                connector, self.database, WebsiteRegistry(self.database)
            ),
            connector,
        )

    def set_success(self, website: str, when: datetime) -> None:
        self.database.set_search_console_dimension_state(
            f"https://{website}/",
            {"last_attempt": when.isoformat(), "last_success": when.isoformat()},
        )

    def test_first_import_runs_six_calls_and_persists_success(self) -> None:
        service, connector = self.service()
        result = service.sync_dimensions(
            website_ids=["a.dk"], reference_date=date(2026, 8, 3),
            reference_time=NOW,
        )
        detail = result.property_results[0]
        self.assertEqual("ingen tidligere dimensionsimport", detail["reason"])
        self.assertEqual(6, result.api_calls_executed)
        self.assertEqual(0, result.api_calls_avoided)
        self.assertEqual(NOW.isoformat(), detail["last_success_after"])
        self.assertEqual(6, len(connector.calls))

    def test_recent_success_skips_without_calls_or_timestamp_change(self) -> None:
        previous = NOW - timedelta(hours=2)
        self.set_success("a.dk", previous)
        service, connector = self.service()
        result = service.sync_dimensions(
            website_ids=["a.dk"], reference_time=NOW
        )
        self.assertEqual("skipped", result.overall_status)
        self.assertEqual(1, result.properties_skipped)
        self.assertEqual(0, result.api_calls_executed)
        self.assertEqual(6, result.api_calls_avoided)
        self.assertEqual(previous.isoformat(), (
            result.property_results[0]["last_success_after"]
        ))
        self.assertEqual([], connector.calls)

    def test_expired_and_failed_previous_attempt_run(self) -> None:
        self.set_success("a.dk", NOW - timedelta(hours=25))
        self.database.set_search_console_dimension_state(
            "https://b.dk/",
            {"last_attempt": (NOW - timedelta(hours=1)).isoformat(),
             "last_error": (NOW - timedelta(hours=1)).isoformat()},
        )
        service, _ = self.service()
        result = service.sync_dimensions(
            website_ids=["a.dk", "b.dk"], reference_time=NOW
        )
        reasons = {
            item["website_id"]: item["reason"]
            for item in result.property_results
        }
        self.assertEqual(
            "mere end 24 timer siden seneste succes", reasons["a.dk"]
        )
        self.assertEqual("ingen tidligere dimensionsimport", reasons["b.dk"])
        self.assertEqual(12, result.api_calls_executed)

    def test_properties_are_evaluated_separately_and_calls_are_saved(self) -> None:
        self.set_success("b.dk", NOW - timedelta(hours=1))
        self.set_success("c.dk", NOW - timedelta(hours=25))
        service, _ = self.service()
        result = service.sync_dimensions(reference_time=NOW)
        statuses = {
            item["website_id"]: item["status"]
            for item in result.property_results
        }
        self.assertEqual(
            {"a.dk": "completed", "b.dk": "skipped", "c.dk": "completed"},
            statuses,
        )
        self.assertEqual(12, result.api_calls_executed)
        self.assertEqual(6, result.api_calls_avoided)

    def test_new_daily_rows_trigger_but_overlap_updates_do_not(self) -> None:
        self.set_success("a.dk", NOW - timedelta(hours=1))
        service, _ = self.service()
        triggered = service.sync_dimensions(
            website_ids=["a.dk"], reference_time=NOW,
            new_daily_website_ids={"a.dk"},
        )
        self.assertEqual(
            "nye Search Console-dagstal",
            triggered.property_results[0]["reason"],
        )
        later = NOW + timedelta(minutes=1)
        skipped = service.sync_dimensions(
            website_ids=["a.dk"], reference_time=later,
            new_daily_website_ids=set(),
        )
        self.assertEqual("skipped", skipped.property_results[0]["status"])

    def test_active_experiment_and_force_override_recent_success(self) -> None:
        self.set_success("a.dk", NOW - timedelta(hours=1))
        service, _ = self.service()
        original = self.database.get_seo_experiments
        self.database.get_seo_experiments = Mock(return_value=[
            {"website_id": "a.dk", "status": "waiting_for_data"}
        ])
        try:
            experiment = service.sync_dimensions(
                website_ids=["a.dk"], reference_time=NOW
            )
        finally:
            self.database.get_seo_experiments = original
        self.assertEqual(
            "aktivt SEO-eksperiment",
            experiment.property_results[0]["reason"],
        )
        forced = service.sync_dimensions(
            website_ids=["a.dk"], reference_time=NOW,
            force_dimensions_refresh=True,
        )
        self.assertEqual(
            "tvungen opdatering", forced.property_results[0]["reason"]
        )

    def test_filter_and_global_scope(self) -> None:
        service, _ = self.service()
        filtered = service.sync_dimensions(
            website_ids=["b.dk"], reference_time=NOW
        )
        self.assertEqual(
            ["b.dk"],
            [item["website_id"] for item in filtered.property_results],
        )
        global_result = service.sync_dimensions(
            website_ids=None, reference_time=NOW,
            force_dimensions_refresh=True,
        )
        self.assertEqual(3, global_result.properties_evaluated)

    def test_one_property_failure_does_not_block_success_or_save_success(self) -> None:
        connector = DimensionConnector(failing_site="https://a.dk/")
        service, _ = self.service(connector)
        result = service.sync_dimensions(
            website_ids=["a.dk", "b.dk"], reference_time=NOW
        )
        self.assertEqual("completed_with_warnings", result.overall_status)
        self.assertEqual(1, result.properties_failed)
        self.assertEqual(12, result.api_calls_executed)
        self.assertNotIn(
            "last_success",
            self.database.get_search_console_dimension_state("https://a.dk/"),
        )
        self.assertEqual(
            NOW.isoformat(),
            self.database.get_search_console_dimension_state(
                "https://b.dk/"
            )["last_success"],
        )

    def test_three_recent_properties_avoid_eighteen_calls(self) -> None:
        for website in ("a.dk", "b.dk", "c.dk"):
            self.set_success(website, NOW - timedelta(hours=1))
        service, connector = self.service()
        result = service.sync_dimensions(reference_time=NOW)
        self.assertEqual(3, result.properties_skipped)
        self.assertEqual(0, result.api_calls_executed)
        self.assertEqual(18, result.api_calls_avoided)
        self.assertEqual([], connector.calls)


if __name__ == "__main__":
    unittest.main()
