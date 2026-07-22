"""Tests for the central AI Analyst agent."""

import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agents.ai_analyst import AIAnalyst
from agents.project_manager import ProjectManager
from agents.website_intelligence import WebsiteIntelligenceAgent
from core.ai_service import AIResponse, AIService
from core.database import Database
from core.knowledge_engine import KnowledgeEngine
from core.seo_history import SEOHistory
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry


VALID_REPORT = {
    "summary": "Trafikken bør undersøges.",
    "problem": "Klik er faldet.",
    "root_cause": "Placeringen er svækket.",
    "recommended_action": "Undersøg de vigtigste landingssider.",
    "priority": "high",
    "confidence": 84,
    "expected_effect": "Et dokumenteret recovery-grundlag.",
    "reasoning": ["Klik og placering bevæger sig negativt."],
    "required_agents": ["SEO Manager"],
    "suggested_tasks": ["Sammenlign de ti vigtigste sider."],
}


class AIAnalystTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.database_path = root / "office.sqlite3"
        self.database = Database(self.database_path)
        self.database.initialize()
        self.registry = WebsiteRegistry(self.database)
        self.task_engine = TaskEngine(self.database)
        self.project_manager = ProjectManager(
            self.task_engine,
            self.registry,
            self.database,
        )
        self.knowledge = KnowledgeEngine(
            Path(__file__).resolve().parents[1] / "knowledge"
        )
        self.knowledge.initialize()
        self.website_intelligence = WebsiteIntelligenceAgent(
            self.database,
            self.registry,
        )
        self._add_website()
        self.website_intelligence.analyze_site("example.dk")
        self.ai_service = Mock(spec=AIService)
        self.analyst = AIAnalyst(
            ai_service=self.ai_service,
            database=self.database,
            knowledge_engine=self.knowledge,
            website_intelligence=self.website_intelligence,
            seo_history=SEOHistory(self.database),
            project_manager=self.project_manager,
            task_engine=self.task_engine,
        )

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def _add_website(self) -> None:
        self.database.upsert_website(
            {
                "website": "example.dk",
                "display_name": "Example",
                "active": True,
                "monetized": True,
                "priority": "high",
                "primary_income_source": "affiliate",
                "niche": "fitness",
                "domain_age": "2",
                "notes": "Kontakt owner@example.dk på 12345678. sk-secret123",
                "status": "active",
            }
        )

    @staticmethod
    def _response(text: str, tokens: int = 10) -> AIResponse:
        return AIResponse(
            text=text,
            model="test-model",
            prompt_tokens=tokens,
            completion_tokens=5,
            latency_ms=20,
        )

    def test_valid_json_is_saved_and_routed_for_seo_review(self) -> None:
        self.ai_service.generate_response.return_value = self._response(
            json.dumps(VALID_REPORT, ensure_ascii=False)
        )

        result = self.analyst.analyze_site("example.dk")

        self.assertEqual(result["confidence"], 84)
        self.assertEqual(result["disposition"], "seo_manager_review")
        saved = self.database.get_latest_analysis(website_id="example.dk")
        self.assertEqual(saved["summary"], VALID_REPORT["summary"])
        self.assertEqual(saved["reasoning"], VALID_REPORT["reasoning"])
        self.assertEqual(self.database.get_ai_analysis_status()["total"], 1)

    def test_invalid_json_retries_once_and_sums_usage(self) -> None:
        self.ai_service.generate_response.side_effect = [
            self._response("ikke json", 11),
            self._response(json.dumps(VALID_REPORT), 13),
        ]

        result = self.analyst.analyze_site("example.dk")

        self.assertEqual(self.ai_service.generate_response.call_count, 2)
        self.assertEqual(result["prompt_tokens"], 24)
        retry_prompt = self.ai_service.generate_response.call_args_list[1].args[0]
        self.assertIn("forrige svar var ugyldigt", retry_prompt)

    def test_two_invalid_answers_are_saved_as_error(self) -> None:
        self.ai_service.generate_response.side_effect = [
            self._response("{"),
            self._response('{"summary": "mangler felter"}'),
        ]

        result = self.analyst.analyze_site("example.dk")

        self.assertEqual(result["analysis_type"], "website_error")
        self.assertEqual(result["confidence"], 0)
        self.assertEqual(result["disposition"], "suggestion_only")
        self.assertEqual(
            self.database.get_latest_analysis()["analysis_type"],
            "website_error",
        )

    def test_project_and_task_analysis_use_read_only_context(self) -> None:
        project_id = self.task_engine.create_project(
            "example.dk",
            "Analyseprojekt",
            "Kun analyse",
            status="ready",
        )
        subproject_id = self.task_engine.create_subproject(
            project_id,
            "Analyse",
            "Analyse",
            1,
            status="ready",
        )
        task_id = self.task_engine.create_task(
            subproject_id,
            "example.dk",
            "Undersøg data",
            "Kun analyse",
            "Behov",
            "AI Analyst",
            30,
            "Bedre beslutning",
            50,
        )
        self.ai_service.generate_response.return_value = self._response(
            json.dumps(VALID_REPORT)
        )

        project = self.analyst.analyze_project(project_id)
        task = self.analyst.analyze_task(task_id)

        self.assertEqual(project["project_id"], project_id)
        self.assertEqual(task["task_id"], task_id)
        self.assertEqual(self.database.get_active_project_count(), 1)
        self.assertEqual(self.database.get_open_task_count(), 1)

    def test_prompt_contains_required_knowledge_and_no_secrets_or_pii(self) -> None:
        context = self.analyst._website_context("example.dk")
        fake_key = "sk-" + "topsecret999"
        context["credential"] = fake_key
        context["contact"] = "person@example.dk +45 12345678"

        prompt = self.analyst.generate_prompt("website", context)

        self.assertIn("company_playbook", prompt)
        self.assertIn("seo_rules", prompt)
        self.assertIn("tone_of_voice", prompt)
        self.assertIn("affiliate_rules", prompt)
        self.assertNotIn(fake_key, prompt)
        self.assertNotIn("person@example.dk", prompt)
        self.assertNotIn("12345678", prompt)
        self.assertNotIn("ordrenr", prompt.lower())

    def test_agent_has_no_operational_write_calls(self) -> None:
        source = inspect.getsource(AIAnalyst).lower()
        for forbidden in (
            "create_project(",
            "create_task(",
            "update_project(",
            "start_task(",
            "complete_task(",
            "wordpress",
            "telegram",
        ):
            self.assertNotIn(forbidden, source)


