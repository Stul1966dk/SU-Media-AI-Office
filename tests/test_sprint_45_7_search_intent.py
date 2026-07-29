"""Regression tests for explicit, grounded search intent."""

import unittest
from pathlib import Path

from agents.title_optimizer import TitleOptimizer


ROOT = Path(__file__).resolve().parents[1]
DAILY_WORK = ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
QUEUE = ROOT / "core" / "work_queue_service.py"


class SearchIntentTests(unittest.TestCase):
    def test_rule_fallback_classifies_guide_intent(self) -> None:
        intent = TitleOptimizer._infer_search_intent(
            {
                "target_query": "del kalender iphone",
                "target_url": "https://site.dk/hvordan-deler-man-kalender/",
            },
            {
                "title": "Sådan deler du kalenderen",
                "h1": "Guide trin for trin",
                "content_excerpt": "Følg disse trin.",
            },
        )

        self.assertEqual("guide", intent["type"])
        self.assertGreaterEqual(intent["confidence"], 70)
        self.assertFalse(intent["ambiguous"])
        self.assertTrue(intent["evidence"])

    def test_rule_fallback_classifies_tool_before_guide(self) -> None:
        intent = TitleOptimizer._infer_search_intent(
            {
                "target_query": "beregn skridtlængde",
                "target_url": "https://site.dk/beregner/",
            },
            {
                "title": "Sådan beregner du skridtlængde",
                "h1": "Beregner",
                "content_excerpt": "Indtast distance og antal skridt.",
            },
        )

        self.assertEqual("tool", intent["type"])

    def test_weak_default_is_marked_ambiguous(self) -> None:
        intent = TitleOptimizer._infer_search_intent(
            {"target_query": "kaffe", "target_url": "https://site.dk/kaffe/"},
            {"title": "Kaffe", "h1": "Kaffe", "content_excerpt": "Om kaffe."},
        )

        self.assertEqual("informational", intent["type"])
        self.assertTrue(intent["ambiguous"])
        self.assertLess(intent["confidence"], 65)

    def test_valid_model_intent_is_preserved(self) -> None:
        intent = TitleOptimizer._normalize_search_intent(
            {
                "type": "comparison",
                "summary": "Brugeren vil sammenligne to løsninger.",
                "evidence": ["Queryen indeholder versus."],
                "confidence": 88,
                "ambiguous": False,
            },
            {"target_query": "a vs b", "target_url": "https://site.dk/a-vs-b/"},
            {"title": "A eller B", "h1": "Sammenligning"},
        )

        self.assertEqual("comparison", intent["type"])
        self.assertEqual(88, intent["confidence"])

    def test_incomplete_model_intent_uses_grounded_fallback(self) -> None:
        intent = TitleOptimizer._normalize_search_intent(
            {"type": "comparison", "summary": "", "evidence": []},
            {
                "target_query": "hvordan deler jeg kalender",
                "target_url": "https://site.dk/guide/",
            },
            {"title": "Guide", "h1": "Sådan gør du"},
        )

        self.assertEqual("guide", intent["type"])

    def test_reviewer_rejects_unsupported_comparison_promise(self) -> None:
        issues = TitleOptimizer._grounding_issues(
            "Sammenlign alle løsninger og vælg den rigtige til dit behov.",
            {
                "title": "Sådan deler du en kalender",
                "h1": "Guide",
                "content_excerpt": "Følg trinene for at dele kalenderen.",
            },
            {"type": "guide"},
        )

        self.assertTrue(any("sammenligning" in issue for issue in issues))

    def test_reviewer_accepts_documented_tool_promise(self) -> None:
        issues = TitleOptimizer._grounding_issues(
            "Beregn din skridtlængde og se hvad resultatet betyder.",
            {
                "title": "Skridtlængdeberegner",
                "h1": "Beregn din skridtlængde",
                "content_excerpt": "Indtast højde og distance i beregneren.",
            },
            {"type": "tool"},
        )

        self.assertEqual([], issues)

    def test_prompt_requires_intent_and_content_grounding(self) -> None:
        prompt = TitleOptimizer._prompt(
            {
                "website": "site.dk",
                "target_url": "https://site.dk/guide/",
                "target_query": "guide",
            },
            {
                "title": "Guide",
                "meta_description": "",
                "h1": "Guide",
                "content_excerpt": "En praktisk vejledning.",
            },
            {"limitations": []},
        )

        self.assertIn("Klassificér først søgeintentionen", prompt)
        self.assertIn("må kun love indhold", prompt)
        self.assertIn('"search_intent"', prompt)

    def test_intent_flows_to_daily_work_and_is_visible(self) -> None:
        queue_source = QUEUE.read_text(encoding="utf-8")
        daily_source = DAILY_WORK.read_text(encoding="utf-8")

        self.assertIn('"search_intent": (', queue_source)
        self.assertIn("_render_search_intent(item)", daily_source)
        self.assertIn("Vurderet søgeintention", daily_source)
        self.assertIn("Se evidens for søgeintentionen", daily_source)
        self.assertIn("Søgeintentionen er tvetydig", daily_source)


if __name__ == "__main__":
    unittest.main()
