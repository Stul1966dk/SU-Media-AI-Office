"""Tests for once-per-session synchronization at Streamlit startup."""

import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock

from core.database import Database
from dashboard.components.startup_sync import (
    SESSION_KEYS,
    SETTING_NAME,
    ensure_startup_sync,
    run_startup_sync,
)


class StartupSyncTests(unittest.TestCase):
    def test_setting_is_persisted_in_app_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "test.db")
            database.initialize()
            self.assertFalse(database.get_app_setting(SETTING_NAME))
            database.set_app_setting(SETTING_NAME, True)
            self.assertTrue(database.get_app_setting(SETTING_NAME))
            database.close()

    def test_disabled_setting_is_checked_once_without_starting(self) -> None:
        database = Mock()
        database.get_app_setting.return_value = False
        factory = Mock(return_value=database)
        executor = Mock()
        state = {}
        ensure_startup_sync(
            state=state, database_factory=factory, executor=executor
        )
        ensure_startup_sync(
            state=state, database_factory=factory, executor=executor
        )
        self.assertTrue(state[SESSION_KEYS["checked"]])
        self.assertFalse(state[SESSION_KEYS["started"]])
        factory.assert_called_once()
        executor.submit.assert_not_called()

    def test_enabled_setting_submits_only_once_for_all_websites(self) -> None:
        database = Mock()
        database.get_app_setting.return_value = True
        executor = Mock()
        executor.submit.return_value = Future()
        state = {}
        ensure_startup_sync(
            state=state,
            database_factory=Mock(return_value=database),
            executor=executor,
        )
        ensure_startup_sync(
            state=state,
            database_factory=Mock(return_value=database),
            executor=executor,
        )
        self.assertTrue(state[SESSION_KEYS["started"]])
        self.assertIsNotNone(state[SESSION_KEYS["started_at"]])
        executor.submit.assert_called_once()

    def test_worker_uses_all_active_scope_and_distinct_feature_name(
        self,
    ) -> None:
        database = Mock()
        service = Mock()
        service.refresh_all.return_value = {
            "steps": [{"step": "Website Registry"}],
            "completed_steps": 1,
            "failed_steps": 0,
            "skipped_steps": 0,
        }
        result = run_startup_sync(
            started_at="2026-07-24T10:00:00+02:00",
            database_factory=Mock(return_value=database),
            service_factory=Mock(return_value=service),
        )
        service.refresh_all.assert_called_once_with(website_ids=None)
        self.assertTrue(result["completed"])
        self.assertFalse(result["failed"])
        self.assertEqual(
            "data_refresh_app_start",
            database.save_feature_run.call_args.kwargs["feature_name"],
        )
        database.close.assert_called_once()

    def test_partial_refresh_is_recorded_as_failed(self) -> None:
        database = Mock()
        service = Mock()
        service.refresh_all.return_value = {
            "steps": [{"step": "Plausible", "status": "error"}],
            "completed_steps": 0,
            "failed_steps": 1,
            "skipped_steps": 0,
        }
        result = run_startup_sync(
            started_at="2026-07-24T10:00:00+02:00",
            database_factory=Mock(return_value=database),
            service_factory=Mock(return_value=service),
        )
        self.assertTrue(result["failed"])
        self.assertEqual(
            "error", database.save_feature_run.call_args.kwargs["status"]
        )


if __name__ == "__main__":
    unittest.main()
