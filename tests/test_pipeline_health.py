"""Tests for the daily-refresh pipeline health summary."""

import unittest
from datetime import datetime, timedelta, timezone

from core.pipeline_health import pipeline_health

NOW = datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc)


def _run(status: str, completed: datetime | None = None) -> dict:
    return {
        "status": status,
        "completed_at": (completed or NOW).isoformat(timespec="seconds"),
    }


class PipelineHealthTests(unittest.TestCase):
    def test_recent_success_is_healthy(self) -> None:
        runs = {
            "data_refresh_all": _run("success", NOW - timedelta(hours=3)),
            "data_refresh:Partner Ads": _run("success"),
            "data_refresh:SEO History": _run("skipped"),
        }
        health = pipeline_health(runs, now=NOW)
        self.assertTrue(health["ok"])
        self.assertEqual([], health["warnings"])

    def test_never_run_is_flagged(self) -> None:
        health = pipeline_health({}, now=NOW)
        self.assertFalse(health["ok"])
        self.assertIn("aldrig kørt", health["warnings"][0])

    def test_stale_refresh_is_flagged(self) -> None:
        runs = {"data_refresh_all": _run("success", NOW - timedelta(days=3))}
        health = pipeline_health(runs, now=NOW)
        self.assertFalse(health["ok"])
        self.assertIn("ikke kørt siden", health["warnings"][0])

    def test_failed_step_is_named_but_skipped_is_not(self) -> None:
        runs = {
            "data_refresh_all": _run("warning", NOW - timedelta(hours=1)),
            "data_refresh:Plausible": _run("error"),
            "data_refresh:SEO History": _run("skipped"),
            "data_refresh:Partner Ads": _run("success"),
        }
        health = pipeline_health(runs, now=NOW)
        self.assertFalse(health["ok"])
        warning = " ".join(health["warnings"])
        self.assertIn("Plausible", warning)
        self.assertNotIn("SEO History", warning)
        self.assertNotIn("Partner Ads", warning)

    def test_none_input_is_treated_as_never_run(self) -> None:
        health = pipeline_health(None, now=NOW)
        self.assertFalse(health["ok"])


if __name__ == "__main__":
    unittest.main()
