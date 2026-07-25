"""Sprint 41.2 tests for SEO Health explanation and presentation."""

import unittest
from pathlib import Path

from core.seo_history import _calculate_score, _trend_from_score


class SEOHealthExplanationTests(unittest.TestCase):
    def test_crosstrainer_growing_is_explained_by_full_score(self) -> None:
        score = _calculate_score(
            click_change=0.0,
            impression_change=270.0,
            ctr_change=0.0,
            position_change=-1.183783783783781,
        )

        self.assertEqual(73.6, score)
        self.assertEqual("growing", _trend_from_score(score))

    def test_existing_trend_thresholds_are_unchanged(self) -> None:
        for score, expected in (
            (70, "growing"),
            (69.9, "stable"),
            (45, "stable"),
            (44.9, "declining"),
            (25, "declining"),
            (24.9, "critical"),
        ):
            self.assertEqual(expected, _trend_from_score(score))

    def test_dashboard_uses_one_decimal_and_column_help(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
        ).read_text(encoding="utf-8")

        self.assertGreaterEqual(source.count('format="%.1f"'), 3)
        for explanation in (
            "ændringer i klik, ",
            "Growing: mindst 70.",
            "Procentvis ændring i klik",
            "Negativ er ",
        ):
            self.assertIn(explanation, source)


if __name__ == "__main__":
    unittest.main()
