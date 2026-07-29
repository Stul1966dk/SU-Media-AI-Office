"""Regression tests for the temporary recommendation test panel."""

import importlib.util
import unittest
from pathlib import Path

from core.task_deliverables import _prompt


ROOT = Path(__file__).resolve().parents[1]
DAILY_WORK = ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"


def load_daily_work():
    spec = importlib.util.spec_from_file_location(
        "daily_work_forced_panel", DAILY_WORK
    )
    page = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(page)
    return page


class FakeDatabase:
    connection = None

    def get_latest_search_console_diagnosis(self, website_id):
        return {
            "website_id": website_id,
            "loss_pages": [{
                "page_url": f"https://{website_id}/maal/",
                "cause": "Placeringsfald",
                "queries": [{
                    "query": "test søgeord",
                    "click_loss": 9,
                }],
            }],
        }

    def get_content(self, website_id):
        return [
            {
                "url": f"https://{website_id}/maal/",
                "title": "Målside",
            },
            {
                "url": f"https://{website_id}/kilde/",
                "title": "Kildeside",
            },
        ]


class ForcedRecommendationPanelTests(unittest.TestCase):
    def test_all_three_test_modes_build_the_requested_type(self) -> None:
        page = load_daily_work()
        expected = {
            "content_update": ("content_update", "existing_section"),
            "internal_links": ("internal_links", ""),
            "content_gap": ("content_update", "content_gap"),
        }

        for mode, (experiment_type, forced_mode) in expected.items():
            with self.subTest(mode=mode):
                result = page._forced_test_recommendation(
                    FakeDatabase(), website_id="site.dk", mode=mode
                )
                self.assertEqual(experiment_type, result["experiment_type"])
                self.assertEqual(forced_mode, result["forced_content_mode"])
                self.assertEqual("test søgeord", result["target_query"])
                self.assertIn("manual-test", result["task_key"])

    def test_panel_is_session_based_and_can_be_closed(self) -> None:
        source = DAILY_WORK.read_text(encoding="utf-8")

        self.assertIn("Midlertidig test af andre opgavetyper", source)
        self.assertIn("Test indholdsopdatering", source)
        self.assertIn("Test interne links", source)
        self.assertIn("Test content gap", source)
        self.assertIn("Afslut testtilstand", source)
        self.assertIn("FORCED_TEST_MODE_KEY", source)
        self.assertNotIn("set_setting", source)

    def test_forced_mode_constrains_the_ai_prompt(self) -> None:
        base = {
            "website": "site.dk",
            "target_url": "https://site.dk/maal/",
            "target_query": "test søgeord",
            "search_queries": [{"query": "test søgeord", "click_loss": 9}],
            "measured_cause": "Placeringsfald",
            "experiment_type": "content_update",
        }

        existing = _prompt(
            {**base, "forced_content_mode": "existing_section"}, []
        )
        gap = _prompt(
            {**base, "forced_content_mode": "content_gap"}, []
        )

        self.assertIn("skal leveres som existing_section", existing)
        self.assertIn("Denne test skal afprøve et content gap", gap)
        self.assertIn('"forced_content_mode": "content_gap"', gap)


if __name__ == "__main__":
    unittest.main()
