"""Sprint 41.1 tests for transparent monthly commission."""

import unittest
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from src.partner_ads import PartnerAdsService


class MonthlyCommissionTests(unittest.TestCase):
    def test_partner_ads_default_period_covers_current_month(self) -> None:
        service = PartnerAdsService(
            "https://example.test/sales", "secret"
        )

        query = parse_qs(urlsplit(
            service.build_url(today=date(2026, 7, 23))
        ).query)

        self.assertEqual(["26-07-01"], query["fra"])
        self.assertEqual(["26-07-23"], query["til"])

    def test_dashboard_contains_read_only_calculation_expander(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
        ).read_text(encoding="utf-8")

        for label in (
            'st.expander("Vis beregning")',
            '"Dato"',
            '"Website"',
            '"Ordre/reference"',
            '"Provision i DKK"',
            '"**Antal salg:**',
            '"**Samlet provision:**',
        ):
            self.assertIn(label, source)
        self.assertNotIn("save_sale(", source)


if __name__ == "__main__":
    unittest.main()
