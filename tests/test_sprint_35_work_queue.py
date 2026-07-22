"""Sprint 35 persistent daily work queue regression tests."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.database import Database
from core.seo_experiment_engine import SEOExperimentEngine
from core.website_registry import WebsiteRegistry
from core.work_queue_service import WorkQueueService


class Sprint35WorkQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "queue.db")
        self.database.initialize()
        for website in ("high.dk", "other.dk"):
            self.database.upsert_website({
                "website": website, "display_name": website, "active": True,
                "monetized": True, "priority": "high",
                "primary_income_source": "affiliate", "niche": "test",
                "domain_age": "1", "notes": "", "status": "active",
            })
        self.registry = WebsiteRegistry(self.database)
        self.experiments = SEOExperimentEngine(self.database)
        self.queue = WorkQueueService(
            self.database, self.registry, experiment_engine=self.experiments
        )

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _period(
        self, website: str, url: str, query: str,
        start: str, end: str, clicks: int, impressions: int,
    ) -> None:
        for dimension, page, word in (
            ("page", url, None),
            ("page_query", url, query),
        ):
            self.database.upsert_search_console_dimension(
                dimension_type=dimension, website_id=website,
                site_url=f"https://{website}/", page_url=page, query=word,
                period_start=start, period_end=end, clicks=clicks,
                impressions=impressions, ctr=clicks / impressions,
                average_position=7,
            )

    def _evidence(self) -> None:
        for website, clicks, impressions in (
            ("high.dk", 400, 6000), ("other.dk", 20, 500),
        ):
            url = f"https://{website}/guide/"
            self._period(
                website, url, "guide", "2026-05-24", "2026-06-20",
                clicks + 100, impressions - 100,
            )
            self._period(
                website, url, "guide", "2026-06-21", "2026-07-18",
                clicks, impressions,
            )

    def _reviewed_draft(self, website: str, score: int = 80) -> int:
        return self.database.create_title_optimization_draft({
            "website": website, "target_url": f"https://{website}/guide/",
            "target_query": "guide", "current_title": "Gammel guide",
            "current_meta": "Gammel metabeskrivelse",
            "page_analysis": {"search_console": {"impressions": 1000}},
            "analysis": {},
            "title_proposals": [{
                "text": f"Ny guide til {website}", "reason": "CTR",
            }],
            "meta_proposals": [{
                "text": "Læs den opdaterede guide og få et hurtigt overblik over de vigtigste valg.",
                "reason": "CTR",
            }],
            "reviewer": {"approved": True},
            "recommended_title_index": 0, "recommended_meta_index": 0,
            "confidence": score, "expected_effect": "Flere klik",
            "measurement_method": "Sammenlign CTR",
        }, [])

    def test_queue_is_saved_sorted_and_not_recalculated_for_next(self) -> None:
        self._evidence()
        self._reviewed_draft("high.dk", 90)
        self._reviewed_draft("other.dk", 75)
        first_snapshot = self.queue.ensure_queue()
        self.assertEqual(2, len(first_snapshot))
        self.assertGreaterEqual(
            first_snapshot[0]["priority_score"],
            first_snapshot[1]["priority_score"],
        )
        with patch.object(
            self.queue.decisions, "collect_candidates",
            side_effect=AssertionError("Køen må ikke genberegnes"),
        ):
            second_snapshot = self.queue.ensure_queue()
        self.assertEqual(
            [item["id"] for item in first_snapshot],
            [item["id"] for item in second_snapshot],
        )

    def test_skip_moves_item_to_bottom_and_logs_optional_reason(self) -> None:
        self._evidence()
        self._reviewed_draft("high.dk", 90)
        self._reviewed_draft("other.dk", 75)
        original = self.queue.current()
        self.queue.skip(original["id"], "Arbejder på siden i morgen")
        current = self.queue.current()
        self.assertNotEqual(original["id"], current["id"])
        self.assertEqual(
            "Arbejder på siden i morgen",
            self.database.get_work_queue_skips(original["id"])[0]["reason"],
        )

    def test_raw_decision_candidate_is_not_daily_work(self) -> None:
        self._evidence()
        candidates = self.queue.decisions.rank_candidates(
            self.queue.decisions.collect_candidates()
        )
        self.database.replace_queued_work(candidates)
        self.assertIsNone(self.queue.current())
        rows = self.database.get_work_queue(("queued",))
        self.assertTrue(rows)
        self.assertTrue(all(item["status"] == "queued" for item in rows))

    def test_global_and_exact_website_filters(self) -> None:
        self._reviewed_draft("high.dk", 90)
        self._reviewed_draft("other.dk", 75)
        self.assertEqual("high.dk", self.queue.current()["website_id"])
        self.assertEqual(
            "other.dk", self.queue.current("other.dk")["website_id"]
        )
        self.assertEqual("high.dk", self.queue.current("high.dk")["website_id"])
        self.assertIsNone(self.queue.current("missing.dk"))

    def test_skip_and_url_lock_stay_inside_filter(self) -> None:
        self._reviewed_draft("high.dk", 90)
        self._reviewed_draft("other.dk", 75)
        high = self.queue.current("high.dk")
        self.queue.skip(high["id"])
        self.assertIsNone(self.queue.current("high.dk"))
        self.assertEqual("other.dk", self.queue.current()["website_id"])
        with patch.object(
            self.experiments, "is_url_locked", return_value=True
        ):
            self.assertIsNone(self.queue.current("other.dk"))


if __name__ == "__main__":
    unittest.main()
