"""Tests for once-per-session synchronization at Streamlit startup."""

import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock, patch

from core.database import Database
from dashboard.components.startup_sync import (
    SESSION_KEYS,
    SETTING_NAME,
    POLL_INTERVAL_SECONDS,
    _is_running,
    _poll_future,
    _render_polling_status,
    _render_status_content,
    ensure_startup_sync,
    run_startup_sync,
)


class StartupSyncTests(unittest.TestCase):
    def test_polling_uses_short_interval(self) -> None:
        self.assertEqual(3, POLL_INTERVAL_SECONDS)

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

    def test_status_is_running_before_future_completes(self) -> None:
        state = {
            SESSION_KEYS["enabled"]: True,
            SESSION_KEYS["started"]: True,
            SESSION_KEYS["completed"]: False,
            SESSION_KEYS["failed"]: False,
            SESSION_KEYS["future"]: Future(),
            SESSION_KEYS["started_at"]: "2026-07-25T07:03:47+02:00",
        }
        self.assertFalse(_poll_future(state))
        self.assertTrue(_is_running(state))
        with (
            patch(
                "dashboard.components.startup_sync.st.info"
            ) as info,
            patch("dashboard.components.startup_sync.st.caption"),
        ):
            _render_status_content(state)
        info.assert_called_once_with(
            "Synkronisering ved app-start kører"
        )

    def test_polling_fragment_requests_one_full_rerun_on_completion(
        self,
    ) -> None:
        with (
            patch(
                "dashboard.components.startup_sync._poll_future",
                return_value=True,
            ),
            patch(
                "dashboard.components.startup_sync._render_status_content"
            ),
            patch(
                "dashboard.components.startup_sync.st.rerun"
            ) as rerun,
        ):
            _render_polling_status.__wrapped__()
        rerun.assert_called_once_with()

    def test_status_changes_to_completed_and_polling_stops(self) -> None:
        future = Future()
        future.set_result({
            "completed": True,
            "failed": False,
            "completed_at": "2026-07-25T07:05:52+02:00",
            "error_type": None,
        })
        state = {
            SESSION_KEYS["enabled"]: True,
            SESSION_KEYS["started"]: True,
            SESSION_KEYS["completed"]: False,
            SESSION_KEYS["failed"]: False,
            SESSION_KEYS["future"]: future,
            "data_refresh_result": {"started_at": "older-manual-run"},
        }
        self.assertTrue(_poll_future(state))
        self.assertFalse(_is_running(state))
        self.assertNotIn(SESSION_KEYS["future"], state)
        self.assertNotIn("data_refresh_result", state)
        self.assertFalse(_poll_future(state))
        with (
            patch(
                "dashboard.components.startup_sync.st.success"
            ) as success,
            patch("dashboard.components.startup_sync.st.caption"),
        ):
            _render_status_content(state)
        success.assert_called_once_with(
            "Synkronisering ved app-start er gennemført"
        )

    def test_status_changes_to_failed_when_future_raises(self) -> None:
        future = Future()
        future.set_exception(RuntimeError("refresh failed"))
        state = {
            SESSION_KEYS["enabled"]: True,
            SESSION_KEYS["started"]: True,
            SESSION_KEYS["completed"]: False,
            SESSION_KEYS["failed"]: False,
            SESSION_KEYS["future"]: future,
        }
        self.assertTrue(_poll_future(state))
        self.assertFalse(_is_running(state))
        self.assertNotIn(SESSION_KEYS["future"], state)
        self.assertEqual("RuntimeError", state[SESSION_KEYS["error_type"]])
        with (
            patch(
                "dashboard.components.startup_sync.st.error"
            ) as error,
            patch("dashboard.components.startup_sync.st.caption"),
        ):
            _render_status_content(state)
        error.assert_called_once_with(
            "Synkronisering ved app-start fejlede"
        )

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
