"""Sprint 38 automatic experiment-evaluation regression tests."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from core.database import Database
from core.experiment_evaluation import (
    EvaluationRules, ExperimentEvaluationService,
)


class FailingAI:
    def generate_response(self, _prompt):
        raise RuntimeError("offline")


class ExperimentEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        self.rules = EvaluationRules(
            minimum_impressions=100, minimum_days=14,
            minimum_clicks=5, retry_days=7,
        )
        self.service = ExperimentEvaluationService(
            self.database, ai_service=FailingAI(), rules=self.rules
        )

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def experiment(self, *, due="2026-02-01", status="waiting_for_data"):
        experiment_id = self.database.create_seo_experiment({
            "website_id": "site.dk", "target_url": "https://site.dk/side/",
            "target_query": "", "experiment_type": "title_meta",
            "hypothesis": "En tydelig title kan øge CTR.",
            "change_description": "Ny title og meta", "goal_metric": "ctr",
            "goal_direction": "increase", "target_change_pct": 10,
            "waiting_period_days": 14, "status": status, "confidence": 90,
        })
        self.database.update_seo_experiment(experiment_id, {
            "baseline_start": "2026-01-01", "baseline_end": "2026-01-14",
            "baseline_clicks": 10, "baseline_impressions": 500,
            "baseline_ctr": .02, "baseline_position": 8.0,
            "started_at": "2026-01-14T12:00:00+01:00",
            "planned_evaluation_date": due,
        })
        return experiment_id

    def comparison(self, *, clicks=20, impressions=500, ctr=.04, position=8.0):
        self.database.upsert_search_console_dimension(
            dimension_type="page", website_id="site.dk",
            site_url="sc-domain:site.dk", page_url="https://site.dk/side/",
            period_start="2026-01-15", period_end="2026-01-28",
            clicks=clicks, impressions=impressions, ctr=ctr,
            average_position=position,
        )

    def test_due_and_not_due_experiments(self):
        due = self.experiment(due="2026-02-01")
        self.experiment(due="2026-03-01")
        found = self.service.find_due_experiments(date(2026, 2, 1))
        self.assertEqual([due], [item["id"] for item in found])

    def test_equal_periods_metrics_position_and_ai_failure(self):
        experiment_id = self.experiment()
        self.comparison()
        result = self.service.evaluate_experiment(
            experiment_id, reference_date=date(2026, 2, 1)
        )
        self.assertEqual(14, result["comparison_days"])
        self.assertEqual(10, result["clicks_absolute_change"])
        self.assertEqual(0, result["impressions_absolute_change"])
        self.assertAlmostEqual(2.0, result["ctr_percentage_point_change"])
        self.assertAlmostEqual(100.0, result["ctr_relative_change"])
        self.assertEqual(0, result["position_change"])
        self.assertEqual("strong_improvement", result["result_status"])
        self.assertTrue(result["ai_conclusion"])
        self.assertEqual("complete", result["post_analysis"]["decision"])
        stored = self.database.get_experiment_evaluations(experiment_id)[0]
        self.assertEqual("Behold ændringen", stored["post_analysis"]["title"])
        self.assertEqual("completed", self.database.get_seo_experiment(
            experiment_id
        )["status"])

    def test_successful_title_test_can_continue_with_content(self):
        experiment_id = self.experiment()
        experiment = self.database.get_seo_experiment(experiment_id)
        analysis = self.service.build_post_analysis(
            experiment,
            {
                "clicks_before": 10, "clicks_after": 18,
                "ctr_before": .02, "ctr_after": .04,
                "position_before": 13.0, "position_after": 12.0,
                "impressions_after": 500,
            },
            "improvement",
            [],
        )

        self.assertEqual("keep_and_continue", analysis["decision"])
        self.assertEqual("content_update", analysis["next_change_type"])

    def test_insufficient_data_never_starts_another_change(self):
        experiment_id = self.experiment()
        experiment = self.database.get_seo_experiment(experiment_id)
        analysis = self.service.build_post_analysis(
            experiment,
            {
                "clicks_before": 0, "clicks_after": 0,
                "ctr_before": 0, "ctr_after": 0,
                "position_before": 0, "position_after": 0,
                "impressions_after": 10,
            },
            "insufficient_data",
            ["For få visninger."],
        )

        self.assertEqual("wait", analysis["decision"])
        self.assertEqual("none", analysis["next_change_type"])

    def test_zero_baseline_and_insufficient_data_retries(self):
        experiment_id = self.experiment()
        self.database.update_seo_experiment(experiment_id, {
            "baseline_clicks": 0, "baseline_ctr": 0,
        })
        self.comparison(clicks=0, impressions=20, ctr=0)
        result = self.service.evaluate_experiment(
            experiment_id, reference_date=date(2026, 2, 1)
        )
        self.assertIsNone(result["clicks_relative_change"])
        self.assertIsNone(result["ctr_relative_change"])
        self.assertEqual("insufficient_data", result["result_status"])
        experiment = self.database.get_seo_experiment(experiment_id)
        self.assertEqual("waiting_for_data", experiment["status"])
        self.assertEqual("2026-02-08", experiment["planned_evaluation_date"])

    def test_evaluation_is_idempotent(self):
        experiment_id = self.experiment()
        self.comparison()
        self.service.evaluate_experiment(
            experiment_id, reference_date=date(2026, 2, 1)
        )
        self.service.evaluate_experiment(
            experiment_id, reference_date=date(2026, 2, 1)
        )
        self.assertEqual(
            1, len(self.database.get_experiment_evaluations(experiment_id))
        )

    def test_one_failure_does_not_stop_other_experiment(self):
        broken = self.experiment()
        good = self.experiment()
        # Only the second URL receives data; missing data is handled safely too.
        self.comparison()
        original = self.service.evaluate_experiment
        self.service.evaluate_experiment = lambda experiment_id, **kwargs: (
            (_ for _ in ()).throw(RuntimeError("boom"))
            if experiment_id == broken else original(experiment_id, **kwargs)
        )
        results = self.service.evaluate_due_experiments(date(2026, 2, 1))
        self.assertEqual(2, len(results))
        self.assertTrue(any(
            item["result_status"] == "evaluation_failed" for item in results
        ))
        self.assertEqual("completed", self.database.get_seo_experiment(good)["status"])


if __name__ == "__main__":
    unittest.main()
