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
    def test_daily_context_replaces_broken_excerpt_with_article_text(
        self,
    ) -> None:
        page = load_daily_work()

        excerpt = page._usable_content_excerpt({
            "excerpt": (
                "Opret en f?lles kalender p? iPhone og del den med b?rnene."
            ),
            "content_text": (
                "Opret en fælles kalender på iPhone og del den med børnene."
            ),
        })

        self.assertEqual(
            "Opret en fælles kalender på iPhone og del den med børnene.",
            excerpt,
        )

    def test_daily_context_keeps_valid_question_mark(self) -> None:
        page = load_daily_work()

        excerpt = page._usable_content_excerpt({
            "excerpt": "Hvordan deler man en kalender?",
            "content_text": "En anden længere tekst.",
        })

        self.assertEqual("Hvordan deler man en kalender?", excerpt)

    def test_candidate_must_share_a_meaningful_topic(self) -> None:
        page = load_daily_work()

        rows = page._rank_internal_link_candidates(
            {
                "target_url": TARGET,
                "target_query": "hvordan opretter man en Gmail konto",
            },
            [
                {
                    "url": "https://site.dk/kalender/",
                    "title": "Fælles kalender på iPhone",
                    "excerpt": "Del kalenderen med familien.",
                },
                {
                    "url": SOURCE,
                    "title": "Sådan logger du ind på Gmail",
                    "excerpt": "Få adgang til din Gmail konto.",
                },
            ],
            is_locked=lambda _url: False,
        )

        self.assertEqual([SOURCE], [row["url"] for row in rows])

    def test_candidate_with_active_experiment_is_excluded(self) -> None:
        page = load_daily_work()

        rows = page._rank_internal_link_candidates(
            {
                "target_url": TARGET,
                "target_query": "Gmail konto",
            },
            [{
                "url": SOURCE,
                "title": "Gmail login og konto",
                "excerpt": "Administrér din Gmail konto.",
            }],
            is_locked=lambda url: url == SOURCE,
        )

        self.assertEqual([], rows)

    def test_media_and_non_public_content_are_not_link_sources(self) -> None:
        page = load_daily_work()

        rows = page._rank_internal_link_candidates(
            {
                "target_url": TARGET,
                "target_query": "Gmail konto",
            },
            [
                {
                    "url": "https://site.dk/gmail.jpg",
                    "title": "Gmail billede",
                    "content_type": "media",
                    "status": "public",
                },
                {
                    "url": "https://site.dk/gmail-kladde/",
                    "title": "Gmail kladde",
                    "content_type": "post",
                    "status": "draft",
                },
                {
                    "url": SOURCE,
                    "title": "Gmail login",
                    "content_type": "post",
                    "status": "publish",
                },
            ],
            is_locked=lambda _url: False,
        )

        self.assertEqual([SOURCE], [row["url"] for row in rows])

    def test_sparse_content_is_refreshed_before_link_analysis(self) -> None:
        page = load_daily_work()
        events = []

        class FakeDatabase:
            def get_content(self, _website):
                return [{"content_type": "post"}]

        class FakeConnector:
            def __init__(self, **_kwargs):
                pass

            def connect(self):
                events.append("connect")
                return True

            def import_content(self):
                events.append("import")

            def disconnect(self):
                events.append("disconnect")

        refreshed = page._refresh_sparse_internal_link_content(
            FakeDatabase(),
            "site.dk",
            connector_type=FakeConnector,
        )

        self.assertTrue(refreshed)
        self.assertEqual(["connect", "import", "disconnect"], events)

    def test_complete_content_registry_is_not_refetched(self) -> None:
        page = load_daily_work()

        class FakeDatabase:
            def get_content(self, _website):
                return [{"content_type": "post"} for _ in range(10)]

        class UnexpectedConnector:
            def __init__(self, **_kwargs):
                raise AssertionError("Connectoren må ikke startes")

        refreshed = page._refresh_sparse_internal_link_content(
            FakeDatabase(),
            "site.dk",
            connector_type=UnexpectedConnector,
        )

        self.assertFalse(refreshed)

    def test_generation_stops_when_no_safe_source_exists(self) -> None:
        page = load_daily_work()

        class FakeDatabase:
            def get_content(self, _website):
                return [
                    {
                        "url": f"https://site.dk/kalender-{index}/",
                        "title": "Fælles kalender",
                        "excerpt": "Del kalenderen med familien.",
                        "content_type": "post",
                        "status": "publish",
                    }
                    for index in range(10)
                ]

            def get_seo_experiments(self, **_kwargs):
                return []

            def get_title_optimization_drafts(self):
                return []

            def get_seo_url_status(self, _url):
                return []

        with self.assertRaisesRegex(
            page.NoSafeInternalLinkError,
            "ingen emnemæssigt relevant kildeside",
        ):
            page._generate_deliverable(FakeDatabase(), {
                "website": "site.dk",
                "target_url": TARGET,
                "target_query": "Gmail konto",
                "experiment_type": "internal_links",
            })

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
