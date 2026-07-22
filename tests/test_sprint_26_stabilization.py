"""Sprint 26 stabilization regression tests."""

import tempfile
import unittest
import logging
import os
import re
from pathlib import Path
from unittest.mock import Mock, patch
from streamlit.testing.v1 import AppTest

from core.database import Database
from core.partner_ads_import import execute_partner_ads_check
from dashboard.components.formatting import (
    format_currency, format_date, format_datetime, format_time,
)
from dashboard.components.feature_status import build_feature_status
from src.main import run_check


ROOT = Path(__file__).resolve().parents[1]


class Sprint26Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    @patch("core.partner_ads_import.load_config")
    @patch("core.partner_ads_import.run_check", return_value=(8, 2))
    def test_partner_ads_dashboard_import_runs_one_check(
        self, run_check: Mock, load_config: Mock
    ) -> None:
        load_config.return_value = Mock(
            partner_ads_base_url="https://example.invalid",
            partner_ads_key="secret",
            telegram_bot_token="secret",
            telegram_chat_id="1",
        )
        result = execute_partner_ads_check(self.database)
        self.assertEqual(8, result["fetched"])
        self.assertEqual(2, result["new"])
        self.assertEqual(6, result["duplicates"])
        self.assertEqual(2, result["telegram_sent"])
        self.assertTrue(result["completed_at"])
        run_check.assert_called_once()
        stored = self.database.get_feature_runs()["partner_ads_import"]
        self.assertEqual("success", stored["status"])
        self.assertEqual(8, stored["records_processed"])
        self.assertEqual(2, stored["records_created"])

    def test_run_check_new_sale_is_sent_and_saved_once(self) -> None:
        sale = {
            "kombiid": "new-1", "dato": "19-07-2026",
            "provision": "10.00",
        }
        partner = Mock()
        partner.fetch_sales.return_value = ("secret-url", [sale])
        telegram = Mock()
        database = Mock()
        database.is_baseline_initialized.return_value = True
        database.sale_exists.return_value = False
        database.get_today_commission.return_value = 0
        self.assertEqual(
            (1, 1), run_check(partner, telegram, database, logging.getLogger())
        )
        telegram.send_sale.assert_called_once()
        database.save_sale.assert_called_once_with(sale)

    def test_run_check_no_new_sales(self) -> None:
        partner = Mock()
        partner.fetch_sales.return_value = ("secret-url", [])
        database = Mock()
        database.is_baseline_initialized.return_value = True
        telegram = Mock()
        self.assertEqual(
            (0, 0), run_check(partner, telegram, database, logging.getLogger())
        )
        telegram.send_sale.assert_not_called()
        database.save_sale.assert_not_called()

    def test_run_check_duplicate_is_not_sent_again(self) -> None:
        sale = {"kombiid": "known-1"}
        partner = Mock()
        partner.fetch_sales.return_value = ("secret-url", [sale, sale])
        database = Mock()
        database.is_baseline_initialized.return_value = True
        database.sale_exists.return_value = True
        telegram = Mock()
        self.assertEqual(
            (2, 0), run_check(partner, telegram, database, logging.getLogger())
        )
        telegram.send_sale.assert_not_called()
        database.save_sale.assert_not_called()

    @patch("core.partner_ads_import.load_config")
    @patch(
        "core.partner_ads_import.run_check",
        side_effect=RuntimeError("Partner Ads svarer ikke"),
    )
    def test_partner_ads_failure_is_recorded_and_raised(
        self, _run_check: Mock, load_config: Mock
    ) -> None:
        load_config.return_value = Mock(
            partner_ads_base_url="https://example.invalid",
            partner_ads_key="secret", telegram_bot_token="secret",
            telegram_chat_id="1",
        )
        with self.assertRaisesRegex(RuntimeError, "svarer ikke"):
            execute_partner_ads_check(self.database)
        self.assertEqual(
            "error",
            self.database.get_feature_runs()["partner_ads_import"]["status"],
        )

    @patch("core.partner_ads_import.load_config")
    @patch("core.partner_ads_import.run_check", return_value=(4, 1))
    def test_status_registration_failure_does_not_fail_import(
        self, _run_check: Mock, load_config: Mock
    ) -> None:
        load_config.return_value = Mock(
            partner_ads_base_url="https://example.invalid",
            partner_ads_key="secret", telegram_bot_token="secret",
            telegram_chat_id="1",
        )
        database = Mock()
        database.save_feature_run.side_effect = AttributeError(
            "save_feature_run mangler"
        )
        result = execute_partner_ads_check(database)
        self.assertEqual(4, result["fetched"])
        self.assertEqual(1, result["new"])

    def test_danish_dashboard_formatting(self) -> None:
        value = "2026-07-19T04:46:31+02:00"
        self.assertEqual("19.07.2026", format_date(value))
        self.assertEqual("04:46", format_time(value))
        self.assertEqual("19.07.2026 kl. 04:46", format_datetime(value))
        self.assertEqual("2.718,40 kr.", format_currency("2718.40"))
        self.assertEqual("307,18 kr.", format_currency("307.18"))

    def test_dashboard_latest_analysis_never_displays_raw_iso(self) -> None:
        self.database.save_ai_analysis({
            "website_id": None, "project_id": None, "task_id": None,
            "analysis_type": "website", "summary": "Test",
            "problem": "Test", "root_cause": "Test",
            "recommended_action": "Test", "priority": "low",
            "confidence": 50, "expected_effect": "Test",
            "reasoning": [], "required_agents": [], "suggested_tasks": [],
            "model": "test", "prompt_tokens": 0, "completion_tokens": 0,
            "latency_ms": 0, "created_at": "2026-07-19T08:12:12+02:00",
        })
        previous = os.environ.get("SU_MEDIA_DATABASE_PATH")
        os.environ["SU_MEDIA_DATABASE_PATH"] = str(self.database.path)
        try:
            app = AppTest.from_file(
                str(ROOT / "dashboard" / "app.py"), default_timeout=20
            ).run()
        finally:
            if previous is None:
                os.environ.pop("SU_MEDIA_DATABASE_PATH", None)
            else:
                os.environ["SU_MEDIA_DATABASE_PATH"] = previous
        self.assertFalse(app.exception)
        latest = next(
            item for item in app.metric if item.label == "Seneste analyse"
        )
        self.assertEqual("19.07.2026 kl. 08:12", latest.value)
        visible = " ".join(
            str(getattr(item, "value", ""))
            for collection in (app.metric, app.caption, app.markdown)
            for item in collection
        )
        self.assertIsNone(
            re.search(r"2026-07-19T|T08:12:12|\\+02:00", visible)
        )

    def test_ai_analyst_uses_timestamp_fallback(self) -> None:
        source = (
            ROOT / "dashboard" / "pages" / "6_AI_Analyst.py"
        ).read_text("utf-8")
        self.assertIn('selected.get("created_at")', source)
        self.assertNotIn("selected['created_at']", source)

    def test_search_console_dimensions_are_available(self) -> None:
        source = (
            ROOT / "dashboard" / "pages" / "9_SEO.py"
        ).read_text("utf-8")
        self.assertIn("Top sider", source)
        self.assertIn("Top søgeord", source)
        self.assertIn("Største klikfald", source)
        self.assertIn("page_query", source)

    def test_central_status_includes_dynamic_and_unimplemented_features(self) -> None:
        rows = build_feature_status(self.database, ROOT)
        statuses = {row["Funktion"]: row["Status"] for row in rows}
        self.assertEqual("Ikke implementeret", statuses["Automation Engine"])
        self.assertEqual("Ikke implementeret", statuses["Supabase"])
        self.assertEqual("Mangler data", statuses["Website Registry"])
        self.assertIn("AI Analyst", statuses)
        self.assertIn("Partner Ads import", statuses)


if __name__ == "__main__":
    unittest.main()
