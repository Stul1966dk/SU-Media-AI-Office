"""Focused Sprint 10 tests for partial refresh classification."""

import unittest
from unittest.mock import Mock, patch

from core.refresh_status import (
    classify_step, normalize_step, result_status, status_label,
    summarize_steps,
)
from dashboard.components.startup_sync import (
    _render_status_content, run_startup_sync,
)


def step(name, status="success", **values):
    return normalize_step(name, status, values)


class PartialStatusTestCase(unittest.TestCase):
    def test_all_steps_succeed(self):
        result = summarize_steps([
            step("Partner Ads"),
            step("Search Console-dagstal"),
            step("Plausible"),
        ])
        self.assertEqual("success", result["status"])
        self.assertEqual(3, result["completed_steps"])

    def test_partial_property_failure_is_warning(self):
        values = {"properties_processed": 3, "properties_failed": 1}
        status = classify_step(values)
        result = summarize_steps([
            step("Search Console-dagstal", status, **values),
            step("Plausible"),
        ])
        self.assertEqual("warning", status)
        self.assertEqual("warning", result["status"])

    def test_one_complete_failure_with_other_success_is_warning(self):
        result = summarize_steps([
            step("Partner Ads", "error"),
            step("Plausible", "success"),
        ])
        self.assertEqual("warning", result["status"])

    def test_all_central_data_steps_fail_is_error(self):
        result = summarize_steps([
            step("Partner Ads", "error"),
            step("Search Console-dagstal", "error"),
            step("Search Console-sider og søgeord", "error"),
            step("Plausible", "error"),
            step("Systemstatus", "success"),
        ])
        self.assertEqual("error", result["status"])

    def test_skipped_is_not_counted_as_completed(self):
        result = summarize_steps([
            step("Partner Ads", "success"),
            step("Search Console-dagstal", "skipped"),
        ])
        self.assertEqual(1, result["completed_steps"])
        self.assertEqual(1, result["skipped_steps"])

    def test_telegram_failure_after_saved_sale_is_warning(self):
        self.assertEqual("warning", classify_step({
            "overall_status": "completed_with_warnings",
            "new": 1,
            "telegram_errors": 1,
        }))

    def test_one_plausible_website_failure_is_warning(self):
        self.assertEqual("warning", classify_step({
            "websites_processed": 4,
            "websites_failed": 1,
        }))

    def test_startup_sync_persists_warning_feature_run(self):
        database = Mock()
        service = Mock()
        service.refresh_all.return_value = {
            "status": "warning", "steps": [{}, {}],
            "completed_steps": 1, "warning_steps": 1,
            "failed_steps": 0, "skipped_steps": 0,
        }
        result = run_startup_sync(
            started_at="2026-07-25T10:00:00+02:00",
            database_factory=lambda: database,
            service_factory=lambda _database: service,
        )
        self.assertEqual(
            "warning", database.save_feature_run.call_args.kwargs["status"]
        )
        self.assertTrue(result["completed"])
        self.assertTrue(result["warning"])
        secret = "sk-do-not-store-this"
        failed_database = Mock()
        failed_service = Mock()
        failed_service.refresh_all.side_effect = RuntimeError(secret)
        run_startup_sync(
            started_at="2026-07-25T10:00:00+02:00",
            database_factory=lambda: failed_database,
            service_factory=lambda _database: failed_service,
        )
        saved = failed_database.save_feature_run.call_args.kwargs
        self.assertNotIn(secret, saved["error_message"])

    def test_legacy_result_is_interpreted_conservatively(self):
        self.assertEqual("warning", result_status({
            "completed_steps": 4, "failed_steps": 1,
        }))
        self.assertEqual("error", result_status({
            "completed_steps": 0, "failed_steps": 2,
        }))
        self.assertEqual("success", result_status({
            "completed_steps": 4, "failed_steps": 0,
        }))

    def test_dashboard_uses_danish_warning_text(self):
        self.assertEqual(
            "Gennemført med advarsler", status_label("warning")
        )
        state = {
            "startup_sync_enabled": True,
            "startup_sync_started": True,
            "startup_sync_completed": True,
            "startup_sync_failed": False,
            "startup_sync_warning": True,
            "startup_sync_completed_at": "2026-07-25T10:01:00+02:00",
        }
        with (
            patch("dashboard.components.startup_sync.st.warning") as warning,
            patch("dashboard.components.startup_sync.st.caption"),
        ):
            _render_status_content(state)
        warning.assert_called_once_with(
            "Synkronisering ved app-start er gennemført med advarsler"
        )


if __name__ == "__main__":
    unittest.main()
