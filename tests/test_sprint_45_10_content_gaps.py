"""Regression tests for evidence-based content gaps and new content ideas."""

import json
import importlib.util
import unittest
from pathlib import Path

from core.task_deliverables import (
    _prompt,
    format_deliverable,
    validate_content_novelty,
    validate_task_deliverable,
)
from core.traffic_recommendations import build_traffic_recommendations


ROOT = Path(__file__).resolve().parents[1]
DAILY_WORK = ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"


def load_daily_work():
    spec = importlib.util.spec_from_file_location(
        "daily_work_45_10", DAILY_WORK
    )
    page = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(page)
    return page


def payload(opportunity_type="new_article", **changes):
    value = {
        "deliverable_type": "content_update",
        "summary": "Nyt indhold til et dokumenteret spørgsmål.",
        "recommended_option": "Erstattes af den færdige tekst.",
        "content_location": "Ny selvstændig side.",
        "current_content": "Ny sektion – ingen eksisterende tekst",
        "replacement_content": (
            "En delt familiekalender gør det muligt at samle aftaler ét sted. "
            "På iPhone kan familien inviteres direkte fra Kalender-appen, "
            "hvorefter alle deltagere kan følge de aftaler, der deles."
        ),
        "search_intent": "Brugeren ønsker en praktisk trin-for-trin-guide.",
        "content_opportunity_type": opportunity_type,
        "missing_topic": "Fælles familiekalender på iPhone",
        "evidence_queries": [
            "fælles familiekalender iphone",
            "del kalender med familie",
        ],
        "duplication_check": (
            "De eksisterende sider forklarer kalenderdeling generelt, men "
            "ingen dækker familiens fælles arbejdsgang som selvstændigt emne."
        ),
        "proposed_title": "Fælles familiekalender på iPhone | Kom godt i gang",
        "proposed_slug": "/faelles-familiekalender-iphone/",
        "outline": [
            "Hvad en fælles familiekalender er",
            "Sådan inviterer du familien",
            "Rettigheder og typiske problemer",
        ],
        "alternatives": ["Udbyg eksisterende guide.", "Lav et blogindlæg."],
        "rationale": "To Search Console-søgninger viser samme manglende behov.",
        "implementation_steps": ["Opret kladden.", "Indsæt teksten."],
        "validation_checks": ["Kontrollér at emnet ikke overlapper."],
    }
    value.update(changes)
    return value


