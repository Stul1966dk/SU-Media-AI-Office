"""Regression tests for Sprint 44.4's unified result and learning flow."""

import unittest
from pathlib import Path

from core.traffic_recommendations import apply_measured_learning


ROOT = Path(__file__).resolve().parents[1]


def source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class UnifiedResultFlowTests(unittest.TestCase):
    def test_results_owns_measurement_outcomes_and_learning(self):
        results = source("dashboard/pages/13_Eksperimenter.py")

        for label in (
            "Aktive målinger", "Afsluttede resultater",
            "Dokumenteret læring", "Forbedret", "Uændret", "Forværret",
            "Anbefalet næste skridt",
        ):
            self.assertIn(label, results)
        self.assertIn("get_seo_learning_entries()", results)
        self.assertIn("Se dokumenterede mønstre og datakvalitet", results)
        self.assertIn("Efteranalyse · hvad skal der ske nu?", results)
        self.assertIn("Se grundlaget for næste beslutning", results)

    def test_old_learning_surfaces_only_point_to_results(self):
        for filename in (
            "dashboard/pages/16_SEO_Laering.py",
            "dashboard/pages/17_SEO_Insights.py",
        ):
            page = source(filename)
            self.assertIn("render_next_step(", page, filename)
            self.assertIn('path="pages/13_Eksperimenter.py"', page, filename)

    def test_learning_is_removed_from_sidebar(self):
        sidebar = source("dashboard/components/ui.py")

        self.assertNotIn('"SEO-læring"', sidebar)

    def test_measured_learning_enriches_future_recommendations(self):
        recommendations = source("core/traffic_recommendations.py")
        today = source("dashboard/pages/15_Dagens_Arbejde.py")

        self.assertIn("def apply_measured_learning(", recommendations)
        self.assertIn("same_url_failures", recommendations)
        self.assertIn('"samme løsning."', recommendations)
        # Learning now enriches selection inside the income-first DecisionEngine
        # that the daily work queue uses, rather than as a page-level pass.
        engine = source("core/decision_engine.py")
        self.assertIn("get_seo_learning_entries()", engine)
        self.assertIn("_steer_by_learning(", engine)
        self.assertIn("learning_adjustment", engine)

    def test_two_failed_same_url_measurements_change_the_advice(self):
        recommendation = {
            "target_url": "https://site.dk/side/",
            "measured_cause": "CTR-fald",
            "recommended_action": "Skriv en ny title.",
        }
        learning = [
            {
                "target_url": recommendation["target_url"],
                "change_type": "title_meta",
                "classification": classification,
            }
            for classification in ("Uændret", "Forværret")
        ]

        result = apply_measured_learning([recommendation], learning)[0]

        self.assertIn("Vælg en anden ændringstype", result["recommended_action"])
        self.assertEqual(
            2, result["learning_evidence"]["same_url_failures"]
        )


if __name__ == "__main__":
    unittest.main()
