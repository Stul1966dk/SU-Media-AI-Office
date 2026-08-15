"""Sprint 42.5 tests for combined Search Console and Plausible tasks."""

import unittest
from datetime import date, timedelta
from pathlib import Path

from dashboard.components.data import (
    build_combined_traffic_tasks,
    build_dashboard_priority_tasks,
)


TODAY = date(2026, 7, 24)


def plausible_rows(
    website: str,
    *,
    current: int = 8,
    previous: int = 10,
    complete: bool = True,
):
    return [
        {
            "website": website,
            "metric_date": (TODAY - timedelta(days=offset)).isoformat(),
            "visitors": current if offset <= 7 else previous,
        }
        for offset in range(1, 15 if complete else 14)
    ]


class CombinedTrafficTaskTests(unittest.TestCase):
    def test_combined_decline_is_critical_and_replaces_plausible_task(self) -> None:
        tasks = build_dashboard_priority_tasks(
            system_status={},
            seo_sites=[{
                "website": "combined.dk",
                "trend": "declining",
                "click_change": -25,
                "position_change": 2,
            }],
            project_tasks=[],
            experiments=[],
            coverage=[],
            plausible_rows=plausible_rows("combined.dk"),
            today=TODAY,
        )

        combined = [
            item for item in tasks
            if item.get("task_type") == "combined_traffic_decline"
        ]
        standalone = [
            item for item in tasks
            if item["description"] == "Plausible-trafikken er faldet."
        ]
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]["priority"], "Kritisk")
        self.assertEqual(combined[0]["change"], "-20,0 %")
        self.assertEqual(
            combined[0]["search_console_change"],
            "klik -25,0 % og placering +2,0",
        )
        self.assertEqual(standalone, [])
        self.assertEqual(tasks[0], combined[0])

    def test_position_only_decline_is_high_and_still_first(self) -> None:
        tasks = build_dashboard_priority_tasks(
            system_status={},
            seo_sites=[{
                "website": "position.dk",
                "trend": "declining",
                "click_change": 5,
                "position_change": 1.5,
            }],
            project_tasks=[],
            experiments=[],
            coverage=[],
            plausible_rows=plausible_rows("position.dk"),
            today=TODAY,
        )
        self.assertEqual(tasks[0]["priority"], "Høj")
        self.assertEqual(
            tasks[0]["description"],
            "Både SEO-trafik og samlet trafik er faldet.",
        )
        self.assertEqual(tasks[0]["search_console_change"], "placering +1,5")

    def test_positive_or_missing_data_creates_no_combined_task(self) -> None:
        self.assertEqual(build_combined_traffic_tasks(
            seo_sites=[{
                "website": "positive.dk",
                "click_change": 5,
                "position_change": -1,
            }],
            plausible_rows=plausible_rows("positive.dk"),
            today=TODAY,
        ), [])
        self.assertEqual(build_combined_traffic_tasks(
            seo_sites=[{
                "website": "missing.dk",
                "click_change": -20,
                "position_change": 1,
            }],
            plausible_rows=plausible_rows("missing.dk", complete=False),
            today=TODAY,
        ), [])

    def test_current_task_renders_combined_signal_before_ai_preparation(self) -> None:
        page = (
            Path(__file__).resolve().parents[1]
            / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
        ).read_text(encoding="utf-8")
        # The income-first work queue is the single primary source; the freshness
        # fallback only runs after it, and the retired traffic selection is gone.
        queue_select = page.index(
            "prepared = preparation.prepare_next(website_id)"
        )
        freshness_fallback = page.index("build_freshness_recommendations(")
        self.assertLess(queue_select, freshness_fallback)
        self.assertIn(
            "_render_recommendation(database, queue, current)", page
        )


if __name__ == "__main__":
    unittest.main()
