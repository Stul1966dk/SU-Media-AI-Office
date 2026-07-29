"""Regression tests for varied, intent-based meta-description CTAs."""

import unittest

from agents.title_optimizer import TitleOptimizer


class VariedMetaCtaTests(unittest.TestCase):
    def test_guide_intent_gets_specific_cta_directions(self) -> None:
        directions = TitleOptimizer._cta_guidance(
            {
                "target_query": "del kalender iphone",
                "target_url": "https://site.dk/hvordan-deler-man-kalender/",
            },
            {"title": "Sådan deler du en kalender", "h1": "Guide"},
        )

        self.assertEqual(
            [
                "Følg guiden",
                "Se hvordan du gør",
                "Lær de vigtigste trin",
            ],
            directions,
        )
        self.assertNotIn("Få overblik over emnet", directions)

    def test_comparison_intent_gets_comparison_ctas(self) -> None:
        directions = TitleOptimizer._cta_guidance(
            {
                "target_query": "bedste løbebånd",
                "target_url": "https://site.dk/bedste-loebebaand/",
            },
            {"title": "Sammenlign løbebånd", "h1": "Modeller og priser"},
        )

        self.assertEqual("Sammenlign mulighederne", directions[0])
        self.assertEqual(3, len(set(directions)))

    def test_prompt_explicitly_limits_overview_cta(self) -> None:
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
            },
            {"limitations": []},
        )

        self.assertIn("forskellige åbninger og handlingsord", prompt)
        self.assertIn("Brug højst 'Få overblik' i ét forslag", prompt)
        self.assertIn("Følg guiden", prompt)

    def test_reviewer_rejects_repeated_meta_openings_and_cta(self) -> None:
        optimizer = object.__new__(TitleOptimizer)
        value = {
            "target_query": "løbebånd",
            "title_proposals": [
                {"text": "Løbebånd | Guide til træning derhjemme"},
            ],
            "meta_proposals": [
                {
                    "text": (
                        "Få overblik over løbebånd, funktioner og modeller, "
                        "så du lettere kan vælge en løsning til hjemmet."
                    )
                },
                {
                    "text": (
                        "Få overblik over priser, motorer og løbeflader, og "
                        "find et løbebånd der passer til din træning."
                    )
                },
                {
                    "text": (
                        "Sammenlign løbebånd på motor, løbeflade og funktioner, "
                        "før du vælger modellen til din hjemmetræning."
                    )
                },
            ],
        }

        review = optimizer.review_proposals(value)

        self.assertEqual(2, len(review["accepted_metas"]))
        self.assertTrue(any(
            '"Få overblik"' in reason
            or "starter som" in reason
            for rejected in review["rejected_metas"]
            for reason in rejected["reasons"]
        ))


if __name__ == "__main__":
    unittest.main()
