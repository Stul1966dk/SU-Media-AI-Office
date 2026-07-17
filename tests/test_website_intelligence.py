"""Tests for Website Intelligence profiles and dashboard page."""

import inspect
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from agents.website_intelligence import WebsiteIntelligenceAgent
from core.database import Database
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry


class WebsiteIntelligenceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "office.sqlite3"
        )
        self.database = Database(self.database_path)
        self.database.initialize()
        self.registry = WebsiteRegistry(self.database)
        self.agent = WebsiteIntelligenceAgent(self.database, self.registry)
        self.analysis_date = date(2026, 7, 17)
        self._add_website("example.dk")

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def _add_website(self, website: str) -> None:
        self.database.upsert_website(
            {
                "website": website,
                "display_name": "Example",
                "active": True,
                "monetized": True,
                "priority": "high",
                "primary_income_source": "affiliate",
                "niche": "fitness / training",
                "domain_age": "3",
                "notes": "CMS WordPress; theme: GeneratePress",
                "status": "active",
            }
        )

    def _add_connected_data(self) -> None:
        for offset in range(1, 29):
            self.database.upsert_search_console_daily_metric(
                website_id="example.dk",
                site_url="sc-domain:example.dk",
                metric_date=(
                    self.analysis_date - timedelta(days=offset)
                ).isoformat(),
                clicks=10,
                impressions=100,
                ctr=0.1,
                average_position=4.0,
            )
        self.database.upsert_seo_health(
            website_id="example.dk",
            analysis_date=self.analysis_date.isoformat(),
            period="28d",
            score=75,
            trend="growing",
            click_change=20,
            impression_change=10,
            ctr_change=1,
            position_change=-1,
        )
        self.database.save_sale(
            {
                "kombiid": "sale-1",
                "programid": "1",
                "program": "Test",
                "dato": "17-7-2026",
                "tidspunkt": "10:00",
                "ordrenr": "order-1",
                "omsaetning": "1000",
                "provision": "100",
                "url": "https://www.example.dk/produkt",
                "valuta": "DKK",
            },
            created_at="2026-07-17T10:00:00+02:00",
        )
        task_engine = TaskEngine(self.database)
        project_id = task_engine.create_project(
            website_id="example.dk",
            title="SEO Recovery – example.dk",
            description="Recovery",
            status="ready",
            priority="high",
            expected_effect="Bedre SEO",
        )
        subproject_id = task_engine.create_subproject(
            project_id,
            "Analyse",
            "Analyse",
            1,
            status="ready",
        )
        task_engine.create_task(
            subproject_id=subproject_id,
            website_id="example.dk",
            title="Analysér website",
            description="Analyse",
            reason="Dokumenteret behov",
            assigned_agent="SEO Manager",
            estimated_minutes=60,
            expected_effect="Bedre beslutning",
            priority_score=90,
        )

    def test_profile_links_all_database_sources(self) -> None:
        self._add_connected_data()
        result = self.agent.analyze_site(
            "example.dk",
            analysis_date=self.analysis_date,
        )
        detail = self.database.get_website_profile_detail("example.dk")
        self.assertEqual(result.profile_action, "created")
        self.assertTrue(0 <= result.health_score <= 100)
        self.assertEqual(detail["profile"]["cms"], "WordPress")
        self.assertEqual(detail["profile"]["theme"], "GeneratePress")
        self.assertEqual(detail["profile"]["monetization"], "affiliate")
        self.assertEqual(detail["profile"]["niche"], "fitness / training")
        self.assertIn(
            "Partner Ads har dokumenteret provision",
            detail["profile"]["strong_areas"],
        )
        self.assertEqual(detail["statistics"]["search_clicks"], 280)
        self.assertEqual(detail["statistics"]["search_impressions"], 2800)
        self.assertEqual(detail["statistics"]["sales_count"], 1)
        self.assertEqual(detail["statistics"]["commission"], 100)
        self.assertEqual(detail["statistics"]["seo_score"], 75)
        self.assertEqual(detail["statistics"]["active_projects"], 1)
        self.assertEqual(detail["statistics"]["active_tasks"], 1)
        self.assertEqual(len(detail["categories"]), 3)
        self.assertEqual(len(detail["active_projects"]), 1)
        self.assertEqual(len(detail["active_tasks"]), 1)

    def test_unknown_platform_is_recorded_without_guessing(self) -> None:
        self.database.upsert_website(
            {
                **self.database.get_website("example.dk"),
                "notes": "",
            }
        )
        self.agent.analyze_site(
            "example.dk",
            analysis_date=self.analysis_date,
        )
        profile = self.database.get_website_profile_detail(
            "example.dk"
        )["profile"]
        self.assertEqual(profile["cms"], "Ukendt")
        self.assertEqual(profile["theme"], "Ukendt")

    def test_history_has_no_duplicates_and_records_real_changes(self) -> None:
        first = self.agent.analyze_site(
            "example.dk",
            analysis_date=self.analysis_date,
        )
        second = self.agent.analyze_site(
            "example.dk",
            analysis_date=self.analysis_date,
        )
        self.assertEqual(first.history_action, "created")
        self.assertEqual(second.history_action, "unchanged")
        self.assertEqual(
            len(
                self.database.get_website_profile_detail(
                    "example.dk"
                )["history"]
            ),
            1,
        )
        self.database.upsert_website(
            {
                **self.database.get_website("example.dk"),
                "niche": "fitness",
            }
        )
        changed = self.agent.analyze_site(
            "example.dk",
            analysis_date=self.analysis_date + timedelta(days=1),
        )
        detail = self.database.get_website_profile_detail("example.dk")
        self.assertEqual(changed.profile_action, "updated")
        self.assertEqual(changed.history_action, "created")
        self.assertEqual(len(detail["history"]), 2)

    def test_analyze_all_sites_builds_one_profile_per_website(self) -> None:
        self._add_website("second.dk")
        result = self.agent.analyze_all_sites(self.analysis_date)
        self.assertEqual(result.websites_analyzed, 2)
        self.assertEqual(result.profiles_created, 2)
        self.assertEqual(len(self.database.get_website_profiles()), 2)

    def test_agent_and_dashboard_have_no_external_calls_or_ui_sql(self) -> None:
        agent_source = inspect.getsource(WebsiteIntelligenceAgent).lower()
        page_source = (
            Path(__file__).resolve().parents[1]
            / "dashboard"
            / "pages"
            / "1_Website_Profile.py"
        ).read_text(encoding="utf-8").lower()
        for forbidden in (
            "telegram",
            "searchconsoleconnector",
            "partneradsservice",
            "requests.",
        ):
            self.assertNotIn(forbidden, agent_source)
            self.assertNotIn(forbidden, page_source)
        for statement in ("select ", "insert ", "update ", "delete "):
            self.assertNotIn(statement, page_source)


class WebsiteProfilePageTestCase(unittest.TestCase):
    def test_page_starts_with_empty_database(self) -> None:
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as temporary_directory:
            previous = os.environ.get("SU_MEDIA_DATABASE_PATH")
            os.environ["SU_MEDIA_DATABASE_PATH"] = str(
                Path(temporary_directory) / "profile.sqlite3"
            )
            try:
                app = AppTest.from_file(
                    str(
                        Path(__file__).resolve().parents[1]
                        / "dashboard"
                        / "pages"
                        / "1_Website_Profile.py"
                    )
                )
                app.run(timeout=15)
            finally:
                if previous is None:
                    os.environ.pop("SU_MEDIA_DATABASE_PATH", None)
                else:
                    os.environ["SU_MEDIA_DATABASE_PATH"] = previous
            self.assertEqual(app.exception, [])
            self.assertEqual(len(app.caption), 1)
            self.assertEqual(app.caption[0].value, "Ingen data.")


if __name__ == "__main__":
    unittest.main()
