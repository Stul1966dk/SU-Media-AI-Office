"""Sprint 44.7 regression tests for approved daily-work instructions."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core.database import Database
from core.task_deliverables import format_deliverable
from core.traffic_recommendation_workflow import (
    TrafficRecommendationWorkflow,
)


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"


def _load_page():
    spec = importlib.util.spec_from_file_location("daily_work_44_7", PAGE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ApprovedInstructionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "office.db"
        self.database = Database(self.database_path)
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
        self.workflow = TrafficRecommendationWorkflow(self.database)

    def tearDown(self) -> None:
        self.database.close()
        self.temporary.cleanup()

    def _approved(self, description: str) -> None:
        decision = self.workflow.create_draft(
            {
                "task_key": "combined|site.dk|page",
                "website": "site.dk",
                "task_type": "combined_traffic_decline",
                "target_url": "https://site.dk/side/",
                "measured_cause": "Placeringsfald",
                "description": "Styrk siden",
                "priority": "Høj",
            },
            title="Styrk siden",
            description=description,
        )
        self.workflow.approve_draft(decision["recommendation_key"])

    def test_parser_restores_every_reviewed_section(self) -> None:
        page = _load_page()
        description = format_deliverable({
            "deliverable_type": "content_update",
            "summary": "Opdatér den vigtigste sektion.",
            "recommended_option": "Indsæt dette konkrete afsnit.",
            "alternatives": ["Alternativ A", "Alternativ B"],
            "rationale": "Placeringen er faldet.",
            "implementation_steps": ["Find sektionen.", "Indsæt afsnittet."],
            "validation_checks": ["Søgeintentionen er bevaret."],
        })

        result = page._parse_approved_deliverable({
            "description": description
        })

        self.assertEqual(
            "Indsæt dette konkrete afsnit.",
            result["recommended_option"],
        )
        self.assertEqual(2, len(result["implementation_steps"]))
        self.assertEqual(
            ["Søgeintentionen er bevaret."],
            result["validation_checks"],
        )

    def test_legacy_approval_requires_repair_before_registration(self) -> None:
        self._approved("Generel gammel beskrivelse uden konkret leverance.")
        with patch.dict(
            os.environ,
            {"SU_MEDIA_DATABASE_PATH": str(self.database_path)},
        ):
            app = AppTest.from_file(str(PAGE)).run(timeout=20)

        self.assertFalse(app.exception)
        labels = [button.label for button in app.button]
        self.assertIn("Lav konkret arbejdsinstruks", labels)
        self.assertNotIn(
            "Registrér ændring og start 28-dages måling",
            labels,
        )

    def test_structured_approval_shows_instruction_before_registration(
        self,
    ) -> None:
        description = format_deliverable({
            "deliverable_type": "content_update",
            "summary": "Opdatér den vigtigste sektion.",
            "recommended_option": "Indsæt dette konkrete afsnit.",
            "alternatives": ["Alternativ A", "Alternativ B"],
            "rationale": "Placeringen er faldet.",
            "implementation_steps": ["Find sektionen.", "Indsæt afsnittet."],
            "validation_checks": ["Søgeintentionen er bevaret."],
        })
        self._approved(description)
        with patch.dict(
            os.environ,
            {"SU_MEDIA_DATABASE_PATH": str(self.database_path)},
        ):
            app = AppTest.from_file(str(PAGE)).run(timeout=20)

        self.assertFalse(app.exception)
        visible = " ".join(
            [item.value for item in app.markdown]
            + [item.value for item in app.success]
        )
        self.assertIn("Godkendt arbejdsinstruks", visible)
        self.assertIn("Indsæt dette konkrete afsnit.", visible)
        self.assertIn("Når du har udført ændringen", visible)
        self.assertEqual(
            "Indsæt dette konkrete afsnit.",
            app.text_area[0].value,
        )

    def test_workflow_can_upgrade_only_an_approved_plan(self) -> None:
        self._approved("Generel gammel beskrivelse.")
        description = format_deliverable({
            "deliverable_type": "content_update",
            "summary": "Konkret plan.",
            "recommended_option": "Indsæt afsnittet.",
            "alternatives": ["A", "B"],
            "rationale": "Data.",
            "implementation_steps": ["Indsæt."],
            "validation_checks": ["Kontrollér."],
        })

        updated = self.workflow.update_approved_plan(
            "combined|site.dk|page", description=description
        )

        self.assertEqual("approved", updated["status"])
        self.assertIn("Anbefalet løsning:", updated["description"])
        self.assertTrue(
            updated["evidence"].get("approved_plan_updated_at")
        )


if __name__ == "__main__":
    unittest.main()
