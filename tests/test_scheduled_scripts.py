"""Tests for the headless Task Scheduler entry scripts."""

import importlib.util
import logging
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


monitor_sales = _load("monitor_sales_script", "monitor_sales.py")
daily_refresh = _load("daily_refresh_script", "daily_refresh.py")
reconnect_sc = _load(
    "reconnect_search_console_script", "reconnect_search_console.py"
)


def _silent_logger() -> logging.Logger:
    logger = logging.getLogger("test.scheduled")
    logger.handlers = [logging.NullHandler()]
    logger.setLevel(logging.CRITICAL)
    return logger


class MonitorSalesRunTests(unittest.TestCase):
    def test_success_returns_zero_and_calls_check(self) -> None:
        check = Mock(return_value={"fetched": 3, "new": 1, "telegram_sent": 1})
        database = Mock()

        code = monitor_sales.run(database, check=check, logger=_silent_logger())

        self.assertEqual(0, code)
        check.assert_called_once_with(database)

    def test_exception_returns_one(self) -> None:
        check = Mock(side_effect=RuntimeError("boom"))

        code = monitor_sales.run(Mock(), check=check, logger=_silent_logger())

        self.assertEqual(1, code)


class ReconnectSearchConsoleRunTests(unittest.TestCase):
    def test_success_connects_and_returns_zero(self) -> None:
        integration = Mock()
        integration.connect.return_value = {"account": "owner@example.com"}

        code = reconnect_sc.run(
            Mock(), integration_factory=lambda _db: integration
        )

        self.assertEqual(0, code)
        integration.connect.assert_called_once_with()

    def test_failed_login_returns_one(self) -> None:
        integration = Mock()
        integration.connect.side_effect = RuntimeError("browseren blev lukket")

        code = reconnect_sc.run(
            Mock(), integration_factory=lambda _db: integration
        )

        self.assertEqual(1, code)


class DailyRefreshRunTests(unittest.TestCase):
    def test_success_returns_zero_and_refreshes(self) -> None:
        service = Mock()
        service.refresh_all.return_value = {
            "steps": [
                {"step": "Partner Ads", "status": "success"},
                {"step": "Plausible", "status": "skipped"},
            ]
        }
        factory = Mock(return_value=service)
        database = Mock()

        code = daily_refresh.run(
            database, service_factory=factory, logger=_silent_logger()
        )

        self.assertEqual(0, code)
        factory.assert_called_once_with(database)
        service.refresh_all.assert_called_once_with(website_ids=None)

    def test_step_error_still_returns_zero(self) -> None:
        service = Mock()
        service.refresh_all.return_value = {
            "steps": [{"step": "Search Console-dagstal", "status": "error"}]
        }
        factory = Mock(return_value=service)

        code = daily_refresh.run(
            Mock(), service_factory=factory, logger=_silent_logger()
        )

        self.assertEqual(0, code)

    def test_refresh_exception_returns_one(self) -> None:
        factory = Mock(side_effect=RuntimeError("boom"))

        code = daily_refresh.run(
            Mock(), service_factory=factory, logger=_silent_logger()
        )

        self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
