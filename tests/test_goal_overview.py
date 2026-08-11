"""Tests for the deterministic revenue-versus-goal overview."""

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from core.database import Database
from core.goal_overview import build_goal_overview


TODAY = date(2026, 8, 15)


def _rec(
    dato: str,
    provision: str,
    url: str,
    valuta: str = "DKK",
    uid: str = "",
    uid2: str = "",
) -> dict:
    return {
        "dato": dato,
        "provision": provision,
        "url": url,
        "valuta": valuta,
        "uid": uid,
        "uid2": uid2,
    }


class BuildGoalOverviewTests(unittest.TestCase):
    def test_empty_records_is_no_data(self) -> None:
        overview = build_goal_overview([], today=TODAY)
        self.assertEqual("no_data", overview.status)
        self.assertEqual(Decimal("0"), overview.rolling_average)
        self.assertEqual(Decimal("0"), overview.current_month.total)
        self.assertEqual([], overview.by_website)

    def test_current_month_and_monthly_aggregation(self) -> None:
        records = [
            _rec("18-7-2026", "300", "https://romaskinen.dk/a/"),
            _rec("2-8-2026", "100", "https://romaskinen.dk/b/"),
            _rec("14-8-2026", "50", "https://baalfad.dk/c/"),
        ]
        overview = build_goal_overview(records, today=TODAY)
        self.assertEqual(Decimal("150"), overview.current_month.total)
        self.assertEqual(2, overview.current_month.sales)
        july = next(m for m in overview.history if (m.year, m.month) == (2026, 7))
        self.assertEqual(Decimal("300"), july.total)

    def test_rolling_average_excludes_current_partial_month(self) -> None:
        records = [
            _rec("10-7-2026", "5000", "https://romaskinen.dk/a/"),
            _rec("20-7-2026", "5000", "https://romaskinen.dk/b/"),
            _rec("3-8-2026", "99999", "https://romaskinen.dk/c/"),
        ]
        overview = build_goal_overview(records, today=TODAY)
        # Only July is a completed month with data; August must be excluded.
        self.assertEqual(1, overview.months_with_data)
        self.assertEqual(Decimal("10000"), overview.rolling_average)
        self.assertEqual(Decimal("99999"), overview.current_month.total)

    def test_non_dkk_sales_are_excluded(self) -> None:
        records = [
            _rec("10-7-2026", "1000", "https://romaskinen.dk/a/"),
            _rec("11-7-2026", "9999", "https://romaskinen.dk/b/", valuta="EUR"),
        ]
        overview = build_goal_overview(records, today=TODAY)
        self.assertEqual(Decimal("1000"), overview.rolling_average)
        self.assertEqual(1, len(overview.by_website))

    def test_malformed_dates_are_skipped(self) -> None:
        records = [
            _rec("ugyldig", "500", "https://romaskinen.dk/a/"),
            _rec("10-7-2026", "1000", "https://romaskinen.dk/b/"),
        ]
        overview = build_goal_overview(records, today=TODAY)
        self.assertEqual(Decimal("1000"), overview.rolling_average)

    def test_by_website_groups_by_domain_with_shares(self) -> None:
        records = [
            _rec("10-7-2026", "300", "https://www.romaskinen.dk/a/"),
            _rec("11-7-2026", "100", "https://romaskinen.dk/b/"),
            _rec("12-7-2026", "100", "https://baalfad.dk/c/"),
        ]
        overview = build_goal_overview(records, today=TODAY)
        sites = {item.website: item for item in overview.by_website}
        self.assertEqual(Decimal("400"), sites["romaskinen.dk"].total)
        self.assertEqual(2, sites["romaskinen.dk"].sales)
        self.assertEqual("romaskinen.dk", overview.by_website[0].website)
        self.assertAlmostEqual(
            1.0, sum(item.share for item in overview.by_website), places=6
        )

    def test_by_page_and_by_product(self) -> None:
        records = [
            _rec("10-7-2026", "300", "https://romaskinen.dk/a/",
                 uid="/side-a/", uid2="Produkt X"),
            _rec("11-7-2026", "100", "https://romaskinen.dk/a/",
                 uid="/side-a/", uid2="Produkt X"),
            _rec("12-7-2026", "50", "https://baalfad.dk/b/",
                 uid="/side-b/", uid2="Produkt Y"),
            # No page or product attribution: excluded from both breakdowns.
            _rec("13-7-2026", "25", "https://baalfad.dk/"),
        ]
        overview = build_goal_overview(records, today=TODAY)

        pages = {item.page: item for item in overview.by_page}
        self.assertEqual(Decimal("400"), pages["romaskinen.dk/side-a/"].total)
        self.assertEqual(2, pages["romaskinen.dk/side-a/"].sales)
        self.assertEqual("romaskinen.dk/side-a/", overview.by_page[0].page)
        self.assertEqual(2, len(overview.by_page))

        products = {item.product: item for item in overview.by_product}
        self.assertEqual(Decimal("400"), products["Produkt X"].total)
        self.assertEqual("Produkt X", overview.by_product[0].product)
        self.assertEqual(2, len(overview.by_product))

    def test_page_and_product_junk_is_filtered(self) -> None:
        records = [
            # Unfilled [UID] template and base64 product blob -> excluded.
            _rec("10-7-2026", "100", "https://motionsmaskinen.dk/",
                 uid="[UID]", uid2="eyJ0eXBlIjoiZmVlZCJ9"),
            _rec("11-7-2026", "200", "https://romaskinen.dk/",
                 uid="/god-side/", uid2="Odin-R900"),
        ]
        overview = build_goal_overview(records, today=TODAY)

        self.assertEqual(1, len(overview.by_page))
        self.assertEqual("romaskinen.dk/god-side/", overview.by_page[0].page)
        self.assertEqual(1, len(overview.by_product))
        self.assertEqual("Odin-R900", overview.by_product[0].product)

    def test_status_bands(self) -> None:
        low, high = Decimal("8000"), Decimal("12000")
        cases = {
            "5000": "under",
            "10000": "in_band",
            "15000": "over",
        }
        for provision, expected in cases.items():
            overview = build_goal_overview(
                [_rec("10-7-2026", provision, "https://romaskinen.dk/a/")],
                today=TODAY,
                target_low=low,
                target_high=high,
            )
            self.assertEqual(expected, overview.status, provision)


class CommissionRecordsDatabaseTests(unittest.TestCase):
    def test_get_commission_records_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "test.db")
            database.initialize()
            try:
                database.upsert_partner_ads_sale({
                    "kombiid": "K1",
                    "programid": "P1",
                    "program": "Prog",
                    "dato": "5-8-2026",
                    "tidspunkt": "12:00:00",
                    "ordrenr": "O1",
                    "omsaetning": "100",
                    "provision": "50",
                    "url": "https://romaskinen.dk/side/",
                    "valuta": "DKK",
                    "uid": "/demo-romaskine/",
                    "uid2": "Odin-R900",
                })
                records = database.get_commission_records()
            finally:
                database.close()

        self.assertEqual(1, len(records))
        self.assertEqual("5-8-2026", records[0]["dato"])
        self.assertEqual("https://romaskinen.dk/side/", records[0]["url"])
        self.assertEqual("DKK", records[0]["valuta"])
        self.assertEqual("/demo-romaskine/", records[0]["uid"])
        self.assertEqual("Odin-R900", records[0]["uid2"])


if __name__ == "__main__":
    unittest.main()