class ContentGapTests(unittest.TestCase):
    def test_rejects_text_already_present_in_current_article(self) -> None:
        value = payload()

        with self.assertRaisesRegex(ValueError, "allerede"):
            validate_content_novelty(value, public_context=[{
                "relation": "berørt side",
                "content_sections": [{
                    "element": "p",
                    "text": value["replacement_content"],
                }],
            }])

    def test_rejects_text_duplicated_on_another_page(self) -> None:
        value = payload()

        with self.assertRaisesRegex(ValueError, "allerede"):
            validate_content_novelty(value, public_context=[{
                "relation": "mulig relateret side",
                "url": "https://site.dk/anden-side/",
                "excerpt": value["replacement_content"],
            }])

    def test_rejects_copy_without_documented_topic(self) -> None:
        value = payload(replacement_content=(
            "En løbejakke beskytter mod vind og regn under træningen. "
            "Vælg en model med ventilation, reflekser og god bevægelsesfrihed."
        ))

        with self.assertRaisesRegex(ValueError, "søgeintentionen"):
            validate_content_novelty(value, public_context=[])

    def test_accepts_new_relevant_copy(self) -> None:
        value = payload()

        validate_content_novelty(value, public_context=[{
            "relation": "berørt side",
            "content_sections": [{
                "element": "p",
                "text": "Kalenderen kan deles med andre personer.",
            }],
        }])

    def test_new_article_requires_complete_brief_and_finished_copy(self) -> None:
        result = validate_task_deliverable(json.dumps(
            payload(), ensure_ascii=False
        ))

        self.assertEqual("new_article", result["content_opportunity_type"])
        self.assertEqual(3, len(result["outline"]))
        self.assertEqual(
            result["replacement_content"], result["recommended_option"]
        )

    def test_all_requested_content_idea_types_are_supported(self) -> None:
        for opportunity_type in (
            "existing_section", "new_category",
            "new_article", "new_blog_post",
        ):
            value = payload(opportunity_type)
            if opportunity_type == "existing_section":
                value.update({
                    "proposed_title": "", "proposed_slug": "", "outline": [],
                    "content_location": "Under H2 om familiedeling.",
                    "current_content": "Den eksisterende passage.",
                })
            result = validate_task_deliverable(json.dumps(
                value, ensure_ascii=False
            ))
            self.assertEqual(
                opportunity_type, result["content_opportunity_type"]
            )

    def test_new_content_rejects_missing_title_slug_or_outline(self) -> None:
        invalid = (
            {"proposed_title": ""},
            {"proposed_slug": ""},
            {"outline": ["Kun ét punkt"]},
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_task_deliverable(json.dumps(
                    payload(**changes), ensure_ascii=False
                ))

    def test_content_gap_requires_search_console_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "Search Console"):
            validate_task_deliverable(json.dumps(
                payload(evidence_queries=[]), ensure_ascii=False
            ))

    def test_prompt_requires_gap_analysis_and_cannibalization_check(self) -> None:
        prompt = _prompt(
            {
                "website": "site.dk",
                "target_url": "https://site.dk/kalender/",
                "target_query": "familiekalender",
                "search_queries": [
                    {"query": "familiekalender iphone", "click_loss": 8}
                ],
                "measured_cause": "Placeringsfald",
            },
            [{
                "relation": "berørt side",
                "content_sections": [{"element": "h2", "text": "Kalender"}],
            }],
        )

        self.assertIn("new_category", prompt)
        self.assertIn("new_article", prompt)
        self.assertIn("new_blog_post", prompt)
        self.assertIn("søgeordskannibalisering", prompt)
        self.assertIn('"evidence_queries"', prompt)
        self.assertIn("search_queries", prompt)

    def test_search_console_queries_flow_into_recommendation(self) -> None:
        search = {
            "website_id": "site.dk",
            "status": "ready",
            "previous_clicks": 100,
            "current_clicks": 60,
            "loss_pages": [{
                "page_url": "https://site.dk/kalender/",
                "cause": "Placeringsfald",
                "previous_ctr": .05,
                "current_ctr": .04,
                "previous_position": 5,
                "current_position": 8,
                "queries": [
                    {"query": "familiekalender iphone", "click_loss": 8},
                    {"query": "del kalender familie", "click_loss": 5},
                ],
            }],
        }
        plausible = {
            "website_id": "site.dk",
            "status": "significant_decline",
            "previous_visitors": 1000,
            "current_visitors": 700,
            "visitor_change_percent": -30,
        }

        result = build_traffic_recommendations([search], [plausible])[0]

        self.assertEqual(
            "familiekalender iphone",
            result["search_queries"][0]["query"],
        )
        self.assertEqual(8, result["search_queries"][0]["click_loss"])

    def test_workflow_persists_search_query_evidence(self) -> None:
        source = (
            ROOT / "core" / "traffic_recommendation_workflow.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"search_queries",', source)

    def test_serialization_persists_content_brief(self) -> None:
        description = format_deliverable(payload())

        self.assertIn("Indholdstype:\nnew_article", description)
        self.assertIn("Manglende emne:", description)
        self.assertIn("Search Console-evidens:", description)
        self.assertIn("Dubletkontrol:", description)
        self.assertIn("Foreslået titel:", description)
        self.assertIn("Foreslået URL:", description)
        self.assertIn("Disposition:", description)

        parsed = load_daily_work()._parse_approved_deliverable({
            "description": description
        })
        self.assertEqual("new_article", parsed["content_opportunity_type"])
        self.assertEqual(
            payload()["proposed_title"], parsed["proposed_title"]
        )
        self.assertEqual(payload()["outline"], parsed["outline"])

    def test_daily_work_exposes_ideas_and_finished_sections(self) -> None:
        source = DAILY_WORK.read_text(encoding="utf-8")

        self.assertIn("Ny kategoritekst", source)
        self.assertIn("Ny artikel", source)
        self.assertIn("Nyt blogindlæg", source)
        self.assertIn("Manglende emne", source)
        self.assertIn("**Dubletkontrol:**", source)
        self.assertIn('st.write("**Disposition**")', source)


if __name__ == "__main__":
    unittest.main()
