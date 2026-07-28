"""Sprint 41.3 tests for reversible website activation."""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from agents.ai_analyst import AIAnalyst
from core.database import Database
from core.search_console_service import SearchConsoleService
from core.website_registry import WebsiteRegistry
from core.work_queue_service import WorkQueueService


class WebsiteActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "office.db"
        self.database = Database(self.path)
        self.database.initialize()
        for website in ("active.dk", "toggle.dk"):
            self.database.upsert_website({
                "website": website,
                "display_name": website,
                "active": True,
                "monetized": True,
                "priority": "medium",
                "primary_income_source": "affiliate",
                "niche": "test",
                "domain_age": "1",
                "notes": "",
                "status": "active",
            })

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def test_toggle_preserves_identity_and_seo_history(self) -> None:
        self.database.upsert_seo_health(
            website_id="toggle.dk",
            analysis_date="2026-07-24",
            period="28d",
            score=70,
            trend="growing",
            click_change=10,
            impression_change=20,
            ctr_change=1,
            position_change=-1,
        )
        before = self.database.get_website("toggle.dk")
        history_before = self.database.get_seo_health_history("toggle.dk")

        self.assertTrue(self.database.set_website_active("toggle.dk", False))
        inactive = self.database.get_website("toggle.dk")

        self.assertEqual(before["website"], inactive["website"])
        self.assertFalse(inactive["active"])
        self.assertEqual("inactive", inactive["status"])
        self.assertNotIn("toggle.dk", self.database.get_active_website_ids())
        self.assertEqual([], self.database.get_latest_seo_health_sites())
        self.assertEqual(
            history_before,
            self.database.get_seo_health_history("toggle.dk"),
        )

        self.assertTrue(self.database.set_website_active("toggle.dk", True))
        reactivated = self.database.get_website("toggle.dk")
        self.assertEqual(before["website"], reactivated["website"])
        self.assertTrue(reactivated["active"])
        self.assertEqual("active", reactivated["status"])
        self.assertEqual(
            history_before,
            self.database.get_seo_health_history("toggle.dk"),
        )
        self.assertEqual(
            ["toggle.dk"],
            [
                row["website"]
                for row in self.database.get_latest_seo_health_sites()
            ],
        )

    def test_search_console_import_skips_inactive_then_includes_reactivated(
        self,
    ) -> None:
        for website in ("active.dk", "toggle.dk"):
            self.database.upsert_search_console_property(
                site_url=f"sc-domain:{website}",
                permission_level="siteFullUser",
                website_id=website,
                active=True,
            )
        connector = Mock()
        connector.get_search_analytics.return_value = []
        service = SearchConsoleService(
            connector, self.database, WebsiteRegistry(self.database)
        )

        self.database.set_website_active("toggle.dk", False)
        first = service.sync_all_properties(days=1)
        self.assertEqual(1, first.properties_processed)
        self.assertEqual(
            ["sc-domain:active.dk"],
            [call.args[0] for call in connector.get_search_analytics.call_args_list],
        )

        connector.get_search_analytics.reset_mock()
        self.database.set_website_active("toggle.dk", True)
        second = service.sync_all_properties(days=1)
        self.assertEqual(2, second.properties_processed)
        self.assertEqual(
            {"sc-domain:active.dk", "sc-domain:toggle.dk"},
            {call.args[0] for call in connector.get_search_analytics.call_args_list},
        )

    def test_registry_sync_does_not_reactivate_manual_deactivation(self) -> None:
        registry_file = self.path.parent / "websites.csv"
        registry_file.write_text(
            "website;display_name;active;monetized;priority;"
            "primary_income_source;niche;domain_age;notes\n"
            "toggle.dk;Toggle;yes;yes;medium;affiliate;test;1;\n",
            encoding="utf-8",
        )
        self.database.set_website_active("toggle.dk", False)

        WebsiteRegistry(self.database).sync()

        website = self.database.get_website("toggle.dk")
        self.assertFalse(website["active"])
        self.assertEqual("inactive", website["status"])

    def test_inactive_website_cannot_create_new_experiment(self) -> None:
        database = Mock()
        database.get_work_queue_item.return_value = {
            "id": 7,
            "website_id": "toggle.dk",
            "status": "queued",
            "candidate": {},
        }
        database.get_website.return_value = {
            "website": "toggle.dk", "active": False, "status": "inactive",
        }
        service = WorkQueueService(
            database,
            Mock(),
            decision_engine=Mock(),
            experiment_engine=Mock(),
        )

        with self.assertRaisesRegex(ValueError, "inaktivt website"):
            service.approve(7)

    def test_inactive_website_cannot_start_new_ai_analysis(self) -> None:
        database = Mock()
        database.get_website.return_value = {
            "website": "toggle.dk", "active": False, "status": "inactive",
        }
        analyst = AIAnalyst(
            ai_service=Mock(),
            database=database,
            knowledge_engine=Mock(),
            website_intelligence=Mock(),
            seo_history=Mock(),
            project_manager=Mock(),
            task_engine=Mock(),
        )

        with self.assertRaisesRegex(ValueError, "ikke aktivt"):
            analyst.analyze_site("toggle.dk")

    def test_websites_page_has_checkbox_activation_editor(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "dashboard" / "pages" / "11_Websites.py"
        ).read_text(encoding="utf-8")
        self.assertIn("st.data_editor(", source)
        self.assertIn("st.column_config.CheckboxColumn(", source)
        self.assertIn('"Gem aktive websites"', source)


if __name__ == "__main__":
    unittest.main()