class AIAnalystDashboardTestCase(unittest.TestCase):
    def test_dashboard_page_shows_saved_analysis(self) -> None:
        try:
            from streamlit.testing.v1 import AppTest
        except ModuleNotFoundError:
            self.skipTest("Streamlit installeres fra requirements.txt.")
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "dashboard.sqlite3"
            database = Database(path)
            database.initialize()
            database.save_ai_analysis(
                {
                    **VALID_REPORT,
                    "website_id": None,
                    "project_id": None,
                    "task_id": None,
                    "analysis_type": "daily",
                    "model": "test-model",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "latency_ms": 25,
                }
            )
            database.close()
            previous = os.environ.get("SU_MEDIA_DATABASE_PATH")
            os.environ["SU_MEDIA_DATABASE_PATH"] = str(path)
            try:
                app = AppTest.from_file(
                    str(
                        Path(__file__).resolve().parents[1]
                        / "dashboard"
                        / "pages"
                        / "6_AI_Analyst.py"
                    )
                )
                app.run(timeout=15)
            finally:
                if previous is None:
                    os.environ.pop("SU_MEDIA_DATABASE_PATH", None)
                else:
                    os.environ["SU_MEDIA_DATABASE_PATH"] = previous
            self.assertEqual(app.exception, [])
            self.assertTrue(
                any(item.value == "AI Analyst" for item in app.title)
            )


if __name__ == "__main__":
    unittest.main()
