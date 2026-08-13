"""Tests for the monetization change-suggestion deliverable type."""

import json
import unittest

from core.task_deliverables import (
    fallback_task_deliverable,
    validate_task_deliverable,
    validate_monetization,
    _prompt,
)


def monetization_payload(**changes):
    value = {
        "deliverable_type": "monetization",
        "summary": "Konvertér eksisterende trafik til provision.",
        "recommended_option": (
            "| Model | Nøgleegenskab | Pris |\n|---|---|---|\n"
            "| Concept2 RowErg | Luftmodstand | Se aktuel pris |\n"
            "| WaterRower A1 | Vandmodstand | Se aktuel pris |\n"
            "Indsæt affiliatelink i pris-kolonnen fra forhandlerens feed."
        ),
        "content_location": "Under introduktionen, før de enkelte anmeldelser.",
        "current_state": "Prosa-anmeldelse af flere romaskiner uden links.",
        "opportunity_type": "comparison_table",
        "evidence": "Siden får 540 klik pr. måned, men 0 kr. i provision.",
        "rationale": "En sammenligningstabel konverterer købsintention direkte.",
        "alternatives": [
            "Tilføj en tydelig “Se aktuel pris”-knap øverst.",
            "Indsæt en fremhævet produktboks til det primære produkt.",
        ],
        "implementation_steps": [
            "Find de produkter siden allerede omtaler.",
            "Indsæt tabellen og affiliatelinks fra feedet.",
        ],
        "validation_checks": ["Alle links peger på omtalte produkter."],
    }
    value.update(changes)
    return value


class MonetizationDeliverableTests(unittest.TestCase):
    def test_valid_monetization_is_accepted(self) -> None:
        result = validate_task_deliverable(
            json.dumps(monetization_payload(), ensure_ascii=False)
        )
        self.assertEqual("monetization", result["deliverable_type"])
        self.assertEqual("comparison_table", result["opportunity_type"])

    def test_every_grounding_field_is_required(self) -> None:
        for field in (
            "content_location", "current_state", "opportunity_type", "evidence",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_task_deliverable(json.dumps(
                    monetization_payload(**{field: ""}), ensure_ascii=False
                ))

    def test_unknown_opportunity_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "ukendt mulighedstype"):
            validate_task_deliverable(json.dumps(
                monetization_payload(opportunity_type="magic"),
                ensure_ascii=False,
            ))

    def test_placeholder_option_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "udfylde det selv"):
            validate_task_deliverable(json.dumps(
                monetization_payload(
                    recommended_option=(
                        "Lav en flot sammenligningstabel og udfyld selv "
                        "kolonnerne med de rigtige produkter og priser."
                    )
                ),
                ensure_ascii=False,
            ))

    def test_too_short_option_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "for kort"):
            validate_task_deliverable(json.dumps(
                monetization_payload(recommended_option="Sæt et link ind."),
                ensure_ascii=False,
            ))

    def test_prompt_carries_monetization_schema_and_rules(self) -> None:
        prompt = _prompt(
            {
                "website": "romaskinen.dk",
                "target_url": "https://romaskinen.dk/vandromaskiner/",
                "target_query": "romaskine vandmodstand",
                "experiment_type": "monetization",
            },
            [{
                "relation": "berørt side",
                "content_sections": [
                    {"element": "h1", "text": "Vandromaskiner"},
                    {"element": "p", "text": "En vandromaskine giver naturtro ro."},
                ],
            }],
        )
        self.assertIn('"opportunity_type"', prompt)
        self.assertIn("comparison_table", prompt)
        self.assertIn("produktfeed", prompt)

    def test_fallback_produces_a_valid_monetization_draft(self) -> None:
        draft = fallback_task_deliverable(
            {
                "experiment_type": "monetization",
                "target_url": "https://romaskinen.dk/vandromaskiner/",
            },
            public_context=[{
                "relation": "berørt side", "h1": "Vandromaskiner",
            }],
        )
        self.assertEqual("monetization", draft["deliverable_type"])
        # The fallback must itself satisfy the validation rules.
        validate_monetization(draft)


if __name__ == "__main__":
    unittest.main()
