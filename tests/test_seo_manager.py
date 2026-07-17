"""Integration tests for the SEO Manager specialist agent."""

import inspect
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from agents.decision_engine import DecisionEngine
from agents.project_manager import ProjectManager
from agents.seo_manager import RECOVERY_SUBPROJECTS, SEOManager
from core.agent_orchestrator import AgentOrchestrator
from core.database import Database
from core.dashboard import Dashboard
from core.knowledge_engine import KnowledgeEngine
from core.seo_history import SEOHistory
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry


class SEOManagerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.database = Database(root / "office.sqlite3")
        self.database.initialize()
        self.registry = WebsiteRegistry(self.database)
        self.task_engine = TaskEngine(self.database)
        self.project_manager = ProjectManager(
            self.task_engine,
            self.registry,
            self.database,
        )
        self.knowledge = KnowledgeEngine(root / "knowledge")
        self.knowledge.initialize()
        self.decision_engine = DecisionEngine(
            self.registry,
            self.database,
            self.project_manager,
        )
        self.orchestrator = AgentOrchestrator(
            decision_engine=self.decision_engine,
            project_manager=self.project_manager,
            task_engine=self.task_engine,
            knowledge_engine=self.knowledge,
            database=self.database,
            website_registry=self.registry,
        )
        self.orchestrator.initialize()
        self.manager = SEOManager(
            database=self.database,
            seo_history=SEOHistory(self.database),
            website_registry=self.registry,
            project_manager=self.project_manager,
            task_engine=self.task_engine,
            knowledge_engine=self.knowledge,
            agent_orchestrator=self.orchestrator,
        )
        self.analysis_date = date(2026, 7, 17)

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def add_website(self, website: str, status: str = "active") -> None:
        self.database.upsert_website(
            {
                "website": website,
                "display_name": website,
                "active": status == "active",
                "monetized": True,
                "priority": "high",
                "primary_income_source": "affiliate",
                "niche": "test",
                "domain_age": "1",
                "notes": "",
                "status": status,
            }
        )

    def add_health_data(self, website: str, critical: bool) -> None:
        for offset in range(1, 57):
            current = offset <= 28
            clicks = 5 if critical and current else 20
            position = 10.0 if critical and current else 5.0
            self.database.upsert_search_console_daily_metric(
                website_id=website,
                site_url=f"sc-domain:{website}",
                metric_date=(
                    self.analysis_date - timedelta(days=offset)
                ).isoformat(),
                clicks=clicks,
                impressions=100,
                ctr=clicks / 100,
                average_position=position,
            )

    def test_stable_website_creates_no_project(self) -> None:
        self.add_website("stable.dk")
        self.add_health_data("stable.dk", critical=False)
        result = self.manager.analyze_site(
            "stable.dk",
            analysis_date=self.analysis_date,
        )
        self.assertEqual(result.action, "no_action")
        self.assertIsNone(
            self.database.get_project_by_website_and_title(
                "stable.dk",
                "SEO Recovery – stable.dk",
            )
        )

    def test_critical_website_creates_complete_recovery_plan_and_event(
        self,
    ) -> None:
        self.add_website("critical.dk")
        self.add_health_data("critical.dk", critical=True)
        before = self.database.get_website("critical.dk")
        result = self.manager.analyze_site(
            "critical.dk",
            analysis_date=self.analysis_date,
        )

        self.assertEqual(result.action, "created")
        self.assertEqual(
            [
                item["title"]
                for item in self.database.get_subprojects_for_project(
                    result.project_id
                )
            ],
            list(RECOVERY_SUBPROJECTS),
        )
        tasks = self.task_engine.get_tasks_for_project(result.project_id)
        self.assertEqual(len(tasks), 5)
        self.assertTrue(
            all(1 <= task["estimated_minutes"] <= 120 for task in tasks)
        )
        self.assertTrue(all(task["measurement_method"] for task in tasks))
        self.assertEqual(
            {task["assigned_agent"] for task in tasks},
            {"SEO Manager", "Webmaster", "Content Manager"},
        )
        dependency_order = sorted(tasks, key=lambda task: task["id"])
        self.assertIsNone(dependency_order[0]["depends_on_task_id"])
        for previous, current in zip(
            dependency_order,
            dependency_order[1:],
        ):
            self.assertEqual(current["depends_on_task_id"], previous["id"])

        events = self.database.get_event_records(status="pending")
        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0]["event_type"],
            "seo_recovery_project_created",
        )
        self.assertEqual(events[0]["source"], "SEO Manager")
        self.assertEqual(before, self.database.get_website("critical.dk"))

    def test_existing_project_is_updated_without_duplicates(self) -> None:
        self.add_website("repeat.dk")
        self.add_health_data("repeat.dk", critical=True)
        first = self.manager.analyze_site(
            "repeat.dk",
            analysis_date=self.analysis_date,
        )
        second = self.manager.analyze_site(
            "repeat.dk",
            analysis_date=self.analysis_date,
        )
        self.assertEqual(first.project_id, second.project_id)
        self.assertEqual(second.action, "updated")
        projects = [
            project
            for project in (
                self.database.get_project_by_website_and_title(
                    "repeat.dk",
                    "SEO Recovery – repeat.dk",
                ),
            )
            if project
        ]
        self.assertEqual(len(projects), 1)
        self.assertEqual(
            len(self.task_engine.get_tasks_for_project(first.project_id)),
            5,
        )
        self.assertEqual(len(self.database.get_event_records()), 1)
        recommendations = self.manager.get_recommendations("repeat.dk")
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["status"], "project_updated")

    def test_phasing_out_website_is_ignored(self) -> None:
        self.add_website("ignored.dk", status="phasing_out")
        result = self.manager.analyze_site(
            "ignored.dk",
            analysis_date=self.analysis_date,
        )
        self.assertEqual(result.action, "ignored")
        self.assertEqual(self.database.get_seo_recommendations("ignored.dk"), [])

    def test_analyze_all_sites_and_dashboard_summary(self) -> None:
        self.add_website("stable.dk")
        self.add_health_data("stable.dk", critical=False)
        self.add_website("critical.dk")
        self.add_health_data("critical.dk", critical=True)
        result = self.manager.analyze_all_sites(self.analysis_date)
        self.assertEqual(result.websites_analyzed, 2)
        self.assertEqual(result.new_projects, 1)
        self.assertEqual(result.updated_projects, 0)
        self.assertEqual(result.no_action, 1)
        self.assertEqual(
            result.highest_priority["website_id"],
            "critical.dk",
        )
        output = Dashboard(self.database).render(
            None,
            seo_manager_status={
                "websites_analyzed": result.websites_analyzed,
                "new_projects": result.new_projects,
                "updated_projects": result.updated_projects,
                "no_action": result.no_action,
                "highest_priority": result.highest_priority,
            },
        )
        self.assertIn("SEO Manager", output)
        self.assertIn("Websites analyseret          2", output)
        self.assertIn("Nye recovery-projekter       1", output)
        self.assertIn("critical.dk", output)

    def test_agent_has_no_telegram_secret_or_website_write_path(self) -> None:
        source = inspect.getsource(SEOManager)
        self.assertNotIn("Telegram", source)
        self.assertNotIn("token", source.lower())
        self.assertNotIn("credential", source.lower())
        self.assertNotIn("upsert_website", source)


if __name__ == "__main__":
    unittest.main()
