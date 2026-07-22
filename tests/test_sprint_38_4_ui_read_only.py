"""Sprint 38.4 regression tests for read-only dashboard rendering."""

import hashlib
import os
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from core.database import Database
from core.experiment_automation import ExperimentAutomationService


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_PAGE = ROOT / "dashboard" / "pages" / "13_Eksperimenter.py"
BRIEFING_PAGE = ROOT / "dashboard" / "pages" / "3_Executive_Briefing.py"


class Sprint384ReadOnlyUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ui-read-only.db"
        database = Database(self.path)
        database.initialize()
        database.upsert_website({
            "website": "test.local", "display_name": "Test", "active": True,
            "monetized": False, "priority": "medium",
            "primary_income_source": "test", "niche": "test",
            "domain_age": "0", "notes": "", "status": "active",
        })
        experiment_id = database.create_seo_experiment({
            "website_id": "test.local", "target_url": "https://test.local/a/",
            "target_query": "", "experiment_type": "title_meta",
            "hypothesis": "Test", "change_description": "Ny title",
            "goal_metric": "ctr", "goal_direction": "increase",
            "target_change_pct": 10, "waiting_period_days": 28,
            "status": "waiting_for_data", "confidence": 80,
        })
        database.update_seo_experiment(experiment_id, {
            "baseline_start": "2026-06-01", "baseline_end": "2026-06-28",
            "baseline_clicks": 10, "baseline_impressions": 500,
            "baseline_ctr": .02, "baseline_position": 7,
            "started_at": "2026-06-29T10:00:00+02:00",
            "planned_evaluation_date": "2026-07-27",
        })
        database.save_experiment_snapshot({
            "experiment_id": experiment_id, "observed_date": "2026-07-20",
            "period_start": "2026-06-22", "period_end": "2026-07-19",
            "clicks": 12, "impressions": 510, "ctr": .0235,
            "average_position": 6.9, "data_quality": "Middel",
            "pulse_status": "Under måling", "observation": "Stabil udvikling.",
        })
        database.save_experiment_observation(
            experiment_id=experiment_id, observation_date="2026-06-29",
            observation_type="implementeret", event_key="implemented",
            description="Ændringen blev markeret som implementeret.",
        )
        database.close()

    def tearDown(self):
        self.temp.cleanup()

    def digest(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def counts(self):
        database = Database(self.path)
        database.initialize()
        try:
            return {
                "snapshots": len(database.get_experiment_snapshots(1)),
                "observations": len(database.get_experiment_observations(1)),
                "evaluations": len(database.get_experiment_evaluations(1)),
                "experiments": len(database.get_seo_experiments()),
            }
        finally:
            database.close()

    def test_open_and_rerun_experiments_are_read_only(self):
        before_counts = self.counts()
        before_hash = self.digest()
        with patch.dict(os.environ, {"SU_MEDIA_DATABASE_PATH": str(self.path)}):
            app = AppTest.from_file(str(EXPERIMENT_PAGE)).run(timeout=20)
            self.assertEqual([], app.exception)
            app.run(timeout=20)
            self.assertEqual([], app.exception)
        self.assertEqual(before_counts, self.counts())
        self.assertEqual(before_hash, self.digest())

    def test_ui_sources_do_not_run_automatic_writers(self):
        experiment_source = EXPERIMENT_PAGE.read_text(encoding="utf-8")
        briefing_source = BRIEFING_PAGE.read_text(encoding="utf-8")
        for forbidden in (
            "update_active_experiments(", "evaluate_due_experiments(",
        ):
            self.assertNotIn(forbidden, experiment_source)
            self.assertNotIn(forbidden, briefing_source)
        self.assertIn("open_database(read_only=True)", experiment_source)

    def test_experiment_database_connection_rejects_writes(self):
        database = Database(self.path)
        database.initialize_read_only()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                database.update_seo_experiment(1, {"status": "completed"})
        finally:
            database.close()

    def test_background_automation_runs_monitoring_then_evaluation(self):
        monitoring, evaluation = Mock(), Mock()
        monitoring.update_active_experiments.return_value = [{"id": 1}]
        evaluation.evaluate_due_experiments.return_value = [{"id": 1}]
        service = ExperimentAutomationService(
            Mock(), monitoring=monitoring, evaluation=evaluation
        )
        result = service.run_after_search_console_sync(date(2026, 7, 22))
        monitoring.update_active_experiments.assert_called_once_with(
            date(2026, 7, 22)
        )
        evaluation.evaluate_due_experiments.assert_called_once_with(
            date(2026, 7, 22)
        )
        self.assertEqual(1, len(result["monitored"]))
        self.assertEqual(1, len(result["evaluated"]))

    def test_main_triggers_automation_only_after_successful_sync(self):
        source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
        sync_index = source.index("data_sync_result = search_console.sync_all_properties")
        automation_index = source.index("run_after_search_console_sync()")
        except_index = source.index("except SearchConsoleAuthenticationError")
        else_index = source.index("else:", except_index)
        self.assertGreater(automation_index, else_index)
        self.assertGreater(automation_index, sync_index)


if __name__ == "__main__":
    unittest.main()
