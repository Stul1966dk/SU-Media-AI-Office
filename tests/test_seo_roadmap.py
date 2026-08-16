"""Per-website SEO roadmap (Fase 2).

The roadmap combines Search Console, Partner-ads commission and Plausible into
concrete goals and an income-first experiment sequence, so each website has a
strategic plan the daily work moves toward.
"""

import tempfile
import unittest
from pathlib import Path

from core.database import Database
from core.seo_roadmap import build_website_roadmap


class SEORoadmapTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _page(
        self, path: str, position: float, clicks: int, impressions: int,
    ) -> None:
        url = f"https://shop.dk{path}"
        for start, end in (
            ("2026-05-24", "2026-06-20"), ("2026-06-21", "2026-07-18"),
        ):
            self.database.upsert_search_console_dimension(
                dimension_type="page", website_id="shop.dk",
                site_url="https://shop.dk/", page_url=url,
                period_start=start, period_end=end, clicks=clicks,
                impressions=impressions,
                ctr=clicks / impressions if impressions else 0,
                average_position=position,
            )

    def _query(
        self, path: str, query: str, position: float,
        clicks: int, impressions: int,
    ) -> None:
        url = f"https://shop.dk{path}"
        for start, end in (
            ("2026-05-24", "2026-06-20"), ("2026-06-21", "2026-07-18"),
        ):
            self.database.upsert_search_console_dimension(
                dimension_type="page_query", website_id="shop.dk",
                site_url="https://shop.dk/", page_url=url, query=query,
                period_start=start, period_end=end, clicks=clicks,
                impressions=impressions,
                ctr=clicks / impressions if impressions else 0,
                average_position=position,
            )

    def _sale(self, path: str, provision: str) -> None:
        self.database.upsert_partner_ads_sale({
            "kombiid": f"k{path}", "provision": provision,
            "url": "https://shop.dk/", "uid": path, "uid2": "",
            "valuta": "DKK", "dato": "01-06-2026",
        })

    def _seed_portfolio(self) -> None:
        # A high-traffic page on page 2 that earns nothing: a monetisation gap.
        self._page("/gap/", position=18, clicks=5, impressions=2000)
        self._query("/gap/", "billig romaskine", position=12,
                    clicks=1, impressions=500)
        # A page that already earns and ranks on page 1: worth growing.
        self._page("/tjener/", position=6, clicks=40, impressions=1500)
        self._query("/tjener/", "romaskine test", position=4,
                    clicks=30, impressions=300)
        self._sale("/tjener/", "1000")
        for day in range(1, 6):
            self.database.upsert_plausible_daily_metric(
                website_id="shop.dk", metric_date=f"2026-07-1{day}",
                visitors=100,
            )

    def test_roadmap_summary_combines_the_sources(self) -> None:
        self._seed_portfolio()
        roadmap = build_website_roadmap(self.database, "shop.dk")
        summary = roadmap["summary"]
        self.assertEqual(3500, summary["impressions"])  # 2000 + 1500
        self.assertEqual(45, summary["clicks"])          # 5 + 40
        self.assertEqual(1000.0, summary["commission"])  # only /tjener/ earns
        self.assertEqual(500, summary["visitors_28d"])   # 5 days x 100
        self.assertGreater(summary["avg_position"], 10)  # weighted by the gap

    def test_goals_identify_gap_striking_and_earner(self) -> None:
        self._seed_portfolio()
        roadmap = build_website_roadmap(self.database, "shop.dk")
        by_type = {goal["type"]: goal for goal in roadmap["goals"]}
        self.assertIn("monetization_gap", by_type)
        self.assertIn("striking_distance", by_type)
        self.assertIn("earner_growth", by_type)
        gap_urls = [item["url"] for item in by_type["monetization_gap"]["items"]]
        self.assertIn("https://shop.dk/gap/", gap_urls)
        striking = [
            item["query"] for item in by_type["striking_distance"]["items"]
        ]
        self.assertIn("billig romaskine", striking)
        self.assertNotIn("romaskine test", striking)  # position 4 is not striking
        earners = [item["url"] for item in by_type["earner_growth"]["items"]]
        self.assertIn("https://shop.dk/tjener/", earners)

    def test_recommended_sequence_is_income_first(self) -> None:
        self._seed_portfolio()
        roadmap = build_website_roadmap(self.database, "shop.dk")
        sequence = roadmap["recommended_sequence"]
        self.assertTrue(sequence)
        # The traffic-rich, non-earning page surfaces as a commission experiment.
        gap = next(
            item for item in sequence
            if item["target_url"] == "https://shop.dk/gap/"
        )
        self.assertEqual("monetization", gap["experiment_type"])
        self.assertEqual("commission", gap["goal_metric"])

    def test_content_gap_goal_lists_underserved_keywords(self) -> None:
        # /guide/ focuses on "guide"; "billig romaskine" is a secondary keyword
        # with demand ranking on page 2 -> a content gap for new content.
        self._page("/guide/", position=8, clicks=5, impressions=1500)
        self._query("/guide/", "guide", position=4, clicks=30, impressions=1000)
        self._query("/guide/", "billig romaskine", position=22,
                    clicks=1, impressions=300)
        roadmap = build_website_roadmap(self.database, "shop.dk")
        by_type = {goal["type"]: goal for goal in roadmap["goals"]}
        self.assertIn("content_gap", by_type)
        self.assertEqual("position", by_type["content_gap"]["metric"])
        queries = [item["query"] for item in by_type["content_gap"]["items"]]
        self.assertIn("billig romaskine", queries)
        self.assertNotIn("guide", queries)  # the page's focus keyword is no gap

    def test_empty_website_yields_no_goals_and_a_safe_narrative(self) -> None:
        roadmap = build_website_roadmap(self.database, "shop.dk")
        self.assertEqual([], roadmap["goals"])
        self.assertIn("endnu ikke nok", roadmap["narrative"])


if __name__ == "__main__":
    unittest.main()
