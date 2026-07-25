"""Sprint 41.4 checks for the dashboard action list."""

import unittest
from pathlib import Path

from dashboard.components.data import build_dashboard_priority_tasks


class DashboardPriorityTaskTests(unittest.TestCase):
    def test_tasks_are_sorted_and_limited_to_five(self) -> None:
        tasks = build_dashboard_priority_tasks(
            system_status={
                "openai": {"is_ok": False},
                "database": {"is_ok": True},
            },
            seo_sites=[
                {"website": "critical.dk", "trend": "critical"},
                {"website": "declining.dk", "trend": "declining"},
            ],
            project_tasks=[{
                "task": "Behandl title-forslag",
                "website": "title.dk",
                "priority_score": 75,
            }],
            experiments=[{"website": "experiment.dk"}],
            coverage=[{
                "website": "missing.dk",
                "latest_search_console": None,
                "latest_plausible": None,
            }],
        )

        self.assertEqual(len(tasks), 5)
        self.assertEqual(tasks[0]["priority"], "Kritisk")
        self.assertEqual(tasks[0]["target"], "pages/12_Systemstatus.py")
        self.assertEqual(tasks[1]["website"], "critical.dk")
        self.assertEqual(tasks[2]["target"], "pages/13_Eksperimenter.py")
        self.assertEqual(tasks[3]["website"], "declining.dk")
        self.assertEqual(tasks[4]["description"], "Search Console-data mangler.")

    def test_empty_state_has_no_tasks(self) -> None:
        self.assertEqual(
            build_dashboard_priority_tasks(
                system_status={},
                seo_sites=[],
                project_tasks=[],
                experiments=[],
                coverage=[],
            ),
            [],
        )

    def test_priority_list_is_independent_of_seo_table_filter(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "dashboard" / "components" / "data.py"
        ).read_text(encoding="utf-8")
        self.assertIn('seo_sites=action_context["seo_health"]', source)

    def test_dashboard_has_no_seo_recovery_section(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('st.subheader("SEO Recovery")', source)
        self.assertNotIn("def _render_recovery(", source)
        self.assertIn("Ingen højprioriterede opgaver fundet.", source)


if __name__ == "__main__":
    unittest.main()
