"""Hard guard against volatile prices in titles and meta descriptions."""

import json
import unittest

from agents.title_optimizer import TitleOptimizer
from core.task_deliverables import mentions_price, validate_task_deliverable


class NoPricesInSnippetsTests(unittest.TestCase):
    def test_price_detector_covers_words_amounts_and_currency(self) -> None:
        for text in (
            "Se de aktuelle priser",
            "Kun 1.999 kr.",
            "Modellen koster 2499 DKK",
            "Spar €50 i dag",
            "Pris og kvalitet",
        ):
            with self.subTest(text=text):
                self.assertTrue(mentions_price(text))
                self.assertTrue(TitleOptimizer._mentions_price(text))

        self.assertFalse(mentions_price("Sammenlign modeller og funktioner"))

    def test_title_reviewer_rejects_price_language(self) -> None:
        reviewed, reasons, _ = TitleOptimizer._review_one(
            {
                "text": (
                    "Løbebånd | Sammenlign priser og modeller til hjemmet"
                )
            },
            kind="title",
            query="løbebånd",
        )

        self.assertTrue(reviewed["text"])
        self.assertTrue(any("priser" in reason for reason in reasons))

    def test_meta_reviewer_rejects_concrete_amount(self) -> None:
        _, reasons, _ = TitleOptimizer._review_one(
            {
                "text": (
                    "Sammenlign løbebånd og find en model til 2.999 kr. "
                    "med funktioner, der passer til hjemmetræning."
                )
            },
            kind="meta",
            query="",
        )

        self.assertTrue(any("beløb" in reason for reason in reasons))

    def test_generic_deliverable_rejects_prices(self) -> None:
        payload = {
            "deliverable_type": "title_meta",
            "summary": "Et færdigt snippet.",
            "recommended_option": (
                "Title: Løbebånd | Se modeller fra 2.999 kr.\n"
                "Meta: Sammenlign funktioner og vælg en model til hjemmet."
            ),
            "alternatives": ["A", "B"],
            "rationale": "Data.",
            "implementation_steps": ["Indsæt manuelt."],
            "validation_checks": ["Kontrollér siden."],
        }

        with self.assertRaisesRegex(ValueError, "priser"):
            validate_task_deliverable(json.dumps(payload))

    def test_both_prompts_contain_the_absolute_price_rule(self) -> None:
        title_prompt = TitleOptimizer._prompt(
            {
                "website": "site.dk",
                "target_url": "https://site.dk/side/",
                "target_query": "løbebånd",
            },
            {"title": "Løbebånd", "meta_description": "", "h1": "Guide"},
            {"limitations": []},
        )
        from core.task_deliverables import _prompt as deliverable_prompt

        generic_prompt = deliverable_prompt({
            "website": "site.dk",
            "target_url": "https://site.dk/side/",
            "target_query": "løbebånd",
            "measured_cause": "CTR-fald",
        }, [])

        self.assertIn("må aldrig omtale priser", title_prompt)
        self.assertIn("må aldrig omtale priser", generic_prompt)


if __name__ == "__main__":
    unittest.main()
