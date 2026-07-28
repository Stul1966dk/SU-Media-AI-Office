"""Regression checks for Streamlit instances created before Sprint 43.4."""

import unittest
from pathlib import Path
from unittest.mock import Mock

from dashboard.components.data import load_dashboard_data
from dashboard.app import _apply_hot_reload_compatibility


class HotReloadCompatibilityTests(unittest.TestCase):
    def test_seo_page_is_read_only_and_points_to_today(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "dashboard"
            / "pages"
            / "9_SEO.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "get_decision(database, traffic_recommendation[\"task_key\"])",
            source,
        )
        self.assertIn("render_next_step(", source)
        self.assertIn('path="app.py"', source)
        self.assertNotIn("Gem opgavekladde", source)
        self.assertNotIn("Godkend opgavekladde", source)

    def test_dashboard_entrypoint_shims_old_database_instance(self):
        class OldDatabase:
            pass

        database = OldDatabase()
        _apply_hot_reload_compatibility(database)

        self.assertEqual([], database.get_traffic_recommendation_decisions())

    def test_dashboard_accepts_database_without_decision_methods(self):
        database = Mock(
            spec=[
                "get_dashboard_system_health",
                "get_latest_seo_health_sites",
                "get_priority_tasks",
                "get_dashboard_action_context",
                "get_priority_task_scores",
                "get_dashboard_overview",
                "get_dashboard_economy",
                "get_seo_health_summary",
                "get_recent_sales",
                "get_recent_events",
                "get_ai_analysis_status",
            ]
        )
        database.get_dashboard_system_health.return_value = {}
        database.get_latest_seo_health_sites.return_value = []
        database.get_priority_tasks.return_value = []
        database.get_dashboard_action_context.return_value = {
            "experiments": [],
            "active_experiments": [],
            "coverage": [],
            "seo_health": [],
            "plausible_daily": [],
        }
        database.get_priority_task_scores.return_value = []
        database.get_dashboard_overview.return_value = {}
        database.get_dashboard_economy.return_value = {}
        database.get_seo_health_summary.return_value = {}
        database.get_recent_sales.return_value = []
        database.get_recent_events.return_value = []
        database.get_ai_analysis_status.return_value = {}

        result = load_dashboard_data(database)

        self.assertEqual([], result.priority_tasks)


if __name__ == "__main__":
    unittest.main()
