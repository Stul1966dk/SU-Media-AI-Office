"""Tests for notification-free historical Partner Ads backfill."""

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from core.database import Database
from core.partner_ads_backfill import backfill_sales


def _sale(kombiid: str, url: str = "https://romaskinen.dk/a/") -> dict:
    return {
        "kombiid": kombiid,
        "programid": "P1",
        "program": "Prog",
        "dato": "5-3-2026",
        "tidspunkt": "12:00:00",
        "ordrenr": f"O-{kombiid}",
        "omsaetning": "100",
        "provision": "50",
        "url": url,
        "valuta": "DKK",
    }


class FakePartnerAds:
    def __init__(self, sales: list[dict]) -> None:
        self.sales = sales
        self.calls: list[tuple] = []

    def fetch_sales(self, *, start_date, end_date):
        self.calls.append((start_date, end_date))
        return "url", list(self.sales)


class BackfillSalesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.database = Database(Path(self._tmp.name) / "test.db")
        self.database.initialize()

    def tearDown(self) -> None:
        self.database.close()
        self._tmp.cleanup()

    def test_stores_sales_and_marks_skipped(self) -> None:
        partner = FakePartnerAds([_sale("A"), _sale("B", "https://baalfad.dk/x/")])
        result = backfill_sales(
            self.database, partner,
            start_date=date(2022, 1, 1), end_date=date(2026, 8, 1),
        )
        self.assertEqual(2, result["created"])
        self.assertEqual(2, len(self.database.get_commission_records()))
        # Marked as already handled so the live monitor never notifies them.
        self.assertEqual(
            "skipped",
            self.database.get_partner_ads_notification_status("A"),
        )
        self.assertEqual(
            "skipped",
            self.database.get_partner_ads_notification_status("B"),
        )

    def test_is_idempotent(self) -> None:
        partner = FakePartnerAds([_sale("A"), _sale("B")])
        backfill_sales(
            self.database, partner,
            start_date=date(2022, 1, 1), end_date=date(2026, 8, 1),
        )
        second = backfill_sales(
            self.database, partner,
            start_date=date(2022, 1, 1), end_date=date(2026, 8, 1),
        )
        self.assertEqual(0, second["created"])
        self.assertEqual(2, second["unchanged"])
        self.assertEqual(2, len(self.database.get_commission_records()))

    def test_passes_the_requested_period(self) -> None:
        partner = FakePartnerAds([])
        backfill_sales(
            self.database, partner,
            start_date=date(2023, 2, 1), end_date=date(2023, 3, 1),
        )
        self.assertEqual([(date(2023, 2, 1), date(2023, 3, 1))], partner.calls)

    def test_deduplicates_repeated_kombiid(self) -> None:
        partner = FakePartnerAds([_sale("A"), _sale("A")])
        result = backfill_sales(
            self.database, partner,
            start_date=date(2022, 1, 1), end_date=date(2026, 8, 1),
        )
        self.assertEqual(1, result["created"])
        self.assertEqual(1, result["duplicates"])
        self.assertEqual(1, len(self.database.get_commission_records()))


if __name__ == "__main__":
    unittest.main()
