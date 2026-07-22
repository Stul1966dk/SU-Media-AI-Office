"""Sprint 38.2 analytical UX and insufficient-data tests."""

import importlib.util
import inspect
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from core.database import Database
from core.experiment_evaluation import ExperimentEvaluationService


ROOT = Path(__file__).resolve().parents[1]


def load_experiment_page():
    path = ROOT / "dashboard" / "pages" / "13_Eksperimenter.py"
    spec = importlib.util.spec_from_file_location("experiment_page_38_2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfflineAI:
    def generate_response(self, _prompt):
        raise RuntimeError("offline")


class StatusChangingAI:
    def generate_response(self, _prompt):
        return SimpleNamespace(text="Resultatet er en forværring.")


class Sprint382Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "sprint382.db")
        self.database.initialize()

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def create_experiment(self, *, low_data=False):
        experiment_id = self.database.create_seo_experiment({
            "website_id": "test.local", "target_url": "https://test.local/a/",
            "target_query": "", "experiment_type": "title_meta",
            "hypothesis": "Tydeligere tekst kan øge CTR.",
            "change_description": "Ny title og meta", "goal_metric": "ctr",
            "goal_direction": "increase", "target_change_pct": 15,
            "waiting_period_days": 7 if low_data else 28,
            "status": "waiting_for_data", "confidence": 90,
        })
        baseline_start = "2026-06-01" if low_data else "2026-05-01"
        baseline_end = "2026-06-07" if low_data else "2026-05-28"
        started_at = "2026-06-08T10:00:00+02:00" if low_data else "2026-05-29T10:00:00+02:00"
        self.database.update_seo_experiment(experiment_id, {
            "baseline_start": baseline_start, "baseline_end": baseline_end,
            "baseline_clicks": 3 if low_data else 40,
            "baseline_impressions": 60 if low_data else 1000,
            "baseline_ctr": .05 if low_data else .04,
            "baseline_position": 8.0 if low_data else 7.2,
            "started_at": started_at,
            "planned_evaluation_date": "2026-06-16" if low_data else "2026-06-27",
        })
        self.database.upsert_search_console_dimension(
            dimension_type="page", website_id="test.local",
            site_url="sc-domain:test.local", page_url="https://test.local/a/",
            period_start="2026-06-09" if low_data else "2026-05-30",
            period_end="2026-06-15" if low_data else "2026-06-26",
            clicks=2 if low_data else 65,
            impressions=40 if low_data else 1100,
            ctr=.05 if low_data else 65 / 1100,
            average_position=8.0 if low_data else 7.1,
        )
        return experiment_id

    def test_fallback_is_analytical_and_cautious(self):
        metrics = {
            "position_change": .1, "ctr_before": .04, "ctr_after": .059,
            "clicks_before": 40, "clicks_after": 65,
        }
        text = ExperimentEvaluationService._fallback_conclusion(
            metrics, "strong_improvement", []
        )
        self.assertIn("placering var stort set uændret", text)
        self.assertIn("bør fortsat følges", text)
        self.assertNotIn("CTR ændrede sig fra", text)

    def test_ai_text_cannot_change_rule_status(self):
        experiment_id = self.create_experiment()
        result = ExperimentEvaluationService(
            self.database, ai_service=StatusChangingAI()
        ).evaluate_experiment(experiment_id, reference_date=date(2026, 7, 21))
        self.assertEqual("strong_improvement", result["result_status"])

    def test_insufficient_data_is_safe_retried_and_idempotent(self):
        experiment_id = self.create_experiment(low_data=True)
        service = ExperimentEvaluationService(
            self.database, ai_service=OfflineAI()
        )
        first = service.evaluate_experiment(
            experiment_id, reference_date=date(2026, 7, 21)
        )
        second = service.evaluate_experiment(
            experiment_id, reference_date=date(2026, 7, 22)
        )
        evaluations = self.database.get_experiment_evaluations(experiment_id)
        experiment = self.database.get_seo_experiment(experiment_id)
        self.assertEqual("insufficient_data", first["result_status"])
        self.assertEqual("insufficient_data", second["result_status"])
        self.assertNotIn("virkede", first["ai_conclusion"])
        self.assertEqual(1, len(evaluations))
        self.assertEqual("2026-06-16", evaluations[0]["evaluation_due_at"])
        self.assertEqual("2026-07-28", experiment["planned_evaluation_date"])
        self.assertEqual("waiting_for_data", experiment["status"])
        self.assertEqual(3, len(evaluations[0]["caveats"]))

    def test_user_interface_hides_empty_learning_and_duplicate_baseline(self):
        page = load_experiment_page()
        detail_source = inspect.getsource(page._detail)
        self.assertNotIn("Læring: Ikke oprettet", detail_source)
        self.assertNotIn("**Baseline:**", detail_source)

    def test_position_and_next_steps_are_natural_danish(self):
        page = load_experiment_page()
        source = inspect.getsource(page._detail)
        self.assertIn("Positionsforbedring", source)
        self.assertIn("Positionsforværring", source)
        self.assertEqual(
            "Bevar ændringen og fortsæt overvågningen.",
            page._next_step("strong_improvement"),
        )
        self.assertEqual(
            "Afvent mere data. Ingen konklusion endnu.",
            page._next_step("insufficient_data"),
        )

    def test_missing_requirements_are_presented(self):
        page = load_experiment_page()
        source = inspect.getsource(page._insufficient_requirements)
        for label in ("Visninger", "Klik", "Datadage"):
            self.assertIn(label, source)
        self.assertEqual("❌ Ikke opfyldt", page._requirement_status(40, 100))
        self.assertEqual("✅ Opfyldt", page._requirement_status(100, 100))
        self.assertIn("EvaluationRules.from_environment", source)
        self.assertNotIn("mindst 100", source)

    def test_completed_measurement_and_retry_are_separate_in_ui(self):
        source = inspect.getsource(load_experiment_page()._active_card)
        self.assertIn("Måleperioden er afsluttet", source)
        self.assertIn("Næste evaluering", source)
        self.assertIn("measurement_remaining", source)
        self.assertNotIn("f\"{remaining} {days_label} tilbage\"", source)


if __name__ == "__main__":
    unittest.main()
