"""Sprint 5 regression tests for incremental Partner Ads synchronization."""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from core.data_refresh_service import DataRefreshService
from core.database import Database
from core.partner_ads_import import execute_partner_ads_check


def sale(kombiid: str, sale_date: str, **changes: str) -> dict[str, str]:
    values = {
        "kombiid": kombiid,
        "programid": "p1",
        "program": "Program",
        "dato": sale_date,
        "tidspunkt": "12:00",
        "ordrenr": f"order-{kombiid}",
        "omsaetning": "100.00",
        "provision": "10.00",
        "url": "https://example.dk",
        "valuta": "DKK",
        "status": "pending",
        "godkendelsesstatus": "pending",
    }
    values.update(changes)
    return values


class PartnerAdsSprint5Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        self.partner = Mock()
        self.telegram = Mock()

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def run_import(
        self, sales: list[dict[str, str]], *, force: bool = False
    ) -> dict:
        self.partner.fetch_sales.return_value = ("sanitized", sales)
        return execute_partner_ads_check(
            self.database,
            force_full_refresh=force,
            today=date(2026, 8, 3),
            partner_ads=self.partner,
            telegram=self.telegram,
        )

    def seed(self, item: dict[str, str]) -> None:
        self.database.initialize_sales_baseline([item])

    def test_first_and_forced_import_use_current_month(self) -> None:
        result = self.run_import([sale("first", "02-08-2026")])
        self.assertEqual("full", result["import_mode"])
        self.assertEqual("2026-08-01", result["start_date"])
        self.assertEqual("2026-08-03", result["end_date"])
        self.assertEqual(1, result["new"])
        self.assertEqual(1, result["telegram_skipped"])
        self.telegram.send_sale.assert_not_called()

        forced = self.run_import([], force=True)
        self.assertEqual("full", forced["import_mode"])
        self.assertEqual("2026-08-01", forced["start_date"])

    def test_incremental_overlap_crosses_month_boundary(self) -> None:
        self.seed(sale("known", "01-08-2026"))
        result = self.run_import([])
        self.assertEqual("incremental", result["import_mode"])
        self.assertEqual("2026-07-30", result["start_date"])
        self.partner.fetch_sales.assert_called_once_with(
            start_date=date(2026, 7, 30), end_date=date(2026, 8, 3)
        )

    def test_normal_incremental_import_creates_one_new_sale(self) -> None:
        self.seed(sale("known", "02-08-2026"))
        result = self.run_import([
            sale("known", "02-08-2026"),
            sale("new-incremental", "03-08-2026"),
        ])
        self.assertEqual("incremental", result["import_mode"])
        self.assertEqual("2026-07-31", result["start_date"])
        self.assertEqual(2, result["fetched"])
        self.assertEqual(1, result["new"])
        self.assertEqual(1, result["updated"])
        self.assertEqual(1, result["telegram_sent"])

    def test_repeat_is_unchanged_without_duplicate_or_second_telegram(self) -> None:
        self.database.initialize_sales_baseline([])
        item = sale("new", "03-08-2026")
        first = self.run_import([item])
        second = self.run_import([item])
        self.assertEqual(1, first["new"])
        self.assertEqual(1, first["telegram_sent"])
        self.assertEqual(0, second["new"])
        self.assertEqual(1, second["unchanged"])
        self.assertEqual(1, second["duplicates"])
        self.assertEqual(1, second["telegram_skipped"])
        self.telegram.send_sale.assert_called_once()

    def test_existing_sale_is_updated_without_notification(self) -> None:
        self.seed(sale("known", "02-08-2026"))
        result = self.run_import([
            sale(
                "known", "02-08-2026", provision="12.50",
                status="approved", godkendelsesstatus="approved",
            )
        ])
        self.assertEqual(1, result["updated"])
        self.assertEqual(0, result["new"])
        self.assertEqual(1, result["telegram_skipped"])
        self.telegram.send_sale.assert_not_called()
        stored = self.database.get_sales("02-08-2026")[0]
        self.assertEqual(12.5, float(stored["provision"]))

    def test_duplicate_api_rows_are_ignored(self) -> None:
        self.database.initialize_sales_baseline([])
        item = sale("same", "03-08-2026")
        result = self.run_import([item, item])
        self.assertEqual(2, result["fetched"])
        self.assertEqual(1, result["new"])
        self.assertEqual(1, result["duplicates"])
        self.telegram.send_sale.assert_called_once()

    def test_telegram_failure_is_warning_and_sale_remains_saved(self) -> None:
        self.database.initialize_sales_baseline([])
        self.telegram.send_sale.side_effect = RuntimeError("Telegram nede")
        item = sale("failed-message", "03-08-2026")
        result = self.run_import([item])
        self.assertEqual("completed_with_warnings", result["overall_status"])
        self.assertEqual(1, result["new"])
        self.assertEqual(1, result["telegram_errors"])
        self.assertTrue(self.database.sale_exists("failed-message"))
        self.assertEqual(
            "failed",
            self.database.get_partner_ads_notification_status("failed-message"),
        )
        self.run_import([item])
        self.telegram.send_sale.assert_called_once()

    def test_api_failure_is_recorded_and_raised(self) -> None:
        self.database.initialize_sales_baseline([])
        self.partner.fetch_sales.side_effect = RuntimeError("API nede")
        with self.assertRaisesRegex(RuntimeError, "API nede"):
            execute_partner_ads_check(
                self.database,
                today=date(2026, 8, 3),
                partner_ads=self.partner,
                telegram=self.telegram,
            )
        run = self.database.get_feature_runs()["partner_ads_import"]
        self.assertEqual("error", run["status"])

    def test_data_refresh_uses_incremental_global_partner_ads(self) -> None:
        service = object.__new__(DataRefreshService)
        service.database = Mock()
        service.partner_refresh = Mock(return_value={"overall_status": "completed"})
        service.refresh_partner_ads()
        service.partner_refresh.assert_called_once_with(
            service.database, force_full_refresh=False
        )

    def test_data_refresh_distinguishes_warning_and_skipped(self) -> None:
        notify = Mock()
        steps: list[dict] = []
        warning = DataRefreshService._run(
            "Partner Ads",
            lambda: {"overall_status": "completed_with_warnings"},
            notify,
            steps,
        )
        skipped = DataRefreshService._run(
            "Partner Ads",
            lambda: {"overall_status": "skipped", "skip_reason": "Mangler"},
            notify,
            steps,
        )
        self.assertEqual("warning", warning["status"])
        self.assertEqual("skipped", skipped["status"])

    def test_continuous_monitor_uses_shared_incremental_import(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "src" / "main.py"
        ).read_text(encoding="utf-8")
        self.assertIn("execute_partner_ads_check(", source)
        self.assertIn("force_full_refresh=False", source)


if __name__ == "__main__":
    unittest.main()
