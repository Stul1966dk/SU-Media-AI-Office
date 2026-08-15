"""Type-aware delivery (P0).

The income-first DecisionEngine selects non-title experiments (monetisation,
content, links). The daily work queue must deliver them end-to-end — enqueue,
surface, approve and implement — as their own type, not force them into a
title/meta test.
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class _FakeAI:
    """Return one canned model response for deliverable generation."""

    def __init__(self, text: str) -> None:
        self._text = text

    def generate_response(self, prompt: str, tools=None):
        return SimpleNamespace(text=self._text)


_MONETIZATION_DELIVERABLE = json.dumps({
    "deliverable_type": "monetization",
    "summary": "Tilføj en sammenligningstabel med de omtalte løbebånd.",
    "recommended_option": (
        "Indsæt en sammenligningstabel med tre løbebånd (model, motor, "
        "foldbar, pris-niveau) og en 'Se pris'-affiliate-knap ved hver række."
    ),
    "rationale": (
        "Siden har trafik men ingen provision; en tabel konverterer den "
        "eksisterende trafik til kommission."
    ),
    "alternatives": [
        "En enkelt fremhævet købsknap øverst på siden",
        "En liste med affiliate-links til hver omtalt model",
    ],
    "implementation_steps": [
        "Åbn siden i WordPress",
        "Indsæt sammenligningstabellen efter introafsnittet",
        "Tilføj affiliate-links til hver række",
    ],
    "validation_checks": ["Alle links peger på gyldige produkter"],
    "content_location": "Efter introafsnittet",
    "current_state": "Ingen produktanbefaling på siden",
    "opportunity_type": "comparison_table",
    "evidence": "1222 visninger, 0 kr i provision",
}, ensure_ascii=False)

from core.daily_work_preparation import DailyWorkPreparationService
from core.database import Database
from core.decision_engine import DecisionEngine
from core.seo_experiment_engine import SEOExperimentEngine
from core.website_registry import WebsiteRegistry
from core.work_queue_service import WorkQueueService


class TypeAwareDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        self.database.upsert_website({
            "website": "earner.dk", "display_name": "earner.dk", "active": True,
            "monetized": True, "priority": "high",
            "primary_income_source": "affiliate", "niche": "test",
            "domain_age": "1", "notes": "", "status": "active",
        })
        # A page with real traffic on page 2 and no commission, on a site that
        # earns elsewhere -> a monetisation-gap candidate.
        for start, end in (
            ("2026-05-24", "2026-06-20"), ("2026-06-21", "2026-07-18"),
        ):
            self.database.upsert_search_console_dimension(
                dimension_type="page", website_id="earner.dk",
                site_url="https://earner.dk/", page_url="https://earner.dk/gap/",
                period_start=start, period_end=end, clicks=2, impressions=2000,
                ctr=0.001, average_position=18,
            )
        self.database.upsert_partner_ads_sale({
            "kombiid": "k1", "provision": "500", "url": "https://earner.dk/",
            "uid": "/andet/", "uid2": "", "valuta": "DKK", "dato": "01-06-2026",
        })
        self.registry = WebsiteRegistry(self.database)
        self.queue = WorkQueueService(
            self.database, self.registry,
            experiment_engine=SEOExperimentEngine(self.database),
            decision_engine=DecisionEngine(
                self.database, self.registry,
                experiment_engine=SEOExperimentEngine(self.database),
            ),
        )

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _prepare(self) -> dict:
        service = DailyWorkPreparationService(
            database=self.database, queue=self.queue,
            title_optimizer=Mock(),  # unused for a non-title candidate
        )
        return service.prepare_next("earner.dk").item

    def test_monetisation_candidate_is_delivered_as_itself(self) -> None:
        item = self._prepare()
        self.assertIsNotNone(item)
        self.assertEqual("https://earner.dk/gap/", item["target_url"])
        # Not forced into a title draft.
        self.assertIsNone(item.get("draft_id"))
        self.assertEqual(
            "monetization", item["candidate"]["experiment_type"]
        )
        self.assertTrue(
            str(item["implementation"]["recommended_change"]).strip()
        )
        # The queue surfaces it as actionable (no title required).
        current = self.queue.current("earner.dk")
        self.assertEqual(item["id"], current["id"])

    def test_a_finished_ai_deliverable_is_used_when_available(self) -> None:
        optimizer = Mock()
        optimizer.ai_service = _FakeAI(_MONETIZATION_DELIVERABLE)
        service = DailyWorkPreparationService(
            database=self.database, queue=self.queue, title_optimizer=optimizer,
        )
        item = service.prepare_next("earner.dk").item
        change = item["implementation"]["recommended_change"]
        # The queue carries the finished, paste-ready element, not the generic
        # "foreslå en konkret monetisering" instruction.
        self.assertIn("sammenligningstabel", change)
        self.assertNotIn("Foreslå en konkret monetisering", change)
        self.assertTrue(item["implementation"]["steps"])

    def test_approve_and_implement_create_a_commission_experiment(self) -> None:
        item = self._prepare()
        result = self.queue.approve(item["id"])  # no title/meta for non-title
        experiment = self.database.get_seo_experiment(result["experiment_id"])
        self.assertEqual("monetization", experiment["experiment_type"])
        self.assertEqual("commission", experiment["goal_metric"])
        started = self.queue.mark_implemented(result["experiment_id"] and item["id"])
        self.assertIn(
            started["status"], {"waiting_for_data", "running"}
        )


if __name__ == "__main__":
    unittest.main()
