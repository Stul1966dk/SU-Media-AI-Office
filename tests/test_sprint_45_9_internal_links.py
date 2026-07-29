"""Regression tests for concrete, verifiable internal-link tasks."""

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.task_deliverables import (
    _prompt,
    fallback_task_deliverable,
    format_deliverable,
    generate_task_deliverable,
    validate_task_deliverable,
)


ROOT = Path(__file__).resolve().parents[1]
DAILY_WORK = ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
SOURCE = "https://site.dk/relateret-guide/"
TARGET = "https://site.dk/maal-side/"


def link_payload(**changes):
    value = {
        "deliverable_type": "internal_links",
        "summary": "Tilføj ét relevant internt link.",
        "recommended_option": "Erstattes af den færdige passage.",
        "source_url": SOURCE,
        "destination_url": TARGET,
        "anchor_text": "guide til kalenderdeling",
        "link_location": "Under H2 “Del kalenderen med familien”.",
        "current_sentence": (
            "Du kan invitere familien til en delt kalender fra din iPhone."
        ),
        "linked_sentence": (
            "Du kan invitere familien fra din iPhone – se vores guide til "
            "kalenderdeling for alle trin."
        ),
        "alternatives": ["Brug en kortere ankertekst.", "Placér linket i FAQ."],
        "rationale": "Kildesiden er emnemæssigt relevant for målsiden.",
        "implementation_steps": ["Åbn kildesiden.", "Indsæt linksætningen."],
        "validation_checks": ["Kontrollér at linket peger på målsiden."],
    }
    value.update(changes)
    return value


class FakeAI:
    def generate_response(self, prompt: str) -> SimpleNamespace:
        self.prompt = prompt
        return SimpleNamespace(
            text=json.dumps(link_payload(), ensure_ascii=False)
        )


def load_daily_work():
    spec = importlib.util.spec_from_file_location("daily_work_45_9", DAILY_WORK)
    page = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(page)
    return page


class InternalLinkDeliverableTests(unittest.TestCase):
    def test_ai_uses_documented_source_and_target(self) -> None:
        ai = FakeAI()
        result = generate_task_deliverable(
            {
                "website": "site.dk",
                "target_url": TARGET,
                "target_query": "kalenderdeling",
                "experiment_type": "internal_links",
            },
            ai_service=ai,
            public_context=[{
                "relation": "mulig relateret side",
                "url": SOURCE,
                "excerpt": "Du kan invitere familien.",
            }],
        )

        self.assertEqual(SOURCE, result["source_url"])
        self.assertEqual(TARGET, result["destination_url"])
        self.assertEqual(
            result["linked_sentence"], result["recommended_option"]
        )

    def test_rejects_source_not_found_in_public_candidates(self) -> None:
        with self.assertRaisesRegex(ValueError, "dokumenterede relaterede"):
            validate_task_deliverable(
                json.dumps(link_payload(), ensure_ascii=False),
                expected_target_url=TARGET,
                allowed_source_urls=["https://site.dk/anden-side/"],
            )

    def test_rejects_wrong_destination(self) -> None:
        with self.assertRaisesRegex(ValueError, "målside"):
            validate_task_deliverable(
                json.dumps(link_payload(
                    destination_url="https://site.dk/forkert/"
                ), ensure_ascii=False),
                expected_target_url=TARGET,
                allowed_source_urls=[SOURCE],
            )

    def test_rejects_same_source_and_destination(self) -> None:
        with self.assertRaisesRegex(ValueError, "forskellige"):
            validate_task_deliverable(json.dumps(link_payload(
                destination_url=SOURCE
            ), ensure_ascii=False))

    def test_rejects_anchor_missing_from_finished_sentence(self) -> None:
        with self.assertRaisesRegex(ValueError, "ordret"):
            validate_task_deliverable(json.dumps(link_payload(
                linked_sentence="Læs mere i den relaterede artikel."
            ), ensure_ascii=False))

    def test_prompt_requires_all_concrete_link_fields(self) -> None:
        prompt = _prompt(
            {
                "website": "site.dk",
                "target_url": TARGET,
                "target_query": "kalenderdeling",
                "experiment_type": "internal_links",
            },
            [{
                "relation": "mulig relateret side",
                "url": SOURCE,
                "excerpt": "Du kan invitere familien.",
            }],
        )

        self.assertIn('relationen "mulig relateret side"', prompt)
        self.assertIn('"source_url"', prompt)
        self.assertIn('"destination_url"', prompt)
        self.assertIn('"anchor_text"', prompt)
        self.assertIn('"link_location"', prompt)
        self.assertIn('"linked_sentence"', prompt)
        self.assertIn("Opfind aldrig en URL", prompt)

    def test_fallback_chooses_a_real_related_page(self) -> None:
        result = fallback_task_deliverable(
            {
                "website": "site.dk",
                "target_url": TARGET,
                "target_query": "kalenderdeling",
                "experiment_type": "internal_links",
            },
            public_context=[{
                "relation": "mulig relateret side",
                "url": SOURCE,
                "excerpt": "Du kan invitere familien til kalenderen.",
            }],
        )

        self.assertEqual(SOURCE, result["source_url"])
        self.assertEqual(TARGET, result["destination_url"])
        self.assertIn(result["anchor_text"], result["linked_sentence"])

    def test_structured_link_survives_approval_serialization(self) -> None:
        description = format_deliverable(link_payload())
        parsed = load_daily_work()._parse_approved_deliverable({
            "description": description
        })

        self.assertEqual(SOURCE, parsed["source_url"])
        self.assertEqual(TARGET, parsed["destination_url"])
        self.assertEqual(
            link_payload()["linked_sentence"], parsed["linked_sentence"]
        )

    def test_daily_work_has_copyable_link_delivery_and_validation(self) -> None:
        source = DAILY_WORK.read_text(encoding="utf-8")

        self.assertIn("def _render_internal_link(", source)
        self.assertIn("Kildeside – her skal linket indsættes", source)
        self.assertIn("Destinationsside – linket skal pege hertil", source)
        self.assertIn("Færdig passage med link", source)
        self.assertIn("validate_internal_link(", source)


if __name__ == "__main__":
    unittest.main()
