"""Reviewer must treat Danish inflections of the target query as relevant.

Regression for the "reviewer_failed" dead end on
helpdesken.dk/skift-soegemaskine-i-browser/, where every title used the
natural singular "søgemaskine" while the target query was the plural
"søgemaskiner", so the raw substring match rejected all titles.
"""

import unittest

from agents.title_optimizer import TitleOptimizer


class QueryRelevanceInflectionTests(unittest.TestCase):
    def test_plural_query_matches_singular_title(self) -> None:
        self.assertTrue(
            TitleOptimizer._query_relevant(
                "Skift søgemaskine i browser – se hvordan du gør",
                "søgemaskiner",
            )
        )

    def test_singular_query_still_matches_plural_title(self) -> None:
        self.assertTrue(
            TitleOptimizer._query_relevant(
                "De bedste søgemaskiner til privatlivet",
                "søgemaskine",
            )
        )

    def test_query_word_inside_compound_still_matches(self) -> None:
        self.assertTrue(
            TitleOptimizer._query_relevant(
                "Guide til internetsøgemaskiner",
                "søgemaskiner",
            )
        )

    def test_unrelated_title_is_still_rejected(self) -> None:
        self.assertFalse(
            TitleOptimizer._query_relevant(
                "Sådan sikrer du din router derhjemme",
                "søgemaskiner",
            )
        )

    def test_short_stem_does_not_over_match(self) -> None:
        # "bil" (stem 3) must not be accepted via inflection against unrelated
        # words; only the min-length-4 prefix rule may grant a match.
        self.assertFalse(TitleOptimizer._inflected_match("biler", "bil"))
        self.assertTrue(TitleOptimizer._inflected_match("biler", "bile"))

    def test_reviewer_accepts_inflected_titles_end_to_end(self) -> None:
        optimizer = object.__new__(TitleOptimizer)
        value = {
            "target_query": "søgemaskiner",
            "title_proposals": [
                {"text": "Skift søgemaskine i browser – følg guiden her"},
            ],
            "meta_proposals": [
                {
                    "text": (
                        "Se hvordan du skifter søgemaskine i Chrome, Edge og "
                        "Firefox med en enkel trin-for-trin guide fra os."
                    )
                },
            ],
        }

        review = optimizer.review_proposals(value)

        self.assertTrue(review["approved"], review["errors"])
        self.assertEqual(1, len(review["accepted_titles"]))


if __name__ == "__main__":
    unittest.main()
