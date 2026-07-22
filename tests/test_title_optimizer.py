"""End-to-end tests for the approval-only title optimization pipeline."""

import json
import io
import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.title_optimizer import (
    TitleOptimizer, TitleOptimizationValidationError,
)
from core.database import Database
from core.website_registry import WebsiteRegistry
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
TITLE_PAGE = ROOT / "dashboard" / "pages" / "14_Title_Optimering.py"
EXECUTIVE_PAGE = ROOT / "dashboard" / "pages" / "3_Executive_Briefing.py"


class FakeResponse:
    url = "https://site.dk/guide/"
    text = """
    <html><head><title>Nuværende guide til emnet</title>
    <meta name="description" content="Læs vores nuværende guide til emnet.">
    <link rel="canonical" href="https://site.dk/guide/">
    <script type="application/ld+json">{}</script></head>
    <body><h1>Guide til emnet</h1><p>Ord på siden med nyttigt indhold.</p>
    <a href="/andet/">Internt link</a></body></html>
    """

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.headers = {}
        self.calls = 0

    def get(self, url: str, **kwargs):
        self.calls += 1
        return FakeResponse()


class FakeAI:
    model = "test"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    def generate_response(self, _prompt: str):
        value = self.responses[self.calls]
        self.calls += 1
        return SimpleNamespace(text=value)


def valid_result() -> dict:
    return {
        "website": "ignored", "target_url": "ignored",
        "target_query": "guide til emnet", "current_title": "ignored",
        "current_meta": "ignored",
        "analysis": {
            "problem": "Mange visninger og lav CTR.",
            "evidence": ["1.000 visninger og 2 procent CTR."],
            "limitations": [],
        },
        "title_proposals": [
            {
                "text": "Bedste guide til emnet – praktiske råd og overblik",
                "reason": "Matcher søgeintentionen.", "strengths": ["Konkret"],
                "risks": ["Skal verificeres"],
            },
            {
                "text": "Guide til emnet: Få et klart overblik og gode råd",
                "reason": "Forklarer indholdet.", "strengths": ["Tydelig"],
                "risks": ["Længde"],
            },
            {
                "text": "Sådan bruger du emnet – komplet guide med gode råd",
                "reason": "Handlingsrettet.", "strengths": ["Relevant"],
                "risks": ["Formulering"],
            },
        ],
        "meta_proposals": [
            {
                "text": "Læs en praktisk guide til emnet med klare forklaringer, konkrete råd og et samlet overblik, der hjælper dig videre.",
                "reason": "Opsummerer siden.", "strengths": ["Klar"],
                "risks": ["Ingen"],
            },
            {
                "text": "Få et overskueligt indblik i emnet. Guiden samler de vigtigste råd og forklarer, hvad du skal være opmærksom på.",
                "reason": "Matcher indhold.", "strengths": ["Dansk"],
                "risks": ["Ingen"],
            },
            {
                "text": "Denne guide forklarer emnet trin for trin og giver dig konkrete råd, nyttig viden og et bedre grundlag for dit valg.",
                "reason": "Konkrete fordele.", "strengths": ["Relevant"],
                "risks": ["Ingen"],
            },
        ],
        "recommended_title_index": 0, "recommended_meta_index": 0,
        "confidence": 82, "expected_effect": "Højere CTR.",
        "measurement_method": "Sammenlign CTR efter 28 dage.",
    }


class TitleOptimizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        self.database.upsert_website({
            "website": "site.dk", "display_name": "Site", "active": True,
            "monetized": True, "priority": "medium",
            "primary_income_source": "affiliate", "niche": "test",
            "domain_age": "1", "notes": "", "status": "active",
        })
        for start, end, clicks in (
            ("2026-05-24", "2026-06-20", 30),
            ("2026-06-21", "2026-07-18", 20),
        ):
            for dimension, page, query in (
                ("page", "https://site.dk/guide/", None),
                ("query", None, "guide til emnet"),
                ("page_query", "https://site.dk/guide/", "guide til emnet"),
            ):
                self.database.upsert_search_console_dimension(
                    dimension_type=dimension, website_id="site.dk",
                    site_url="https://site.dk/", page_url=page, query=query,
                    period_start=start, period_end=end, clicks=clicks,
                    impressions=1000, ctr=clicks / 1000,
                    average_position=7,
                )

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def optimizer(self, responses: list[str]) -> TitleOptimizer:
        return TitleOptimizer(
            database=self.database,
            website_registry=WebsiteRegistry(self.database),
            ai_service=FakeAI(responses), session=FakeSession(),
        )

    def test_complete_flow_selects_page_query_and_public_snippet(self) -> None:
        optimizer = self.optimizer([json.dumps(valid_result())])
        candidate = optimizer.select_candidate("site.dk")
        self.assertEqual("https://site.dk/guide/", candidate["target_url"])
        self.assertEqual("guide til emnet", candidate["target_query"])
        page = optimizer.analyze_current_snippet(candidate)
        self.assertEqual("Nuværende guide til emnet", page["title"])
        self.assertEqual("Læs vores nuværende guide til emnet.", page["meta_description"])
        draft_id = optimizer.run("site.dk")
        draft = self.database.get_title_optimization_draft(draft_id)
        self.assertEqual(3, len(draft["title_proposals"]))
        self.assertEqual(3, len(draft["meta_proposals"]))
        self.assertEqual("awaiting_approval", draft["status"])
        self.assertTrue(draft["reviewer"]["approved"])

    def test_invalid_json_is_repaired_once(self) -> None:
        ai = FakeAI(["not json", json.dumps(valid_result())])
        optimizer = TitleOptimizer(
            database=self.database,
            website_registry=WebsiteRegistry(self.database),
            ai_service=ai, session=FakeSession(),
        )
        draft_id = optimizer.run("site.dk")
        self.assertTrue(draft_id)
        self.assertEqual(2, ai.calls)

    def test_previous_alias_response_is_normalized_with_safe_defaults(self) -> None:
        aliased = {
            "seo_title": [
                {"title": item["text"], "explanation": item["reason"]}
                for item in valid_result()["title_proposals"]
            ],
            "meta_description": [
                item["text"] for item in valid_result()["meta_proposals"]
            ],
            "explanation": "CTR er lav i forhold til visningerne.",
            "confidence": "79",
        }
        optimizer = self.optimizer([json.dumps(aliased)])
        draft_id = optimizer.run("site.dk")
        draft = self.database.get_title_optimization_draft(draft_id)
        self.assertEqual(3, len(draft["title_proposals"]))
        self.assertEqual(3, len(draft["meta_proposals"]))
        self.assertEqual(79, draft["confidence"])
        self.assertEqual(0, draft["recommended_title_index"])
        self.assertTrue(draft["expected_effect"])
        self.assertTrue(draft["measurement_method"])

    def test_actual_repair_shape_titles_and_meta_descriptions_regression(
        self,
    ) -> None:
        repaired_shape = {
            "titles": [
                "Guide til emnet – praktiske råd og et klart overblik",
                "Guide til emnet: Sådan får du overblik og gode råd",
                "Guide til emnet med forklaringer, valg og nyttige råd",
            ],
            "meta_descriptions": [
                item["text"] for item in valid_result()["meta_proposals"]
            ],
        }
        optimizer = self.optimizer([json.dumps(repaired_shape)])
        draft_id = optimizer.run("site.dk")
        draft = self.database.get_title_optimization_draft(draft_id)
        self.assertEqual(3, len(draft["title_proposals"]))
        self.assertEqual(3, len(draft["meta_proposals"]))
        self.assertEqual("awaiting_approval", draft["status"])
        self.assertTrue(draft["reviewer"]["approved"])

    def test_final_error_lists_only_missing_critical_fields(self) -> None:
        incomplete = json.dumps({
            "seo_title": ["Kun ét title-forslag til guide til emnet"],
            "meta": ["Kun én metabeskrivelse med for lidt grundlag"],
            "confidence": 70,
        })
        optimizer = self.optimizer([incomplete, incomplete])
        with self.assertRaises(TitleOptimizationValidationError) as raised:
            optimizer.run("site.dk")
        self.assertEqual("critical_fields", raised.exception.phase)
        self.assertIn(
            "title_proposals (præcis 3)",
            raised.exception.missing_fields,
        )
        self.assertIn(
            "meta_proposals (præcis 3)",
            raised.exception.missing_fields,
        )
        self.assertNotIn(
            "Modelsvar mangler krævede felter", str(raised.exception)
        )

    def test_structure_log_contains_keys_and_types_but_not_values(self) -> None:
        stream = io.StringIO()
        logger = logging.getLogger("title-optimizer-test")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.addHandler(logging.StreamHandler(stream))
        optimizer = TitleOptimizer(
            database=self.database,
            website_registry=WebsiteRegistry(self.database),
            ai_service=FakeAI([json.dumps(valid_result())]),
            session=FakeSession(), logger=logger,
        )
        optimizer.run("site.dk")
        logged = stream.getvalue()
        self.assertIn("title_proposals", logged)
        self.assertIn('"length": 3', logged)
        self.assertNotIn("Bedste guide til emnet", logged)

    def test_approval_locks_and_implementation_starts_experiment(self) -> None:
        optimizer = self.optimizer([json.dumps(valid_result())])
        draft_id = optimizer.run("site.dk")
        draft = self.database.get_title_optimization_draft(draft_id)
        result = optimizer.approve_draft(
            draft_id, draft["selected_title"], draft["selected_meta"]
        )
        repeated = optimizer.approve_draft(
            draft_id, draft["selected_title"], draft["selected_meta"]
        )
        self.assertEqual(result, repeated)
        self.assertEqual(
            1, len(self.database.get_task_records_for_project(
                result["project_id"]
            ))
        )
        self.assertEqual(
            1, len(self.database.get_seo_experiments(
                target_url="https://site.dk/guide/"
            ))
        )
        experiment = self.database.get_seo_experiment(result["experiment_id"])
        self.assertEqual("planned", experiment["status"])
        approved = self.database.get_approved_changes(
            experiment_id=result["experiment_id"]
        )
        self.assertEqual(1, len(approved))
        self.assertEqual(draft["selected_title"], approved[0]["approved_title"])
        self.assertEqual(draft["selected_meta"], approved[0]["approved_meta"])
        self.assertEqual(
            "awaiting_implementation", approved[0]["status"]
        )
        self.assertTrue(
            optimizer.experiments.is_url_locked("https://site.dk/guide/")
        )
        self.assertEqual(
            1, len(self.database.get_task_records_for_project(
                result["project_id"]
            ))
        )
        started = optimizer.mark_implemented(draft_id)
        self.assertEqual(started, optimizer.mark_implemented(draft_id))
        self.assertEqual("waiting_for_data", started["status"])
        self.assertEqual(28, started["waiting_period_days"])
        self.assertEqual(
            "measurement_period",
            self.database.get_approved_changes(
                experiment_id=result["experiment_id"]
            )[0]["status"],
        )
        self.assertIsNotNone(
            self.database.get_title_optimization_draft(
                draft_id
            )["implemented_at"]
        )

    def test_reviewer_rejects_spam_and_duplicates(self) -> None:
        value = valid_result()
        value["title_proposals"][1]["text"] = value["title_proposals"][0]["text"]
        value["title_proposals"][0]["text"] = "Verdens bedste mirakel!!!"
        review = self.optimizer([]).review_proposals(value)
        self.assertTrue(review["approved"])
        self.assertEqual(2, len(review["accepted_titles"]))
        self.assertEqual(1, len(review["rejected_titles"]))

    def test_reviewer_keeps_all_three_valid_proposals(self) -> None:
        review = self.optimizer([]).review_proposals(valid_result())
        self.assertTrue(review["approved"])
        self.assertEqual(3, len(review["accepted_titles"]))
        self.assertEqual(3, len(review["accepted_metas"]))
        self.assertFalse(review["rejected_titles"])

    def test_reviewer_keeps_two_valid_titles(self) -> None:
        value = valid_result()
        value["title_proposals"][2]["text"] = "For kort"
        review = self.optimizer([]).review_proposals(value)
        self.assertTrue(review["approved"])
        self.assertEqual(2, len(review["accepted_titles"]))
        self.assertEqual(1, len(review["rejected_titles"]))

    def test_reviewer_keeps_one_valid_title(self) -> None:
        value = valid_result()
        value["title_proposals"][1]["text"] = "For kort"
        value["title_proposals"][2]["text"] = "Verdens bedste mirakel!!!"
        review = self.optimizer([]).review_proposals(value)
        self.assertTrue(review["approved"])
        self.assertEqual(1, len(review["accepted_titles"]))
        self.assertEqual(2, len(review["rejected_titles"]))

    def test_reviewer_auto_shortens_small_title_overrun(self) -> None:
        value = valid_result()
        value["title_proposals"][0]["text"] = (
            "Guide til emnet med praktiske råd og et meget klart samlet "
            "overblik nu nu"
        )
        self.assertGreater(len(value["title_proposals"][0]["text"]), 70)
        self.assertLessEqual(len(value["title_proposals"][0]["text"]), 75)
        review = self.optimizer([]).review_proposals(value)
        self.assertTrue(review["approved"])
        shortened = review["accepted_titles"][0]
        self.assertLessEqual(len(shortened["text"]), 70)
        self.assertTrue(shortened["reviewer_corrections"])

    def test_reviewer_stops_only_when_all_of_one_type_are_invalid(self) -> None:
        value = valid_result()
        for proposal in value["title_proposals"]:
            proposal["text"] = "For kort"
        review = self.optimizer([]).review_proposals(value)
        self.assertFalse(review["approved"])
        self.assertEqual(0, len(review["accepted_titles"]))
        self.assertEqual(3, len(review["accepted_metas"]))
        self.assertEqual(
            ["Alle titleforslag blev forkastet."], review["errors"]
        )

    def test_rejection_creates_no_task_or_experiment(self) -> None:
        optimizer = self.optimizer([json.dumps(valid_result())])
        draft_id = optimizer.run("site.dk")
        optimizer.reject_draft(draft_id)
        self.assertEqual(
            "rejected",
            self.database.get_title_optimization_draft(draft_id)["status"],
        )
        self.assertFalse(self.database.get_projects("site.dk"))
        self.assertFalse(
            self.database.get_seo_experiments(website_id="site.dk")
        )

    def test_human_ui_starts_with_recommendation_and_renders_cards(self) -> None:
        result = valid_result()
        result.update({
            "website": "site.dk",
            "target_url": "https://site.dk/guide/",
            "target_query": "guide til emnet",
            "current_title": "Nuværende guide til emnet",
            "current_meta": "Nuværende beskrivelse",
            "page_analysis": {
                "title": "Nuværende guide til emnet",
                "search_console": {
                    "clicks": 20, "impressions": 1000, "ctr": .02,
                    "position": 7, "period": "21.06.2026 – 18.07.2026",
                },
            },
        })
        review = self.optimizer([]).review_proposals(result)
        result["reviewer"] = review
        result["title_proposals"] = review["accepted_titles"]
        result["meta_proposals"] = review["accepted_metas"]
        self.database.create_title_optimization_draft(result, [])
        previous = os.environ.get("SU_MEDIA_DATABASE_PATH")
        os.environ["SU_MEDIA_DATABASE_PATH"] = str(self.database.path)
        try:
            app = AppTest.from_file(
                str(TITLE_PAGE), default_timeout=20
            ).run()
        finally:
            if previous is None:
                os.environ.pop("SU_MEDIA_DATABASE_PATH", None)
            else:
                os.environ["SU_MEDIA_DATABASE_PATH"] = previous
        self.assertFalse(app.exception)
        labels = [button.label for button in app.button]
        self.assertEqual(3, labels.count("Vælg denne title"))
        self.assertEqual(3, labels.count("Vælg denne metabeskrivelse"))
        self.assertIn("Godkend anbefalet forslag", labels)
        self.assertIn("Vælg et andet forslag", labels)
        self.assertIn("Redigér selv", labels)
        self.assertIn("Afvis alle forslag", labels)
        source = TITLE_PAGE.read_text(encoding="utf-8")
        self.assertLess(
            source.index("AI anbefaler denne ændring"),
            source.index("Se datagrundlag og tekniske detaljer"),
        )
        self.assertIn('expanded=False', source)
        executive = EXECUTIVE_PAGE.read_text(encoding="utf-8")
        self.assertIn("Gennemgå title-forslaget for", executive)
        self.assertIn("Anbefalet metabeskrivelse", executive)


if __name__ == "__main__":
    unittest.main()
