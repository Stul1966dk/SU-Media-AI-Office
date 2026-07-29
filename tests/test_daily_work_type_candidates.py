import unittest
from pathlib import Path

from core.traffic_recommendations import expand_daily_work_types


ROOT = Path(__file__).resolve().parents[1]
DAILY_WORK = ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"


def recommendation(cause="Placeringsfald"):
    return {
        "task_key": "search|site.dk|maal",
        "task_type": "search_only_decline",
        "website": "site.dk",
        "target_url": "https://site.dk/maal/",
        "target_query": "test søgeord",
        "search_queries": [
            {"query": "test søgeord", "click_loss": 9},
            {"query": "relevant spørgsmål", "click_loss": 4},
        ],
        "measured_cause": cause,
        "description": "Oprindelig anbefaling",
        "recommended_action": "Oprindelig handling",
        "total_score": 42.0,
    }


class DailyWorkTypeCandidateTests(unittest.TestCase):
    def test_position_decline_creates_three_normal_candidates(self):
        result = expand_daily_work_types(
            [recommendation()],
            content_urls_by_website={
                "site.dk": [
                    "https://site.dk/maal/",
                    "https://site.dk/relevant-kilde/",
                ],
            },
        )

        self.assertEqual(
            {"content_update", "content_gap", "internal_links"},
            {item["daily_work_type"] for item in result},
        )
        self.assertEqual(3, len({item["task_key"] for item in result}))
        by_type = {item["daily_work_type"]: item for item in result}
        self.assertEqual(
            "existing_section",
            by_type["content_update"]["forced_content_mode"],
        )
        self.assertEqual(
            "content_gap",
            by_type["content_gap"]["forced_content_mode"],
        )
        self.assertEqual(
            "internal_links",
            by_type["internal_links"]["experiment_type"],
        )

    def test_internal_link_requires_another_known_page(self):
        result = expand_daily_work_types(
            [recommendation()],
            content_urls_by_website={
                "site.dk": ["https://site.dk/maal/"],
            },
        )

        self.assertNotIn(
            "internal_links",
            {item["daily_work_type"] for item in result},
        )

    def test_content_gap_requires_search_query_evidence(self):
        item = recommendation()
        item["search_queries"] = []

        result = expand_daily_work_types(
            [item],
            content_urls_by_website={"site.dk": []},
        )

        self.assertEqual(
            ["content_update"],
            [row["daily_work_type"] for row in result],
        )

    def test_ctr_decline_creates_title_meta_candidate(self):
        result = expand_daily_work_types(
            [recommendation("CTR-fald")],
            content_urls_by_website={"site.dk": ["https://site.dk/anden/"]},
        )

        self.assertEqual(1, len(result))
        self.assertEqual("title_meta", result[0]["daily_work_type"])
        self.assertEqual("title_meta", result[0]["experiment_type"])

    def test_temporary_developer_panel_is_removed(self):
        source = DAILY_WORK.read_text(encoding="utf-8")

        self.assertNotIn("Udviklerværktøjer · midlertidig test", source)
        self.assertNotIn("Test indholdsopdatering", source)
        self.assertNotIn("Test interne links", source)
        self.assertNotIn("Test content gap", source)
        self.assertNotIn("FORCED_TEST_MODE_KEY", source)


if __name__ == "__main__":
    unittest.main()
