"""Tests for deterministic SEO history analysis."""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from core.database import Database
from core.dashboard import Dashboard
from core.seo_history import analyze_all_sites, analyze_site


class SEOHistoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(
            Path(self.temporary_directory.name) / "office.sqlite3"
        )
        self.database.initialize()
        for website in ("alpha.dk", "beta.dk"):
            self.database.upsert_website(
                {
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
                }
            )
        self.reference_date = date(2026, 7, 17)

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def add_metric(
        self,
        website: str,
        offset: int,
        clicks: int,
        impressions: int,
        position: float,
    ) -> None:
        self.database.upsert_search_console_daily_metric(
            website_id=website,
            site_url=f"sc-domain:{website}",
            metric_date=(
                self.reference_date - timedelta(days=offset)
            ).isoformat(),
            clicks=clicks,
            impressions=impressions,
            ctr=clicks / impressions,
            average_position=position,
        )

    def test_all_period_change_methods(self) -> None:
        for offset in range(1, 181):
            current = offset <= 90
            self.add_metric(
                "alpha.dk",
                offset,
                clicks=20 if current else 10,
                impressions=200,
                position=4.0 if current else 6.0,
            )

        clicks = self.database.get_click_change(
            "alpha.dk", self.reference_date
        )
        impressions = self.database.get_impression_change(
            "alpha.dk", self.reference_date
        )
        ctr = self.database.get_ctr_change(
            "alpha.dk", self.reference_date
        )
        positions = self.database.get_position_change(
            "alpha.dk", self.reference_date
        )

        self.assertEqual(
            [item["period"] for item in clicks],
            ["7d", "28d", "90d"],
        )
        self.assertEqual(
            [item["change"] for item in clicks],
            [0.0, 0.0, 100.0],
        )
        for item in impressions:
            self.assertAlmostEqual(item["change"], 0.0)
        self.assertEqual(
            [item["change"] for item in ctr],
            [0.0, 0.0, 5.0],
        )
        self.assertEqual(
            [item["change"] for item in positions],
            [0.0, 0.0, -2.0],
        )

    def test_analyze_site_returns_all_periods_and_bounded_scores(self) -> None:
        for offset in range(1, 181):
            self.add_metric(
                "alpha.dk",
                offset,
                clicks=200 - offset,
                impressions=1000,
                position=3.0 + (offset / 100),
            )
        health = analyze_site(
            self.database,
            "alpha.dk",
            self.reference_date,
        )
        self.assertEqual([item.period for item in health], ["7d", "28d", "90d"])
        self.assertTrue(all(0 <= item.score <= 100 for item in health))
        self.assertEqual(health[-1].trend, "growing")
        self.assertTrue(
            all(
                item.trend
                in {"growing", "stable", "declining", "critical"}
                for item in health
            )
        )

    def test_analyze_all_sites_has_no_duplicates_and_updates_history(
        self,
    ) -> None:
        for offset in range(1, 181):
            self.add_metric(
                "alpha.dk",
                offset,
                clicks=200 - offset,
                impressions=1000,
                position=3.0 + (offset / 100),
            )
            self.add_metric(
                "beta.dk",
                offset,
                clicks=offset,
                impressions=1000,
                position=3.0 + ((181 - offset) / 100),
            )

        first = analyze_all_sites(self.database, self.reference_date)
        original = self.database.get_seo_health_history(
            "alpha.dk", "7d"
        )[0]["score"]
        self.add_metric(
            "alpha.dk",
            1,
            clicks=0,
            impressions=1000,
            position=20.0,
        )
        second = analyze_all_sites(self.database, self.reference_date)
        history = self.database.get_seo_health_history()
        updated = self.database.get_seo_health_history(
            "alpha.dk", "7d"
        )[0]["score"]

        self.assertEqual(len(first), 6)
        self.assertEqual(len(second), 6)
        self.assertEqual(len(history), 6)
        self.assertNotEqual(original, updated)
        summary = self.database.get_seo_health_summary("28d")
        self.assertEqual(sum(summary.values()), 2)
        lowest = self.database.get_lowest_seo_scores()
        self.assertEqual(len(lowest), 2)
        self.assertLessEqual(lowest[0]["score"], lowest[1]["score"])

    def test_dashboard_shows_seo_health_counts(self) -> None:
        for trend, website in (("growing", "alpha.dk"), ("critical", "beta.dk")):
            self.database.upsert_seo_health(
                website_id=website,
                analysis_date=self.reference_date.isoformat(),
                period="28d",
                score=80 if trend == "growing" else 10,
                trend=trend,
                click_change=10,
                impression_change=5,
                ctr_change=1,
                position_change=-1,
            )
        output = Dashboard(self.database).render(
            None,
            seo_health_status=self.database.get_seo_health_summary(),
        )
        self.assertIn("SEO Health", output)
        self.assertIn("Growing                      1", output)
        self.assertIn("Critical                     1", output)


if __name__ == "__main__":
    unittest.main()
