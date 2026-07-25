"""Sprint 27 central refresh and website briefing tests."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.data_refresh_service import DataRefreshService
from core.database import Database
from core.search_console_service import (
    SearchConsoleDataSyncResult, SearchConsoleDimensionSyncResult,
    SearchConsoleSyncResult,
)
from core.website_registry import ImportResult
from agents.website_intelligence import WebsiteIntelligenceBatchResult
from agents.website_intelligence import WebsiteIntelligenceResult
from core.seo_history import SEOHealth
from dashboard.components.briefing_readiness import (
    get_website_briefing_readiness,
)


class DataRefreshServiceTests(unittest.TestCase):
    def _service(self, *, search_failure: bool = False) -> DataRefreshService:
        database = Mock()
        database.get_active_website_ids.return_value = ["a.dk", "b.dk"]
        database.get_seo_experiments.return_value = []
        database.get_priority_task_scores.return_value = []
        registry = Mock()
        registry.sync.return_value = ImportResult(
            total=2, created=0, updated=2, phased_out=0
        )
        search = Mock()
        if search_failure:
            search.synchronize.side_effect = RuntimeError("Search fejlede")
        else:
            search.synchronize.return_value = SearchConsoleSyncResult(
                connection_ok=True, total=2, matched=2, unmatched=0,
                properties=[], error=None,
            )
        search.sync_all_properties.return_value = SearchConsoleDataSyncResult(
            properties_processed=2, properties_failed=0,
            rows_created=3, rows_updated=4, start_date="2026-01-01",
            end_date="2026-02-01",
            earliest_fetched_date="2026-01-01",
            latest_fetched_date="2026-02-01",
            import_mode="incremental", errors=[],
        )
        search.sync_dimensions.return_value = SearchConsoleDimensionSyncResult(
            properties_processed=2, properties_failed=0, page_rows=10,
            query_rows=20, page_query_rows=30, rows_created=60,
            rows_updated=0, errors=[],
        )
        seo = Mock()
        seo.analyze_all_sites.return_value = [
            Mock(website="a.dk"), Mock(website="a.dk"), Mock(website="b.dk")
        ]
        seo.analyze_site.return_value = [
            SEOHealth(
                website="a.dk", period="28d", click_change_pct=0,
                impression_change_pct=0, ctr_change=0, position_change=0,
                trend="stable", score=50, action="unchanged",
            )
        ]
        intelligence = Mock()
        intelligence.analyze_all_sites.return_value = WebsiteIntelligenceBatchResult(
            websites_analyzed=2, profiles_created=0, profiles_updated=2,
            profiles_unchanged=0, history_changes=2,
        )
        intelligence.analyze_site.side_effect = lambda website: (
            WebsiteIntelligenceResult(
                website=website, profile_action="unchanged",
                statistics_action="unchanged", history_action="unchanged",
                health_score=50,
            )
        )
        plausible = Mock()
        plausible.import_active_websites.return_value = {
            "websites_evaluated": 2,
            "websites_attempted": 2, "websites_updated": 2,
            "websites_processed": 2, "websites_skipped": 0,
            "datapoints_saved": 60, "rows_created": 60,
            "rows_updated": 0, "errors": [], "websites_failed": 0,
            "overall_status": "completed",
        }
        service = DataRefreshService(
            database, registry=registry,
            partner_refresh=Mock(return_value={
                "fetched": 4, "new": 1, "duplicates": 3,
                "telegram_sent": 1, "completed_at": "2026-01-01T10:00:00+01:00",
            }),
            search_console=search, seo_history=seo,
            intelligence=intelligence,
            plausible_import=plausible,
            health_check=Mock(return_value={}),
        )
        service._test_parts = (registry, search, seo, intelligence, plausible)
        return service

    def test_refresh_all_runs_in_required_order(self) -> None:
        events = []
        service = self._service()
        result = service.refresh_all(
            lambda step, status, _result: events.append((step, status)),
            force_derived_refresh=True,
        )
        completed = [
            step for step, status in events if status == "success"
        ]
        self.assertEqual(
            [
                step for step in DataRefreshService.STEPS
                if step != "SEO-eksperimentovervågning"
            ],
            completed,
        )
        self.assertEqual(
            len(DataRefreshService.STEPS) - 1, result["completed_steps"]
        )
        self.assertEqual(1, result["skipped_steps"])
        self.assertEqual(0, result["failed_steps"])
        service.database.replace_priority_task_scores.assert_not_called()
        search = service._test_parts[1]
        search.sync_all_properties.assert_called_once_with(
            days=35, website_ids=None, force_full_refresh=False
        )
        search.sync_dimensions.assert_called_once_with(
            website_ids=None,
            new_daily_website_ids=set(),
            force_dimensions_refresh=False,
        )
        plausible = service._test_parts[4]
        plausible.import_active_websites.assert_called_once_with(
            website_ids=None, force_full_refresh=False
        )

    def test_manual_website_scope_reaches_incremental_daily_import(
        self,
    ) -> None:
        service = self._service()
        service.refresh_all(website_ids=["alpha.dk"])
        search = service._test_parts[1]
        search.sync_all_properties.assert_called_once_with(
            days=35,
            website_ids=["alpha.dk"],
            force_full_refresh=False,
        )
        search.sync_dimensions.assert_called_once_with(
            website_ids=["alpha.dk"],
            new_daily_website_ids=set(),
            force_dimensions_refresh=False,
        )
        plausible = service._test_parts[4]
        plausible.import_active_websites.assert_called_once_with(
            website_ids=["alpha.dk"], force_full_refresh=False
        )

    def test_new_daily_rows_and_force_are_forwarded_to_dimensions(self) -> None:
        service = self._service()
        search = service._test_parts[1]
        search.sync_all_properties.return_value = SearchConsoleDataSyncResult(
            properties_processed=2, properties_failed=0,
            rows_created=1, rows_updated=4, start_date="2026-01-01",
            end_date="2026-02-01", earliest_fetched_date="2026-01-01",
            latest_fetched_date="2026-02-01", import_mode="incremental",
            errors=[],
            property_results=[
                {"website_id": "alpha.dk", "rows_created": 1},
                {"website_id": "beta.dk", "rows_created": 0},
            ],
        )
        service.refresh_all(force_dimensions_refresh=True)
        search.sync_dimensions.assert_called_once_with(
            website_ids=None,
            new_daily_website_ids={"alpha.dk"},
            force_dimensions_refresh=True,
        )

    def test_independent_steps_continue_and_seo_is_skipped_after_search_error(
        self,
    ) -> None:
        service = self._service(search_failure=True)
        _registry, search, seo, intelligence, plausible = service._test_parts
        result = service.refresh_all()
        statuses = {item["step"]: item["status"] for item in result["steps"]}
        self.assertEqual("error", statuses["Search Console-properties"])
        self.assertEqual("skipped", statuses["Search Console-dagstal"])
        self.assertEqual("skipped", statuses["SEO History"])
        search.sync_all_properties.assert_not_called()
        seo.analyze_all_sites.assert_not_called()
        self.assertEqual(2, intelligence.analyze_site.call_count)
        plausible.import_active_websites.assert_called_once_with(
            website_ids=None, force_full_refresh=False
        )


class BriefingReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def test_missing_website_is_not_ready(self) -> None:
        result = get_website_briefing_readiness(
            self.database, "missing.example"
        )
        self.assertEqual("Ikke klar", result["status"])
        self.assertIn("Website Registry", result["missing_required"])

    def test_basic_data_is_partially_ready_and_can_generate(self) -> None:
        database = Mock()
        database.get_website.return_value = {"website": "example.dk"}
        database.get_website_profile_detail.return_value = {"profile": {}}
        database.get_search_console_daily_metrics.return_value = [{}] * 14
        database.get_dashboard_system_health.return_value = {
            "openai": {"is_ok": True}
        }
        database.get_website_intelligence_source.return_value = {
            "seo_health": None, "partner_ads": {"sales": []},
            "active_projects": [], "active_tasks": [],
        }
        database.get_website_discovery_profile.return_value = None
        database.get_latest_analysis.return_value = None
        result = get_website_briefing_readiness(database, "example.dk")
        self.assertEqual("Delvist klar", result["status"])
        self.assertFalse(result["missing_required"])


if __name__ == "__main__":
    unittest.main()
