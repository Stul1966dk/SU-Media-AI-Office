"""Regression tests for paste-ready, grounded content updates."""

import json
import unittest
from pathlib import Path

from agents.title_optimizer import _PageParser
from core.task_deliverables import (
    _prompt,
    fallback_task_deliverable,
    format_deliverable,
    validate_task_deliverable,
)


ROOT = Path(__file__).resolve().parents[1]
DAILY_WORK = ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"


def content_payload(**changes):
    value = {
        "deliverable_type": "content_update",
        "summary": "Opdatér afsnittet med et tydeligere svar.",
        "recommended_option": "Denne værdi erstattes af den nye tekst.",
        "content_location": "Under H2 “Del kalenderen med familien”.",
        "current_content": "Du kan dele din kalender med andre.",
        "replacement_content": (
            "Du kan dele kalenderen direkte fra Kalender-appen på din "
            "iPhone. Åbn den ønskede kalender, vælg personerne, og send "
            "invitationen. Modtagerne kan derefter se de aftaler, du deler."
        ),
        "search_intent": (
            "Brugeren vil have en praktisk vejledning til kalenderdeling."
        ),
        "content_opportunity_type": "existing_section",
        "missing_topic": "Del kalender med familien",
        "evidence_queries": ["del kalender iphone"],
        "duplication_check": (
            "Emnet udbygger den eksisterende guide uden en ny URL."
        ),
        "proposed_title": "",
        "proposed_slug": "",
        "outline": [],
        "alternatives": ["Udbyg FAQ-sektionen.", "Tilføj en kort tjekliste."],
        "rationale": "Siden mister placering på vejledningssøgningen.",
        "implementation_steps": ["Find H2-sektionen.", "Erstat afsnittet."],
        "validation_checks": ["Kontrollér trinene på en iPhone."],
    }
    value.update(changes)
    return value


class ContentUpdateDeliverableTests(unittest.TestCase):
    def test_valid_content_update_is_paste_ready(self) -> None:
        result = validate_task_deliverable(
            json.dumps(content_payload(), ensure_ascii=False)
        )

        self.assertEqual(
            result["replacement_content"], result["recommended_option"]
        )
        self.assertIn("Under H2", result["content_location"])

    def test_content_update_requires_every_grounding_field(self) -> None:
        for field in (
            "content_location", "current_content", "replacement_content",
            "search_intent",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_task_deliverable(json.dumps(
                    content_payload(**{field: ""}), ensure_ascii=False
                ))

    def test_content_update_rejects_instruction_to_write_it_yourself(self) -> None:
        with self.assertRaisesRegex(ValueError, "brugeren skrive"):
            validate_task_deliverable(json.dumps(content_payload(
                replacement_content=(
                    "Udarbejd et afsnit med relevant information og sørg "
                    "selv for at beskrive alle de vigtigste trin tydeligt."
                )
            ), ensure_ascii=False))

    def test_prompt_requires_exact_source_and_finished_copy(self) -> None:
        prompt = _prompt(
            {
                "website": "site.dk",
                "target_url": "https://site.dk/guide/",
                "target_query": "del kalender",
                "measured_cause": "Placeringsfald",
            },
            [{
                "relation": "berørt side",
                "content_sections": [
                    {"element": "h2", "text": "Del kalenderen"},
                    {"element": "p", "text": "Nuværende passage."},
                ],
            }],
        )

        self.assertIn("citere den", prompt)
        self.assertIn("nuværende passage", prompt)
        self.assertIn("kopieres direkte", prompt)
        self.assertIn('"content_location"', prompt)
        self.assertIn('"replacement_content"', prompt)
        self.assertIn("content_sections", prompt)

    def test_public_page_parser_preserves_headings_and_paragraphs(self) -> None:
        parser = _PageParser("https://site.dk/")
        parser.feed(
            "<h1>Kalenderdeling</h1><h2>På iPhone</h2>"
            "<p>Åbn Kalender-appen og vælg kalenderen.</p>"
        )

        self.assertEqual(
            [
                {"element": "h1", "text": "Kalenderdeling"},
                {"element": "h2", "text": "På iPhone"},
                {
                    "element": "p",
                    "text": "Åbn Kalender-appen og vælg kalenderen.",
                },
            ],
            parser.sections,
        )

    def test_fallback_uses_the_actual_public_page(self) -> None:
        result = fallback_task_deliverable(
            {
                "website": "site.dk",
                "target_url": "https://site.dk/guide/",
                "target_query": "del kalender",
                "measured_cause": "Placeringsfald",
            },
            public_context=[{
                "relation": "berørt side",
                "h1": "Sådan deler du kalenderen",
                "content_sections": [{
                    "element": "p",
                    "text": "Åbn Kalender-appen på din iPhone.",
                }],
            }],
        )

        self.assertIn("Åbn Kalender-appen", result["current_content"])
        self.assertGreaterEqual(len(result["replacement_content"]), 80)
        self.assertTrue(result["content_location"])

    def test_formatted_delivery_persists_structured_content(self) -> None:
        description = format_deliverable(content_payload())

        self.assertIn("Placering:", description)
        self.assertIn("Nuværende tekst:", description)
        self.assertIn("Ny tekst:", description)
        self.assertIn("Søgeintention:", description)

    def test_daily_work_displays_copyable_content_fields(self) -> None:
        source = DAILY_WORK.read_text(encoding="utf-8")

        self.assertIn("def _render_content_update(", source)
        self.assertIn('st.write("**Placering på siden**")', source)
        self.assertIn('st.write("**Nuværende tekst**")', source)
        self.assertIn('st.write("**Ny færdig tekst**")', source)
        self.assertIn('"Ny færdig tekst",', source)
        self.assertIn("validate_content_change(reviewed)", source)


if __name__ == "__main__":
    unittest.main()
