"""Sprint 7 tests for change-driven derived calculations."""

import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

from agents.website_intelligence import WebsiteIntelligenceResult
from core.data_refresh_service import DataRefreshService
from core.search_console_service import (
    SearchConsoleDataSyncResult,
    SearchConsoleDimensionSyncResult,
    SearchConsoleSyncResult,
)
from core.seo_history import SEOHealth
from core.website_registry import ImportResult


class _FakeContentConnector:
    """Stand-in for WordPressConnector that never touches the network."""

    def __init__(self, *, website_id, database) -> None:
        self.website_id = website_id

    def connect(self) -> bool:
        return True

    def import_content(self, *, modified_after=None) -> dict:
        return {"total": 0, "changed": 0}

    def disconnect(self) -> None:
        pass


class _FakeScanner:
    """Stand-in for WebsiteScanner that never touches the network."""

    def scan(self, domain: str) -> dict:
        return {"cms": "wordpress", "scan_status": "completed"}


class _FakeEvaluator:
    """Stand-in for ExperimentEvaluationService (no AI, nothing due)."""

    def evaluate_due_experiments(self, reference_date=None) -> list:
        return []


class Sprint7DerivedRefreshTests(unittest.TestCase):
    def service(
        self, *, daily: dict[str, int] | None = None,
        plausible: dict[str, int] | None = None,
        partner_new: int = 0,
        registry_updated: int = 0,
        seo_action: str = "unchanged",
        intelligence_action: str = "unchanged",
        experiments: list[dict] | None = None,
    ) -> DataRefreshService:
        database = Mock()
        database.get_active_website_ids.return_value = ["a.dk", "b.dk"]
        database.get_integration_state.return_value = None
        database.get_website_discovery_profiles.return_value = []
        database.get_seo_experiments.return_value = experiments or []
        database.get_priority_task_scores.return_value = []
        database.get_dashboard_action_context.return_value = {}
        database.get_dashboard_system_health.return_value = {}
        database.get_priority_tasks.return_value = []

        registry = Mock()
        registry.sync.return_value = ImportResult(
            total=2, created=0, updated=registry_updated, phased_out=0
        )
        search = Mock()
        search.synchronize.return_value = SearchConsoleSyncResult(
            connection_ok=True, total=2, matched=2, unmatched=0,
            properties=[],
        )
        daily_results = [
            {
                "website_id": website,
                "site_url": f"https://{website}/",
                "rows_created": values.get("created", 0),
                "rows_updated": values.get("updated", 0),
                "rows_changed": values.get("changed", 0),
            }
            for website, values in (daily or {}).items()
        ]
        search.sync_all_properties.return_value = SearchConsoleDataSyncResult(
            properties_processed=2, properties_failed=0,
            rows_created=sum(x["rows_created"] for x in daily_results),
            rows_updated=sum(x["rows_updated"] for x in daily_results),
            start_date="2026-07-01", end_date="2026-07-25",
            earliest_fetched_date="2026-07-01",
            latest_fetched_date="2026-07-25",
            import_mode="incremental", errors=[],
            property_results=daily_results,
        )
        search.sync_dimensions.return_value = SearchConsoleDimensionSyncResult(
            properties_processed=0, properties_failed=0,
            page_rows=0, query_rows=0, page_query_rows=0,
            rows_created=0, rows_updated=0, errors=[],
            properties_evaluated=2, properties_skipped=2,
            api_calls_executed=0, api_calls_avoided=12,
            property_results=[
                {
                    "website_id": website, "status": "skipped",
                    "rows_created": 0, "rows_updated": 0, "rows_changed": 0,
                }
                for website in ("a.dk", "b.dk")
            ],
            overall_status="skipped",
        )
        seo = Mock()
        seo.analyze_site.side_effect = lambda website: [
            SEOHealth(
                website=website, period="28d", click_change_pct=0,
                impression_change_pct=0, ctr_change=0, position_change=0,
                trend="stable", score=50, action=seo_action,
            )
        ]
        intelligence = Mock()
        intelligence.analyze_site.side_effect = lambda website: (
            WebsiteIntelligenceResult(
                website=website, profile_action=intelligence_action,
                statistics_action="unchanged", history_action="unchanged",
                health_score=50,
            )
        )
        plausible_rows = [
            {
                "website_id": website,
                "rows_created": values.get("created", 0),
                "rows_updated": values.get("updated", 0),
                "rows_changed": values.get("changed", 0),
                "status": "completed",
            }
            for website, values in (plausible or {}).items()
        ]
        plausible_import = Mock()
        plausible_import.import_active_websites.return_value = {
            "website_results": plausible_rows,
            "rows_created": sum(x["rows_created"] for x in plausible_rows),
            "rows_updated": sum(x["rows_updated"] for x in plausible_rows),
            "rows_changed": sum(x["rows_changed"] for x in plausible_rows),
            "overall_status": "completed",
        }
        service = DataRefreshService(
            database, registry=registry,
            partner_refresh=Mock(return_value={
                "new": partner_new, "updated": 0,
                "overall_status": "completed",
            }),
            search_console=search, seo_history=seo,
            intelligence=intelligence,
            plausible_import=plausible_import,
            health_check=Mock(return_value={}),
            content_connector=_FakeContentConnector,
            discovery_scanner=_FakeScanner(),
            experiment_evaluator=_FakeEvaluator(),
        )
        service._test_seo = seo
        service._test_intelligence = intelligence
        service.refresh_priority_scores = Mock(return_value={
            "data_changed": False, "records_updated": 0,
            "processed_websites": [],
        })
        return service

    @staticmethod
    def steps(result: dict) -> dict[str, dict]:
        return {item["step"]: item for item in result["steps"]}

    @patch("core.data_refresh_service.ExperimentMonitoringService")
    def test_no_changes_skip_all_four_derived_steps(
        self, monitoring_class: Mock
    ) -> None:
        result = self.service().refresh_all()
        steps = self.steps(result)
        for name in (
            "SEO History", "Website Intelligence",
            "SEO-eksperimentovervågning", "Prioriteringsscore",
        ):
            self.assertEqual("skipped", steps[name]["status"])
            self.assertFalse(steps[name]["data_changed"])
        monitoring_class.assert_not_called()
        self.assertEqual(5, result["skipped_steps"])

    @patch("core.data_refresh_service.ExperimentMonitoringService")
    def test_search_change_is_scoped_and_identical_seo_is_unchanged(
        self, _monitoring: Mock
    ) -> None:
        service = self.service(
            daily={"a.dk": {"created": 1, "changed": 1}}
        )
        result = service.refresh_all()
        service._test_seo.analyze_site.assert_called_once_with("a.dk")
        service._test_intelligence.analyze_site.assert_called_once_with("a.dk")
        seo = self.steps(result)["SEO History"]
        self.assertFalse(seo["data_changed"])
        self.assertIn("search_console_daily", seo["trigger_sources"])

    @patch("core.data_refresh_service.ExperimentMonitoringService")
    def test_plausible_change_runs_seo_only_for_changed_website(
        self, _monitoring: Mock
    ) -> None:
        service = self.service(
            plausible={"b.dk": {"updated": 1, "changed": 1}}
        )
        result = service.refresh_all()
        service._test_seo.analyze_site.assert_called_once_with("b.dk")
        service._test_intelligence.analyze_site.assert_not_called()
        self.assertEqual(
            "skipped", self.steps(result)["Website Intelligence"]["status"]
        )

    @patch("core.data_refresh_service.ExperimentMonitoringService")
    def test_partner_ads_only_runs_intelligence_not_seo_or_priority(
        self, _monitoring: Mock
    ) -> None:
        service = self.service(partner_new=1)
        result = service.refresh_all()
        steps = self.steps(result)
        self.assertEqual("skipped", steps["SEO History"]["status"])
        self.assertEqual("success", steps["Website Intelligence"]["status"])
        self.assertEqual("skipped", steps["Prioriteringsscore"]["status"])
        self.assertEqual(2, service._test_intelligence.analyze_site.call_count)

    @patch("core.data_refresh_service.ExperimentMonitoringService")
    def test_experiment_waits_without_data_but_runs_when_due(
        self, monitoring_class: Mock
    ) -> None:
        future = (date.today() + timedelta(days=5)).isoformat()
        service = self.service(experiments=[{
            "id": 1, "website_id": "a.dk", "status": "waiting_for_data",
            "planned_evaluation_date": future,
        }])
        first = service.refresh_all()
        self.assertEqual(
            "skipped",
            self.steps(first)["SEO-eksperimentovervågning"]["status"],
        )
        past = (date.today() - timedelta(days=1)).isoformat()
        service.database.get_seo_experiments.return_value = [{
            "id": 1, "website_id": "a.dk", "status": "waiting_for_data",
            "planned_evaluation_date": past,
        }]
        monitoring_class.return_value.update_active_experiments.return_value = [
            {"data_changed": True}
        ]
        second = service.refresh_all()
        step = self.steps(second)["SEO-eksperimentovervågning"]
        self.assertEqual("success", step["status"])
        self.assertTrue(step["data_changed"])

    @patch("core.data_refresh_service.ExperimentMonitoringService")
    def test_new_search_data_runs_experiment_and_priority(
        self, monitoring_class: Mock
    ) -> None:
        service = self.service(
            daily={"a.dk": {"created": 1, "changed": 1}},
            experiments=[{
                "id": 1, "website_id": "a.dk", "status": "waiting_for_data",
                "planned_evaluation_date": (
                    date.today() + timedelta(days=5)
                ).isoformat(),
            }],
        )
        monitoring_class.return_value.update_active_experiments.return_value = [
            {"data_changed": False}
        ]
        result = service.refresh_all()
        steps = self.steps(result)
        self.assertEqual(
            "success", steps["SEO-eksperimentovervågning"]["status"]
        )
        self.assertEqual("success", steps["Prioriteringsscore"]["status"])

    @patch("core.data_refresh_service.ExperimentMonitoringService")
    def test_error_is_unknown_not_no_change(self, _monitoring: Mock) -> None:
        service = self.service()
        service.search_console.sync_all_properties.side_effect = RuntimeError(
            "Search failed"
        )
        result = service.refresh_all()
        seo = self.steps(result)["SEO History"]
        self.assertTrue(seo["unknown_due_to_error"])
        self.assertIn("Kunne ikke afgøre", seo["reason"])

    @patch("core.data_refresh_service.ExperimentMonitoringService")
    def test_force_runs_website_steps_with_filter(
        self, monitoring_class: Mock
    ) -> None:
        service = self.service(experiments=[{
            "id": 1, "website_id": "a.dk", "status": "waiting_for_data",
            "planned_evaluation_date": (
                date.today() + timedelta(days=5)
            ).isoformat(),
        }])
        monitoring_class.return_value.update_active_experiments.return_value = []
        result = service.refresh_all(
            website_ids=["a.dk"], force_derived_refresh=True
        )
        service._test_seo.analyze_site.assert_called_once_with("a.dk")
        service._test_intelligence.analyze_site.assert_called_once_with("a.dk")
        self.assertEqual(
            "success",
            self.steps(result)["SEO-eksperimentovervågning"]["status"],
        )
        service.refresh_priority_scores.assert_called_once_with(["a.dk"])


if __name__ == "__main__":
    unittest.main()
