"""Sprint 42.1 tests for Plausible metrics on Website Profile."""

import importlib.util
import unittest
from datetime import date, timedelta
from pathlib import Path


PAGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "dashboard" / "pages" / "1_Website_Profile.py"
)
SPEC = importlib.util.spec_from_file_location("website_profile_page", PAGE_PATH)
PAGE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(PAGE)


class PlausibleProfileTests(unittest.TestCase):
    def test_known_daily_values_are_summed_for_each_period(self) -> None:
        today = date(2026, 7, 24)
        rows = [
            {
                "metric_date": (today - timedelta(days=offset)).isoformat(),
                "visitors": offset,
            }
            for offset in range(1, 31)
        ]

        result = PAGE.summarize_plausible_visitors(rows, today=today)

        self.assertEqual(result["yesterday"], 1)
        self.assertEqual(result["last_7_days"], sum(range(1, 8)))
        self.assertEqual(result["last_30_days"], sum(range(1, 31)))

    def test_rows_from_other_website_do_not_affect_selected_website(self) -> None:
        today = date(2026, 7, 24)
        selected = [{
            "website_id": "a.dk",
            "metric_date": "2026-07-23",
            "visitors": 12,
        }]
        other = [{
            "website_id": "b.dk",
            "metric_date": "2026-07-23",
            "visitors": 99,
        }]

        self.assertEqual(
            PAGE.summarize_plausible_visitors(selected, today=today)["yesterday"],
            12,
        )
        self.assertNotEqual(
            PAGE.summarize_plausible_visitors(other, today=today)["yesterday"],
            12,
        )

    def test_empty_rows_use_required_empty_state(self) -> None:
        self.assertIsNone(PAGE.summarize_plausible_visitors([]))
        source = PAGE_PATH.read_text(encoding="utf-8")
        self.assertIn("Ingen Plausible-data fundet.", source)

    def test_page_uses_database_only_and_no_connector(self) -> None:
        source = PAGE_PATH.read_text(encoding="utf-8").lower()
        self.assertIn("get_plausible_daily_metrics", source)
        self.assertNotIn("plausibleconnector", source)
        self.assertNotIn("requests.", source)


if __name__ == "__main__":
    unittest.main()
