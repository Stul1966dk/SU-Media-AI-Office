"""Sprint 37.3 automatic daily-work preparation tests."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from agents.title_optimizer import TitleOptimizationValidationError
from core.daily_work_preparation import DailyWorkPreparationService
from core.database import Database
from core.seo_experiment_engine import SEOExperimentEngine
from core.website_registry import WebsiteRegistry
from core.work_queue_service import WorkQueueService


class FakeOptimizer:
    def __init__(self, database: Database, error: Exception | None = None):
        self.database = database
        self.error = error
        self.generated = 0

    def analyze_current_snippet(self, candidate):
        return {
            "title": "Gammel title", "meta_description": "Gammel meta",
            "h1": "Guide", "canonical": candidate["target_url"],
            "word_count": 500, "internal_links": 5, "schema": [],
        }

    def analyze_competitors(self, candidate):
        return {"competitors": [], "limitations": []}

    def generate_title_proposals(self, candidate, page, competitors):
        self.generated += 1
        if self.error:
            raise self.error
        return {
            "website": candidate["website"],
            "target_url": candidate["target_url"],
            "target_query": candidate["target_query"],
            "current_title": page["title"], "current_meta": page["meta_description"],
            "page_analysis": {**page, "search_console": {
                "clicks": candidate["clicks"],
                "impressions": candidate["impressions"],
                "ctr": candidate["ctr"], "position": candidate["position"],
            }},
            "analysis": {},
            "title_proposals": [{"text": "Ny komplet guide til flere klik", "reason": "CTR"}],
            "meta_proposals": [{
                "text": "Læs den komplette guide og få et tydeligt overblik over de vigtigste muligheder.",
                "reason": "CTR",
            }],
            "reviewer": {"approved": True},
            "recommended_title_index": 0, "recommended_meta_index": 0,
            "confidence": 85, "expected_effect": "Flere klik",
            "measurement_method": "Sammenlign CTR",
        }

    def create_approval_draft(self, result, competitors):
        return self.database.create_title_optimization_draft(
            result, competitors["competitors"]
        )


class Sprint373DailyPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "daily.db")
        self.database.initialize()
        for website in ("baalfad.dk", "romaskinen.dk"):
            self.database.upsert_website({
                "website": website, "display_name": website,
                "active": True, "monetized": True, "priority": "high",
                "primary_income_source": "affiliate", "niche": "test",
                "domain_age": "1", "notes": "", "status": "active",
            })
        self.registry = WebsiteRegistry(self.database)
        self.queue = WorkQueueService(
            self.database, self.registry,
            experiment_engine=SEOExperimentEngine(self.database),
        )

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def _draft(self, website="baalfad.dk", suffix="guide", approved=True):
        return self.database.create_title_optimization_draft({
            "website": website, "target_url": f"https://{website}/{suffix}/",
            "target_query": "guide", "current_title": "Gammel title",
            "current_meta": "Gammel meta",
            "page_analysis": {"search_console": {"impressions": 1000}},
            "analysis": {},
            "title_proposals": [{"text": "Ny komplet guide til flere klik", "reason": "CTR"}],
            "meta_proposals": [{
                "text": "Læs den komplette guide og få et tydeligt overblik over de vigtigste muligheder.",
                "reason": "CTR",
            }],
            "reviewer": {"approved": approved},
            "recommended_title_index": 0, "recommended_meta_index": 0,
            "confidence": 85, "expected_effect": "Flere klik",
            "measurement_method": "Sammenlign CTR",
        }, [])

    def _raw_candidate(self, website="baalfad.dk", suffix="auto"):
        return {
            "website": website, "target_url": f"https://{website}/{suffix}/",
            "target_query": "guide", "current_clicks": 10,
            "current_impressions": 1000, "current_ctr": .01,
            "current_position": 7, "confidence": 85,
            "expected_effect_reason": "Lav CTR", "priority_score": 90,
        }

    def _service(self, optimizer, candidates=None):
        candidates = candidates or []
        self.queue.decisions = Mock()
        self.queue.decisions.collect_candidates.return_value = candidates
        self.queue.decisions.rank_candidates.side_effect = lambda value: value
        self.queue.decisions.has_conflict.return_value = False
        return DailyWorkPreparationService(
            database=self.database, queue=self.queue,
            title_optimizer=optimizer,
        )

    def test_history_does_not_block_and_reviewed_draft_is_reused(self):
        draft_id = self._draft()
        candidate = self.queue._queue_candidates()[0]
        historical_id = self.database.enqueue_work_candidate(candidate)
        for status in ("implemented", "completed", "cancelled"):
            self.database.update_work_queue_item(
                historical_id, {"status": status}
            )
        optimizer = FakeOptimizer(self.database)
        result = self._service(optimizer).prepare_next("baalfad.dk")
        self.assertIsNotNone(result.item)
        self.assertEqual(draft_id, result.item["draft_id"])
        self.assertEqual(0, optimizer.generated)
        self.assertEqual("queued", result.item["status"])

    def test_generation_is_idempotent_and_filter_is_respected(self):
        optimizer = FakeOptimizer(self.database)
        candidate = self._raw_candidate("romaskinen.dk")
        service = self._service(optimizer, [candidate])
        first = service.prepare_next("romaskinen.dk")
        second = service.prepare_next("romaskinen.dk")
        self.assertEqual("romaskinen.dk", first.item["website_id"])
        self.assertEqual(first.item["id"], second.item["id"])
        self.assertEqual(1, optimizer.generated)
        self.assertEqual(1, len(self.database.get_title_optimization_drafts()))
        self.assertEqual(1, len(self.database.get_work_queue(("queued",))))

    def test_parallel_calls_generate_only_once(self):
        results, optimizers = [], []
        candidate = self._raw_candidate()

        def prepare():
            database = Database(self.database.path)
            database.initialize()
            queue = WorkQueueService(database, WebsiteRegistry(database))
            queue.decisions = Mock()
            queue.decisions.collect_candidates.return_value = [candidate]
            queue.decisions.rank_candidates.side_effect = lambda value: value
            queue.decisions.has_conflict.return_value = False
            optimizer = FakeOptimizer(database)
            optimizers.append(optimizer)
            result = DailyWorkPreparationService(
                database=database, queue=queue, title_optimizer=optimizer
            ).prepare_next()
            results.append(result)
            database.close()

        threads = [threading.Thread(target=prepare) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, sum(item.generated for item in optimizers))
        self.assertEqual(1, len({result.item["id"] for result in results}))

    def test_generation_and_reviewer_failures_leave_no_active_work(self):
        errors = (
            RuntimeError("OpenAI fejlede"),
            TitleOptimizationValidationError(
                "Reviewer afviste", phase="review"
            ),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                optimizer = FakeOptimizer(self.database, error)
                result = self._service(
                    optimizer, [self._raw_candidate(suffix=type(error).__name__)]
                ).prepare_next()
                self.assertIsNone(result.item)
                self.assertIn(result.reason, {"generation_failed", "reviewer_failed"})
                self.assertEqual([], self.database.get_work_queue(("queued",)))
                self.assertEqual([], self.database.get_title_optimization_drafts())

    def test_locked_candidate_is_not_generated(self):
        optimizer = FakeOptimizer(self.database)
        service = self._service(optimizer, [self._raw_candidate()])
        self.queue.experiments = Mock()
        self.queue.experiments.is_url_locked.return_value = True
        result = service.prepare_next()
        self.assertEqual("all_candidates_locked", result.reason)
        self.assertEqual(0, optimizer.generated)


if __name__ == "__main__":
    unittest.main()
