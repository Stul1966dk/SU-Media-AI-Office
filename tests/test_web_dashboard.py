"""Tests for the read-only Streamlit dashboard."""

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from core.agent_orchestrator import Event
from core.database import Database
from core.task_engine import TaskEngine
from dashboard.components.data import load_dashboard_data


class WebDashboardDataTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "office.sqlite3"
        )
        self.database = Database(self.database_path)
        self.database.initialize()
        self.reference_time = datetime(2026, 7, 17, 12, 0)
        self._add_website("active.dk", "active", True)
        self._add_website("old.dk", "phasing_out", False)

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def _add_website(
        self,
        website: str,
        status: str,
        monetized: bool,
    ) -> None:
        self.database.upsert_website(
            {
                "website": website,
                "display_name": website,
                "active": status == "active",
                "monetized": monetized,
                "priority": "high",
                "primary_income_source": "affiliate",
                "niche": "test",
                "domain_age": "1",
                "notes": "",
                "status": status,
            }
        )

    def test_cards_and_tables_use_real_database_results(self) -> None:
        task_engine = TaskEngine(self.database)
        project_id = task_engine.create_project(
            website_id="active.dk",
            title="SEO Recovery – active.dk",
            description="Recovery",
            status="ready",
            priority="high",
            expected_effect="Bedre SEO",
        )
        subproject_id = task_engine.create_subproject(
            project_id,
            "Analyse",
            "Analyse",
            sequence=1,
            status="ready",
        )
        task_engine.create_task(
            subproject_id=subproject_id,
            website_id="active.dk",
            title="Analysér fald",
            description="Analyse",
            reason="Dokumenteret fald",
            assigned_agent="SEO Manager",
            estimated_minutes=60,
            expected_effect="Forklaring",
            priority_score=90,
        )
        self.database.upsert_seo_health(
            website_id="active.dk",
            analysis_date="2026-07-17",
            period="28d",
            score=20,
            trend="critical",
            click_change=-30,
            impression_change=-10,
            ctr_change=-2,
            position_change=3,
        )
        self.database.save_sale(
            {
                "kombiid": "sale-1",
                "programid": "1",
                "program": "Test",
                "dato": "17-7-2026",
                "tidspunkt": "10:00",
                "ordrenr": "order-1",
                "omsaetning": "100",
                "provision": "25",
                "url": "https://active.dk/produkt",
                "valuta": "DKK",
            },
            created_at="2026-07-17T10:00:00+02:00",
        )
        self.database.create_event_record(
            {
                **Event(
                    event_type="seo_recovery_project_created",
                    source="SEO Manager",
                    website="active.dk",
                    title="Recovery",
                    description="Dokumenteret fald",
                    priority=80,
                ).__dict__,
                "data_json": "{}",
                "status": "pending",
            }
        )
        self.database.set_system_status("partner_ads", True)
        self.database.set_system_status("search_console", True)
        self.database.set_system_status("agent_orchestrator", True)
        self.database.set_system_status("knowledge_engine", True)

        data = load_dashboard_data(
            self.database,
            now=self.reference_time,
        )
        self.assertTrue(all(data.system_status.values()))
        self.assertEqual(
            data.overview,
            {
                "websites": 2,
                "active_websites": 1,
                "monetized": 1,
                "phasing_out": 1,
                "active_projects": 1,
                "open_tasks": 1,
            },
        )
        self.assertEqual(data.economy["today_commission"], 25)
        self.assertEqual(data.economy["month_commission"], 25)
        self.assertEqual(data.economy["today_sales"], 1)
        self.assertEqual(data.economy["month_sales"], 1)
        self.assertEqual(data.seo_counts["critical"], 1)
        self.assertEqual(len(data.priority_tasks), 1)
        self.assertEqual(len(data.recovery_projects), 1)
        self.assertEqual(len(data.recent_sales), 1)
        self.assertEqual(data.recent_sales[0]["website"], "active.dk")
        self.assertEqual(len(data.recent_events), 1)
        self.assertEqual(data.displayed_database_results, 5)

    def test_seo_filter_and_empty_sections(self) -> None:
        data = load_dashboard_data(
            self.database,
            seo_trend="growing",
            now=self.reference_time,
        )
        self.assertEqual(data.seo_sites, [])
        self.assertEqual(data.priority_tasks, [])
        self.assertEqual(data.recovery_projects, [])
        self.assertEqual(data.recent_sales, [])
        self.assertEqual(data.recent_events, [])

    def test_one_missing_section_does_not_break_other_sections(self) -> None:
        database = Mock(spec=Database)
        database.get_dashboard_system_status.return_value = {}
        database.get_dashboard_overview.side_effect = RuntimeError("missing")
        database.get_dashboard_economy.return_value = {}
        database.get_seo_health_summary.return_value = {}
        database.get_latest_seo_health_sites.return_value = []
        database.get_priority_tasks.return_value = [{"task": "Virker"}]
        database.get_active_seo_recovery_projects.return_value = []
        database.get_recent_sales.return_value = []
        database.get_recent_events.return_value = []
        data = load_dashboard_data(database)
        self.assertEqual(data.overview["websites"], 0)
        self.assertEqual(data.priority_tasks, [{"task": "Virker"}])

    def test_ui_contains_no_sql_or_external_service_calls(self) -> None:
        dashboard_root = Path(__file__).resolve().parents[1] / "dashboard"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in dashboard_root.rglob("*.py")
        ).lower()
        for forbidden in (
            "select ",
            "insert ",
            "update ",
            "delete ",
            "telegram",
            "searchconsoleconnector",
            "partneradsservice",
            "requests.",
        ):
            self.assertNotIn(forbidden, source)


class StreamlitStartupTestCase(unittest.TestCase):
    def test_dashboard_starts_without_exception(self) -> None:
        try:
            from streamlit.testing.v1 import AppTest
        except ModuleNotFoundError:
            self.skipTest("Streamlit installeres fra requirements.txt.")
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "dashboard.sqlite3"
            previous = os.environ.get("SU_MEDIA_DATABASE_PATH")
            os.environ["SU_MEDIA_DATABASE_PATH"] = str(path)
            try:
                app = AppTest.from_file(
                    str(
                        Path(__file__).resolve().parents[1]
                        / "dashboard"
                        / "app.py"
                    )
                )
                app.run(timeout=15)
            finally:
                if previous is None:
                    os.environ.pop("SU_MEDIA_DATABASE_PATH", None)
                else:
                    os.environ["SU_MEDIA_DATABASE_PATH"] = previous
            self.assertEqual(app.exception, [])


if __name__ == "__main__":
    unittest.main()
