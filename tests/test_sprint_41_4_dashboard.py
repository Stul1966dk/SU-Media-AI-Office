"""Sprint 41.4 regression checks for the dashboard cleanup."""

import unittest
from pathlib import Path


class DashboardPartnerAdsCleanupTests(unittest.TestCase):
    def test_old_partner_ads_table_is_not_rendered(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("def _render_sales(", source)
        self.assertNotIn("_render_sales(data)", source)

    def test_economy_and_partner_ads_import_status_remain(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
        ).read_text(encoding="utf-8")

        self.assertIn("def _render_economy(", source)
        self.assertIn('"Månedens provision"', source)
        self.assertIn('_refresh_step(result, "Partner Ads")', source)
        self.assertIn('"Nye Partner Ads-salg"', source)


if __name__ == "__main__":
    unittest.main()
