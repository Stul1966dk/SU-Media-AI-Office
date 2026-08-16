"""Learning-aware selection (unify pipelines + learn from observations).

Once an experiment's outcome is recorded, the income-first DecisionEngine must
stop repeating a change type that failed on a URL and lean toward a site's
proven change types — without ever overturning the income invariants.
"""

import tempfile
import unittest
from pathlib import Path

from core.database import Database
from core.decision_engine import DecisionEngine
from core.seo_experiment_engine import SEOExperimentEngine
from core.website_registry import WebsiteRegistry


class LearningAwareSelectionTests(unittest.TestCase):
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
        self.registry = WebsiteRegistry(self.database)
        self.engine = DecisionEngine(
            self.database, self.registry,
            experiment_engine=SEOExperimentEngine(self.database),
        )
        self._next_experiment_id = 100

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _period(
        self, path: str, start: str, end: str,
        clicks: int, impressions: int, position: float,
    ) -> None:
        url = f"https://earner.dk{path}"
        for dimension, word in (("page", None), ("page_query", "søgeord")):
            self.database.upsert_search_console_dimension(
                dimension_type=dimension, website_id="earner.dk",
                site_url="https://earner.dk/", page_url=url, query=word,
                period_start=start, period_end=end, clicks=clicks,
                impressions=impressions,
                ctr=clicks / impressions if impressions else 0,
                average_position=position,
            )

    def _clickable_page(self, path: str) -> None:
        # Position 6 with low CTR and no sale -> a title_meta candidate.
        self._period(path, "2026-05-24", "2026-06-20", 5, 2000, 6.0)
        self._period(path, "2026-06-21", "2026-07-18", 5, 2000, 6.0)

    def _learning(self, path: str, change_type: str, classification: str) -> None:
        self._next_experiment_id += 1
        self.database.save_seo_learning_entry({
            "experiment_id": self._next_experiment_id,
            "website_id": "earner.dk",
            "target_url": f"https://earner.dk{path}",
            "change_type": change_type, "target_query": "", "hypothesis": "h",
            "classification": classification, "effect_size": 0,
            "data_quality": "sufficient", "conclusion": "",
            "pattern_level": "Enkelt observation",
            "original_change": {}, "implemented_change": {},
            "baseline": {}, "result": {},
        })

    def _candidate(self, path: str) -> dict:
        ranked = self.engine.rank_candidates(
            self.engine.collect_candidates(include_locked=True)
        )
        return next(
            item for item in ranked
            if item["target_url"] == f"https://earner.dk{path}"
        )

    def test_without_learning_a_clickable_page_is_a_title_meta_test(self) -> None:
        self._clickable_page("/p/")
        self.assertEqual("title_meta", self._candidate("/p/")["experiment_type"])

    def test_a_change_type_that_failed_twice_is_not_repeated(self) -> None:
        self._clickable_page("/p/")
        self._learning("/p/", "title_meta", "Uændret")
        self._learning("/p/", "title_meta", "Forværret")
        candidate = self._candidate("/p/")
        # Steered away from the twice-failed title_meta toward content.
        self.assertEqual("content_update", candidate["experiment_type"])

    def test_repeated_failure_with_no_alternative_is_penalised(self) -> None:
        self._clickable_page("/p/")
        for classification in ("Uændret", "Forværret"):
            self._learning("/p/", "title_meta", classification)
            self._learning("/p/", "content_update", classification)
        candidate = self._candidate("/p/")
        # Both alternatives failed: it keeps a type but is pushed down.
        self.assertLess(candidate["score_factors"]["learning"], 0)

    def test_a_sites_proven_change_type_gets_a_bounded_boost(self) -> None:
        self._clickable_page("/p/")
        for _ in range(3):
            self._learning("/other/", "title_meta", "Forbedret")
        candidate = self._candidate("/p/")
        self.assertGreater(candidate["score_factors"]["learning"], 0)
        self.assertLessEqual(candidate["score_factors"]["learning"], 5.0)


if __name__ == "__main__":
    unittest.main()
