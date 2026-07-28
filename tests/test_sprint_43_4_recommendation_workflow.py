"""Sprint 43.4 tests for safe traffic recommendation decisions."""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

from core.database import Database
from core.traffic_recommendation_workflow import (
    TrafficRecommendationWorkflow,
)
from dashboard.components.data import _filter_decided_recommendations


RECOMMENDATION = {
    "task_key": "combined|site.dk|url",
    "website": "site.dk",
    "task_type": "combined_traffic_decline",
    "target_url": "https://site.dk/side/",
    "measured_cause": "CTR-fald",
    "description": "Gennemgå title og meta på siden.",
    "recommended_action": "Gennemgå title og meta på siden.",
    "explanation": "Begge datakilder viser fald.",
    "priority": "Kritisk",
    "click_change": -30,
    "plausible_change": -25,
    "confidence": "høj",
    "total_score": 82,
}


class RecommendationWorkflowTests(unittest.TestCase):
    def setUp(self):
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

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_draft_is_saved_outside_operational_task_queue(self):
        result = self.workflow.create_draft(
            RECOMMENDATION,
            title="Ret title",
            description="Kontrollér CTR-faldet før ændring.",
        )
        self.assertEqual("draft", result["status"])
        self.assertEqual("Ret title", result["title"])
        self.assertEqual([], self.database.get_task_records_for_project())

    def test_same_recommendation_updates_instead_of_duplicating(self):
        self.workflow.create_draft(
            RECOMMENDATION, title="Første", description="Beskrivelse"
        )
        self.workflow.create_draft(
            RECOMMENDATION, title="Anden", description="Ny beskrivelse"
        )
        result = self.database.get_traffic_recommendation_decision(
            RECOMMENDATION["task_key"]
        )
        count = self.database.connection.execute(
            "SELECT COUNT(*) FROM traffic_recommendation_decisions"
        ).fetchone()[0]
        self.assertEqual(1, count)
        self.assertEqual("Anden", result["title"])

    def test_snooze_and_reject_are_persisted(self):
        until = date.today() + timedelta(days=14)
        snoozed = self.workflow.snooze(RECOMMENDATION, until)
        self.assertEqual("snoozed", snoozed["status"])
        self.assertEqual(until.isoformat(), snoozed["snoozed_until"])
        rejected = self.workflow.reject(RECOMMENDATION)
        self.assertEqual("rejected", rejected["status"])
        self.assertIsNone(rejected["snoozed_until"])

    def test_past_snooze_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "fremtiden"):
            self.workflow.snooze(
                RECOMMENDATION, date.today() - timedelta(days=1)
            )

    def test_existing_open_task_blocks_duplicate_draft(self):
        database = Mock()
        database.find_open_task_by_title.return_value = {"id": 7}
        workflow = TrafficRecommendationWorkflow(database)
        with self.assertRaisesRegex(ValueError, "allerede en åben opgave"):
            workflow.create_draft(
                RECOMMENDATION,
                title="Ret title",
                description="Beskrivelse",
            )
        database.upsert_traffic_recommendation_decision.assert_not_called()

    def test_handled_recommendations_are_hidden_from_action_list(self):
        items = [{"task_key": RECOMMENDATION["task_key"]}]
        draft = [{
            "recommendation_key": RECOMMENDATION["task_key"],
            "status": "draft",
        }]
        self.assertEqual([], _filter_decided_recommendations(items, draft))
        snoozed = [{
            "recommendation_key": RECOMMENDATION["task_key"],
            "status": "snoozed",
            "snoozed_until": (date.today() + timedelta(days=1)).isoformat(),
        }]
        self.assertEqual([], _filter_decided_recommendations(items, snoozed))
        expired = [{
            **snoozed[0],
            "snoozed_until": date.today().isoformat(),
        }]
        self.assertEqual(
            items, _filter_decided_recommendations(items, expired)
        )


if __name__ == "__main__":
    unittest.main()
