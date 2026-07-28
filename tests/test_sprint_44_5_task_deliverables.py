"""Regression tests for concrete AI deliverables before task approval."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.task_deliverables import (
    fallback_task_deliverable,
    format_deliverable,
    generate_task_deliverable,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeAI:
    def __init__(self, deliverable_type: str = "title_meta") -> None:
        self.deliverable_type = deliverable_type

    def generate_response(self, prompt: str) -> SimpleNamespace:
        self.prompt = prompt
        return SimpleNamespace(text=json.dumps({
            "deliverable_type": self.deliverable_type,
            "summary": "Tre færdige forslag.",
            "recommended_option": "Det anbefalede konkrete forslag.",
            "alternatives": ["Forslag A", "Forslag B", "Forslag C"],
            "rationale": "Bygger på det målte signal.",
            "implementation_steps": ["Indsæt manuelt.", "Kontrollér siden."],
            "validation_checks": ["Søgeintentionen er bevaret."],
        }))


class TaskDeliverableTests(unittest.TestCase):
    def test_ai_generates_a_valid_reviewable_deliverable(self):
        ai = FakeAI()
        result = generate_task_deliverable(
            {
                "website": "site.dk",
                "target_url": "https://site.dk/side/",
                "target_query": "test",
                "measured_cause": "CTR-fald",
                "recommended_action": "Forbedr snippet.",
            },
            ai_service=ai,
        )

        self.assertEqual("title_meta", result["deliverable_type"])
        self.assertEqual(3, len(result["alternatives"]))
        self.assertIn("bed aldrig brugeren om selv", ai.prompt)

    def test_rule_fallback_covers_every_supported_work_type(self):
        cases = {
            "CTR-fald": "title_meta",
            "Placeringsfald": "content_update",
            "interne links": "internal_links",
            "teknisk rettelse": "technical_fix",
            "schema markup": "schema",
            "kanalfald": "traffic_analysis",
        }
        for description, expected in cases.items():
            result = fallback_task_deliverable({
                "website": "site.dk",
                "target_url": "https://site.dk/side/",
                "target_query": "søgeord",
                "measured_cause": description,
                "description": description,
            })
            self.assertEqual(expected, result["deliverable_type"])
            self.assertTrue(result["recommended_option"])
            self.assertGreaterEqual(len(result["alternatives"]), 2)

    def test_approved_description_contains_the_actual_output(self):
        deliverable = fallback_task_deliverable({
            "website": "site.dk",
            "target_url": "https://site.dk/side/",
            "target_query": "søgeord",
            "measured_cause": "CTR-fald",
        })

        description = format_deliverable(deliverable)

        self.assertIn("Anbefalet løsning:", description)
        self.assertIn("Leverancetype: title_meta", description)
        self.assertIn("Alternativer:", description)
        self.assertIn("Implementering:", description)
        self.assertIn("Kontrol før godkendelse:", description)

    def test_today_requires_output_before_approval(self):
        source = (
            ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
        ).read_text(encoding="utf-8")
        action_source = source.split(
            "def _render_new_decision_actions(", 1
        )[1].split("def _create_and_approve(", 1)[0]

        self.assertIn("Lav konkret arbejdsudkast", action_source)
        self.assertIn("Konkret arbejdsudkast", action_source)
        self.assertIn("Godkend arbejdsudkast", action_source)
        self.assertNotIn('"Godkend opgave"', action_source)
        self.assertIn("analyze_current_snippet", source)
        self.assertIn('"relation": "berørt side"', source)
        self.assertIn("value=_approved_solution(item)", source)
        self.assertIn("_approved_change_type(item)", source)


if __name__ == "__main__":
    unittest.main()
