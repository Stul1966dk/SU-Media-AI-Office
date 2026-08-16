"""Content-gap detection (Fase 3: new keywords / new articles).

A query with real demand that a page shows up for but does not focus on — it
ranks poorly because no page is dedicated to it — becomes a content_gap
experiment: propose dedicated content, measured on the query's page ranking.
"""

import tempfile
import unittest
from pathlib import Path

from core.database import Database
from core.decision_engine import DecisionEngine
from core.seo_experiment_engine import SEOExperimentEngine
from core.website_registry import WebsiteRegistry


class ContentGapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        self.database.upsert_website({
            "website": "shop.dk", "display_name": "shop.dk", "active": True,
            "monetized": True, "priority": "high",
            "primary_income_source": "affiliate", "niche": "test",
            "domain_age": "1", "notes": "", "status": "active",
        })
        self.registry = WebsiteRegistry(self.database)
        self.engine = DecisionEngine(
            self.database, self.registry,
            experiment_engine=SEOExperimentEngine(self.database),
        )

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _query(
        self, path: str, query: str, position: float, impressions: int,
    ) -> None:
        url = f"https://shop.dk{path}"
        for start, end in (
            ("2026-05-24", "2026-06-20"), ("2026-06-21", "2026-07-18"),
        ):
            self.database.upsert_search_console_dimension(
                dimension_type="page_query", website_id="shop.dk",
                site_url="https://shop.dk/", page_url=url, query=query,
                period_start=start, period_end=end, clicks=1,
                impressions=impressions,
                ctr=1 / impressions if impressions else 0,
                average_position=position,
            )

    def _candidates(self) -> list:
        return self.engine.rank_candidates(
            self.engine.collect_candidates(include_locked=True)
        )

    def test_an_underserved_secondary_keyword_becomes_a_content_gap(
        self,
    ) -> None:
        # /guide/ focuses on "guide" (top, good position); "billig løbebånd" is a
        # secondary keyword with demand that ranks on page 3 -> a content gap.
        self._query("/guide/", "guide", position=4, impressions=1000)
        self._query("/guide/", "billig løbebånd", position=22, impressions=300)
        gaps = [
            c for c in self._candidates()
            if c["experiment_type"] == "content_gap"
        ]
        self.assertEqual(1, len(gaps))
        gap = gaps[0]
        self.assertEqual("billig løbebånd", gap["target_query"])
        self.assertEqual("https://shop.dk/guide/", gap["target_url"])
        self.assertEqual("position", gap["goal_metric"])
        self.assertEqual("content_gap", gap["forced_content_mode"])

    def test_the_pages_focus_keyword_is_not_a_gap(self) -> None:
        self._query("/guide/", "guide", position=4, impressions=1000)
        self._query("/guide/", "billig løbebånd", position=22, impressions=300)
        self.assertFalse(any(
            c["experiment_type"] == "content_gap" and c["target_query"] == "guide"
            for c in self._candidates()
        ))

    def test_a_well_ranked_secondary_keyword_is_not_a_gap(self) -> None:
        # Secondary keyword but already on page 1 -> no gap.
        self._query("/guide/", "guide", position=4, impressions=1000)
        self._query("/guide/", "løbebånd test", position=6, impressions=300)
        self.assertFalse(any(
            c["experiment_type"] == "content_gap" for c in self._candidates()
        ))


if __name__ == "__main__":
    unittest.main()
