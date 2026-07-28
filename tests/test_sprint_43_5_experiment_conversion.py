"""Sprint 43.5 tests for approval-gated recommendation experiments."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from core.database import Database
from core.traffic_recommendation_workflow import (
    TrafficRecommendationWorkflow,
)
from dashboard.components.data import _filter_decided_recommendations


RECOMMENDATION = {
    "task_key": "combined|site.dk|guide",
    "website": "site.dk",
    "task_type": "combined_traffic_decline",
    "target_url": "https://site.dk/guide/",
    "target_query": "bedste guide",
    "measured_cause": "Placeringsfald",
    "description": "Styrk siden til søgeordet “bedste guide”.",
    "recommended_action": "Opdater det vigtigste indholdsafsnit.",
    "explanation": "Search Console og Plausible viser samme fald.",
    "measurement_method": "Sammenlign organiske klik efter 28 dage.",
    "completion_criterion": "Det valgte afsnit er opdateret.",
    "priority": "Kritisk",
    "click_change": -30,
    "plausible_change": -25,
    "confidence": "høj",
    "total_score": 82,
}


class RecommendationExperimentConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "office.db")
        self.database.initialize()
        self.database.upsert_website({
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
        self.workflow = TrafficRecommendationWorkflow(self.database)

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _draft(self) -> dict:
        return self.workflow.create_draft(
            RECOMMENDATION,
            title="Opdater guideafsnittet",
            description="Opdater kun afsnittet om valg af guide.",
        )

    def _baseline(self) -> None:
        self.database.upsert_search_console_dimension(
            dimension_type="page_query",
            website_id="site.dk",
            site_url="https://site.dk/",
            page_url=RECOMMENDATION["target_url"],
            query=RECOMMENDATION["target_query"],
            period_start="2026-06-21",
            period_end="2026-07-18",
            clicks=30,
            impressions=700,
            ctr=30 / 700,
            average_position=8.2,
        )

    def test_draft_must_be_explicitly_approved(self) -> None:
        self._draft()
        approved = self.workflow.approve_draft(
            RECOMMENDATION["task_key"]
        )
        second = self.workflow.approve_draft(RECOMMENDATION["task_key"])
        self.assertEqual("approved", approved["status"])
        self.assertIsNotNone(approved["evidence"]["approved_at"])
        self.assertEqual(approved["id"], second["id"])
        self.assertEqual([], self.database.get_seo_experiments())

    def test_approved_implemented_change_starts_one_28_day_experiment(self):
        self._baseline()
        self._draft()
        self.workflow.approve_draft(RECOMMENDATION["task_key"])
        experiment = self.workflow.mark_implemented(
            RECOMMENDATION["task_key"],
            change_description=(
                "Omskrev afsnittet om valg og tilføjede konkrete kriterier."
            ),
            experiment_type="content_update",
        )
        repeated = self.workflow.mark_implemented(
            RECOMMENDATION["task_key"],
            change_description="Denne tekst må ikke skabe et nyt forsøg.",
            experiment_type="content_update",
        )
        decision = self.database.get_traffic_recommendation_decision(
            RECOMMENDATION["task_key"]
        )
        self.assertEqual(experiment["id"], repeated["id"])
        self.assertEqual("waiting_for_data", experiment["status"])
        self.assertEqual(28, experiment["waiting_period_days"])
        self.assertEqual(
            28,
            (
                date.fromisoformat(experiment["planned_evaluation_date"])
                - date.fromisoformat(experiment["started_at"][:10])
            ).days,
        )
        self.assertEqual("experiment_running", decision["status"])
        self.assertEqual(
            experiment["id"], decision["evidence"]["experiment_id"]
        )
        self.assertEqual(1, len(self.database.get_seo_experiments()))

    def test_missing_baseline_creates_no_experiment(self) -> None:
        self._draft()
        self.workflow.approve_draft(RECOMMENDATION["task_key"])
        with self.assertRaisesRegex(ValueError, "stabil baseline"):
            self.workflow.mark_implemented(
                RECOMMENDATION["task_key"],
                change_description="Opdaterede ét afsnit.",
                experiment_type="content_update",
            )
        self.assertEqual([], self.database.get_seo_experiments())
        decision = self.database.get_traffic_recommendation_decision(
            RECOMMENDATION["task_key"]
        )
        self.assertEqual("approved", decision["status"])

    def test_unapproved_or_empty_change_cannot_start_measurement(self) -> None:
        self._baseline()
        self._draft()
        with self.assertRaisesRegex(ValueError, "godkendes"):
            self.workflow.mark_implemented(
                RECOMMENDATION["task_key"],
                change_description="Opdaterede ét afsnit.",
                experiment_type="content_update",
            )
        self.workflow.approve_draft(RECOMMENDATION["task_key"])
        with self.assertRaisesRegex(ValueError, "Beskriv præcist"):
            self.workflow.mark_implemented(
                RECOMMENDATION["task_key"],
                change_description=" ",
                experiment_type="content_update",
            )

    def test_approved_and_running_recommendations_leave_action_list(self):
        items = [{"task_key": RECOMMENDATION["task_key"]}]
        for status in ("approved", "experiment_running"):
            with self.subTest(status=status):
                self.assertEqual([], _filter_decided_recommendations(
                    items,
                    [{
                        "recommendation_key": RECOMMENDATION["task_key"],
                        "status": status,
                    }],
                ))


if __name__ == "__main__":
    unittest.main()
