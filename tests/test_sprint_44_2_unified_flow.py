"""Sprint 44.2 checks for the unified daily recommendation workflow."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.database import Database
from core.traffic_work_overview import build_traffic_work_overview


ROOT = Path(__file__).resolve().parents[1]


class UnifiedDailyFlowTests(unittest.TestCase):
    def test_direct_approval_persists_hidden_draft_and_approval(self):
        page_path = (
            ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
        )
        spec = importlib.util.spec_from_file_location(
            "daily_work_44_2", page_path
        )
        page = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(page)
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "office.db")
            database.initialize()
            database.upsert_website({
                "website": "site.dk",
                "display_name": "Site",
                "active": True,
                "monetized": True,
                "priority": "high",
                "primary_income_source": "affiliate",
                "niche": "test",
                "domain_age": "1",
                "notes": "",
                "status": "active",
            })
            recommendation = {
                "task_key": "combined|site.dk|page",
                "website": "site.dk",
                "task_type": "combined_traffic_decline",
                "target_url": "https://site.dk/side/",
                "measured_cause": "CTR-fald",
                "description": "Styrk siden",
                "priority": "Kritisk",
            }

            with patch.object(page, "_finish_daily_action") as finish:
                page._create_and_approve(
                    database,
                    recommendation,
                    "Styrk siden",
                    "Opdatér indholdet.",
                )

            decision = database.get_traffic_recommendation_decision(
                recommendation["task_key"]
            )
            self.assertEqual("approved", decision["status"])
            finish.assert_called_once()
            database.close()

    def test_decision_statuses_point_back_to_today(self):
        decisions = [
            {
                "recommendation_key": "draft",
                "website_id": "site.dk",
                "status": "draft",
                "title": "Opgave",
                "description": "Beskrivelse",
                "target_url": "https://site.dk/side/",
                "evidence": {},
            },
            {
                "recommendation_key": "approved",
                "website_id": "site.dk",
                "status": "approved",
                "title": "Godkendt opgave",
                "description": "Beskrivelse",
                "target_url": "https://site.dk/side-2/",
                "evidence": {},
            },
        ]

        items = build_traffic_work_overview(decisions, [])

        self.assertEqual(
            ["Klar til implementering", "Klar til godkendelse"],
            [item["status_label"] for item in items],
        )
        self.assertEqual({"app.py"}, {item["target"] for item in items})
        self.assertTrue(all(item["recommendation_key"] for item in items))

    def test_today_contains_all_user_decisions_and_implementation(self):
        source = (
            ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
        ).read_text(encoding="utf-8")

        for text in (
            "Godkend opgave",
            "Redigér før godkendelse",
            "Udsæt 14 dage",
            "Afvis",
            "Åbn siden, der skal ændres",
            "Registrér ændring og start 28-dages måling",
        ):
            self.assertIn(text, source)
        self.assertIn("get_decisions(", source)
        self.assertIn("mark_implemented(", source)

    def test_partner_ads_is_contextual_to_integrations(self):
        navigation = (
            ROOT / "dashboard" / "components" / "ui.py"
        ).read_text(encoding="utf-8")
        integrations = (
            ROOT / "dashboard" / "pages" / "18_Integrationer.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            '("pages/10_Partner_Ads.py", "Partner Ads"', navigation
        )
        self.assertIn("Se salg og importdetaljer", integrations)
        self.assertIn("pages/10_Partner_Ads.py", integrations)


if __name__ == "__main__":
    unittest.main()
