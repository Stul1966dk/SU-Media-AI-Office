"""Sprint 42.7 tests for the persisted priority explanation."""

import importlib.util
import unittest
from pathlib import Path


PAGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
)
SPEC = importlib.util.spec_from_file_location("daily_work_42_7", PAGE_PATH)
PAGE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PAGE)


class PriorityExplanationTests(unittest.TestCase):
    def test_only_positive_persisted_subscores_are_included(self) -> None:
        explanations = PAGE._priority_explanations({
            "task_type": "seo_health",
            "click_change": -17.1,
            "position_change": 2.8,
            "seo_health_trend": "declining",
            "search_console_click_score": 17.0,
            "position_score": 28.0,
            "seo_health_score": 30.0,
            "ctr_score": 0.0,
            "plausible_score": 0.0,
        })
        self.assertEqual(
            ["Search Console", "Placering", "SEO Health"],
            [item[0] for item in explanations],
        )
        self.assertNotIn("CTR", [item[0] for item in explanations])
        self.assertEqual(17.0, explanations[0][2])

    def test_copy_uses_saved_raw_signal_values(self) -> None:
        explanations = PAGE._priority_explanations({
            "task_type": "combined_traffic_decline",
            "plausible_change": -24.6,
            "click_change": -17.14,
            "plausible_score": 22.3,
            "search_console_click_score": 10.3,
        })
        self.assertEqual(
            "Den samlede trafik er faldet 24,6 %.",
            explanations[0][1],
        )
        self.assertEqual(
            "Organiske klik er faldet 17,1 %.",
            explanations[1][1],
        )

    def test_total_is_rendered_from_stored_total_score(self) -> None:
        source = PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn("float(item['total_score'])", source)
        self.assertNotIn("score_priority_item", source)
        self.assertEqual("79,6", PAGE._format_score(79.62))

    def test_website_filter_is_applied_before_selecting_first_task(self) -> None:
        source = PAGE_PATH.read_text(encoding="utf-8")
        filter_position = source.index("if website_id:", source.index(
            "priority_tasks = _build_current_priority_tasks"
        ))
        render_position = source.index("if priority_tasks:", filter_position)
        self.assertLess(filter_position, render_position)


if __name__ == "__main__":
    unittest.main()
