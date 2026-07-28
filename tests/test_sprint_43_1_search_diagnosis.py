"""Sprint 43.1 tests for deterministic Search Console diagnosis."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.database import Database
from core.search_console_diagnosis import (
    SearchConsoleDiagnosisService,
    build_search_console_diagnosis,
)


def page(
    url: str,
    previous_clicks: int,
    current_clicks: int,
    *,
    previous_impressions: int = 1000,
    current_impressions: int = 800,
    previous_ctr: float = .06,
    current_ctr: float = .04,
    previous_position: float = 4,
    current_position: float = 4,
) -> dict:
    return {
        "page_url": url,
        "previous_clicks": previous_clicks,
        "current_clicks": current_clicks,
        "click_change": current_clicks - previous_clicks,
        "previous_impressions": previous_impressions,
        "current_impressions": current_impressions,
        "previous_ctr": previous_ctr,
        "current_ctr": current_ctr,
        "previous_position": previous_position,
        "current_position": current_position,
        "period_start": "2026-07-01",
        "period_end": "2026-07-28",
        "previous_period_start": "2026-06-03",
        "previous_period_end": "2026-06-30",
    }


class ComparisonService:
    def __init__(self, pages, page_queries):
        self.pages = pages
        self.page_queries = page_queries

    def get_dimension_comparisons(self, _website, dimension_type):
        return self.pages if dimension_type == "page" else self.page_queries


class SearchConsoleDiagnosisTests(unittest.TestCase):
    def test_loss_pages_are_ranked_and_queries_are_attached(self):
        pages = [
            page(
                "https://site.dk/a", 60, 25,
                previous_position=3, current_position=5,
            ),
            page(
                "https://site.dk/b", 40, 30,
                previous_impressions=1000, current_impressions=600,
                previous_ctr=.04, current_ctr=.05,
            ),
        ]
        queries = [
            {
                **page("https://site.dk/a", 20, 5),
                "query": "vigtigt søgeord",
            },
            {
                **page("https://site.dk/a", 10, 8),
                "query": "andet søgeord",
            },
        ]

        result = build_search_console_diagnosis(
            "site.dk", pages, queries
        )

        self.assertEqual("ready", result["status"])
        self.assertEqual(45, result["click_loss"])
        self.assertEqual("https://site.dk/a", result["loss_pages"][0]["page_url"])
        self.assertEqual("Placeringsfald", result["loss_pages"][0]["cause"])
        self.assertEqual(
            "Lavere søgeefterspørgsel", result["loss_pages"][1]["cause"]
        )
        self.assertEqual(
            "vigtigt søgeord",
            result["loss_pages"][0]["queries"][0]["query"],
        )
        self.assertEqual(100.0, result["explained_loss_share"])

    def test_low_volume_is_saved_as_insufficient_without_page_guess(self):
        result = build_search_console_diagnosis(
            "small.dk", [page("https://small.dk/", 10, 2)], []
        )

        self.assertEqual("insufficient_data", result["status"])
        self.assertEqual([], result["loss_pages"])
        self.assertIn("minimum er 20", result["reason"])

    def test_growth_has_no_loss_pages(self):
        result = build_search_console_diagnosis(
            "growth.dk", [page("https://growth.dk/", 30, 40)], []
        )

        self.assertEqual("no_decline", result["status"])
        self.assertEqual(0, result["click_loss"])
        self.assertEqual([], result["loss_pages"])

    def test_small_site_decline_is_treated_as_noise(self):
        result = build_search_console_diagnosis(
            "noise.dk", [page("https://noise.dk/", 100, 97)], []
        )

        self.assertEqual("minor_decline", result["status"])
        self.assertEqual([], result["loss_pages"])
        self.assertIn("støjgrænsen", result["reason"])

    def test_cross_domain_page_is_excluded_from_diagnosis(self):
        result = build_search_console_diagnosis(
            "site.dk",
            [
                page("https://site.dk/egen/", 30, 15),
                page("https://other.dk/fremmed/", 100, 0),
            ],
            [],
        )

        self.assertEqual(30, result["previous_clicks"])
        self.assertEqual("ready", result["status"])
        self.assertEqual(
            ["https://site.dk/egen/"],
            [item["page_url"] for item in result["loss_pages"]],
        )

    def test_missing_periods_are_not_persisted(self):
        database = Mock()
        service = SearchConsoleDiagnosisService(
            database, ComparisonService([], [])
        )

        result = service.analyze_site("missing.dk")

        self.assertEqual("missing_periods", result["status"])
        self.assertEqual("skipped", result["write_action"])
        database.upsert_search_console_diagnosis.assert_not_called()


class SearchConsoleDiagnosisPersistenceTests(unittest.TestCase):
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

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_diagnosis_is_persisted_idempotently(self):
        comparisons = ComparisonService(
            [page("https://site.dk/a", 30, 20)], []
        )
        service = SearchConsoleDiagnosisService(
            self.database, comparisons
        )

        first = service.analyze_site("site.dk")
        second = service.analyze_site("site.dk")
        stored = self.database.get_latest_search_console_diagnosis("site.dk")

        self.assertEqual("created", first["write_action"])
        self.assertEqual("unchanged", second["write_action"])
        self.assertEqual("ready", stored["status"])
        self.assertEqual(10, stored["click_loss"])


if __name__ == "__main__":
    unittest.main()
