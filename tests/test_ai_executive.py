"""Tests for safe, evidence-based executive prioritization."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.ai_executive import AIExecutive, BriefingValidationError
from core.executive_intelligence import ExecutiveIntelligence
from core.task_engine import TaskEngine
from agents.project_manager import ProjectManager
from core.ai_service import AIResponse
from core.database import Database
from core.website_registry import WebsiteRegistry


class FakeAI:
    model = "test-model"

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls = 0

    def generate_response(self, prompt: str) -> AIResponse:
        text = self.texts[self.calls]
        self.calls += 1
        return AIResponse(text, self.model, 10, 5, 2)


class Knowledge:
    def get_company_rules(self) -> str:
        return "Målet er målbar, stabil indtjening."


def make_executive(database: Database, ai: FakeAI) -> AIExecutive:
    empty = SimpleNamespace()
    return AIExecutive(
        ai_service=ai, ai_analyst=empty, database=database,
        website_registry=WebsiteRegistry(database), website_intelligence=empty,
        seo_history=empty, seo_manager=empty, project_manager=empty,
        task_engine=empty, knowledge_engine=Knowledge(),
        agent_orchestrator=empty,
    )


class AIExecutiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        for website, status in (
            ("active.dk", "active"), ("old.dk", "phasing_out")
        ):
            self.database.upsert_website({
                "website": website, "display_name": website, "active": True,
                "monetized": True, "priority": "high",
                "primary_income_source": "affiliate", "niche": "test",
                "domain_age": "1", "notes": "", "status": status,
            })

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def test_ignored_site_and_cautious_missing_data(self) -> None:
        agent = make_executive(self.database, FakeAI([]))
        context = agent.collect_company_context()
        self.assertEqual(["active.dk"], [x["website"] for x in context["websites"]])
        ranked = agent.rank_opportunities(context)
        self.assertLess(ranked[0]["priority_score"], 50)
        self.assertEqual("monitor",
                         agent.recommend_next_action(ranked[0])["action_type"])

    def test_dimension_data_creates_concrete_executable_task(self) -> None:
        for dimension_type, page_url, query in (
            ("page", "https://active.dk/guide/", None),
            ("query", None, "bedste guide"),
            ("page_query", "https://active.dk/guide/", "bedste guide"),
        ):
            self.database.upsert_search_console_dimension(
                dimension_type=dimension_type, website_id="active.dk",
                site_url="https://active.dk/", page_url=page_url, query=query,
                period_start="2026-06-21", period_end="2026-07-18",
                clicks=10, impressions=500, ctr=.02, average_position=7.0,
            )
        focus = {
            "website": "active.dk", "evidence": [],
            "recommended_action": "Overvåg udviklingen",
            "priority_score": 80, "confidence": 90,
            "estimated_minutes": 60,
        }
        context = ExecutiveIntelligence(
            self.database
        ).build_website_context("active.dk")
        result = ExecutiveIntelligence(
            self.database
        ).create_actionable_focus_area(focus, context)
        self.assertEqual("https://active.dk/guide/", result["target_url"])
        self.assertEqual("bedste guide", result["target_query"])
        self.assertLessEqual(len(result["exact_steps"]), 5)
        self.assertTrue(result["completion_criteria"])
        self.assertNotIn("importér", result["recommended_action"].lower())

    def test_company_context_can_be_limited_to_one_active_website(self) -> None:
        self.database.upsert_website({
            "website": "second.dk", "display_name": "second.dk",
            "active": True, "monetized": False, "priority": "low",
            "primary_income_source": "", "niche": "test",
            "domain_age": "1", "notes": "", "status": "active",
        })
        context = make_executive(
            self.database, FakeAI([])
        ).collect_company_context(website_id="active.dk")
        self.assertEqual(
            ["active.dk"], [item["website"] for item in context["websites"]]
        )
        self.assertIn("website-niveau", context["scope_limitation"])

    def test_validation_caps_work_and_enforces_confidence(self) -> None:
        focus = {
            "rank": 1, "website": "active.dk", "title": "Analyse",
            "reason": "Data", "evidence": ["SEO 40"], "recommended_action": "Gør",
            "action_type": "perform_task", "project_id": None, "task_id": None,
            "assigned_agent": "SEO Manager", "estimated_minutes": 999,
            "expected_effect": "Flere klik", "priority_score": 80,
            "confidence": 55,
        }
        value = {
            "summary": "S", "company_status": "Forsigtig",
            "focus_areas": [focus], "risks": [], "opportunities": [],
            "total_estimated_minutes": 999, "model": "",
        }
        result = AIExecutive._validate_json(json.dumps(value))
        self.assertEqual(120, result["focus_areas"][0]["estimated_minutes"])
        self.assertEqual("monitor", result["focus_areas"][0]["action_type"])

    def test_validation_accepts_safe_aliases_extra_fields_and_numeric_text(
        self,
    ) -> None:
        value = {
            "summary": "S", "companyStatus": "Stabil",
            "focusAreas": [{
                "website": "active.dk", "title": "Analyse",
                "reason": "Data", "evidence": "SEO 40",
                "recommendedAction": "Undersøg", "actionType": "monitor",
                "priorityScore": "70", "confidence": "65",
                "estimatedMinutes": "45", "harmless_extra": "ignoreres",
            }],
            "risks": "Datamangel", "opportunities": [], "extra": "ok",
        }
        result = AIExecutive._validate_json(json.dumps(value))
        self.assertEqual(70, result["focus_areas"][0]["priority_score"])
        self.assertEqual(["SEO 40"], result["focus_areas"][0]["evidence"])

    def test_safe_aliases_and_noncritical_defaults_are_normalized(self) -> None:
        value = {
            "summary": "S", "company_status": "Delvis",
            "focus_areas": [{
                "website": "active.dk",
                "recommendation": "Importér URL-data for active.dk",
                "reasons": "", "priority": "71", "confidence": "65",
                "actionType": "", "assignedAgent": "SEO Manager",
            }],
            "risks": [], "opportunities": [],
        }
        result = AIExecutive._validate_json(json.dumps(value))
        focus = result["focus_areas"][0]
        self.assertEqual("Prioriteret indsats for active.dk", focus["title"])
        self.assertEqual("monitor", focus["action_type"])
        self.assertEqual([], focus["evidence"])
        self.assertEqual(71, focus["priority_score"])

    def test_missing_critical_focus_fields_are_rejected(self) -> None:
        value = {
            "summary": "S", "company_status": "Delvis",
            "focus_areas": [{"title": "Mangler kritiske data"}],
            "risks": [], "opportunities": [],
        }
        with self.assertRaisesRegex(ValueError, "kritiske felter"):
            AIExecutive._validate_json(json.dumps(value))

    def test_generic_action_is_rejected(self) -> None:
        value = {
            "summary": "S", "company_status": "Delvis",
            "focus_areas": [{
                "website": "active.dk", "title": "SEO",
                "recommended_action": "Undersøg området",
                "priority_score": 70, "confidence": 70,
            }],
            "risks": [], "opportunities": [],
        }
        with self.assertRaisesRegex(ValueError, "generisk"):
            AIExecutive._validate_json(json.dumps(value))

    def test_intelligence_creates_concrete_bounded_data_action(self) -> None:
        intelligence = ExecutiveIntelligence(self.database, "Målbar effekt")
        context = intelligence.build_website_context("active.dk")
        focus = intelligence.create_actionable_focus_area({
            "website": "active.dk", "title": "SEO-fald",
            "recommended_action": "Se nærmere på problemet",
            "priority_score": 75, "confidence": 70,
            "estimated_minutes": 500, "evidence": [],
        }, context)
        self.assertIn("URL- og søgeordsniveau", focus["recommended_action"])
        self.assertLessEqual(focus["estimated_minutes"], 120)
        self.assertTrue(focus["data_sources"])
        self.assertTrue(focus["expected_effect"])
        self.assertTrue(focus["priority_reason"])

    def test_send_to_project_manager_creates_draft_only(self) -> None:
        manager = ProjectManager(
            TaskEngine(self.database), WebsiteRegistry(self.database),
            self.database,
        )
        project_id = manager.create_draft_from_focus({
            "website": "active.dk", "title": "Konkret SEO-analyse",
            "recommended_action": "Importer URL-data",
            "measurement_method": "Antal URL'er",
            "priority_label": "Høj", "expected_effect": "Mellem",
        })
        project = self.database.get_project_record(project_id)
        self.assertEqual("draft", project["status"])

    def test_previous_briefing_survives_new_invalid_model_response(self) -> None:
        valid = json.dumps({
            "summary": "S", "company_status": "Stabil", "focus_areas": [],
            "risks": [], "opportunities": [], "total_estimated_minutes": 0,
            "model": "",
        })
        agent = make_executive(
            self.database, FakeAI([valid, "bad", "still bad"])
        )
        agent.generate_daily_briefing()
        with self.assertRaises(BriefingValidationError):
            agent.generate_daily_briefing()
        self.assertEqual("S", agent.get_latest_briefing()["summary"])

    def test_invalid_json_is_retried_and_daily_save_is_idempotent(self) -> None:
        valid = json.dumps({
            "summary": "S", "company_status": "Forsigtig",
            "focus_areas": [], "risks": [], "opportunities": [],
            "total_estimated_minutes": 0, "model": "",
        })
        ai = FakeAI(["not json", valid, valid])
        agent = make_executive(self.database, ai)
        agent.generate_daily_briefing()
        agent.generate_daily_briefing()
        self.assertEqual(3, ai.calls)
        self.assertEqual(1, len(self.database.get_executive_briefing_history()))

    def test_analysis_has_no_operational_side_effects(self) -> None:
        agent = make_executive(self.database, FakeAI([]))
        before = self.database.get_executive_context()["counts"]
        agent.rank_opportunities(agent.collect_company_context())
        self.assertEqual(before, self.database.get_executive_context()["counts"])


if __name__ == "__main__":
    unittest.main()
