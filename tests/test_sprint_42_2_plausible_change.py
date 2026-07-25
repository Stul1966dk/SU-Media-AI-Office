"""Sprint 42.2 tests for non-overlapping Plausible comparisons."""

import importlib.util
import unittest
from datetime import date, timedelta
from pathlib import Path


PAGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "dashboard" / "pages" / "1_Website_Profile.py"
)
SPEC = importlib.util.spec_from_file_location("website_profile_42_2", PAGE_PATH)
PAGE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(PAGE)


def rows_for_periods(
    *,
    today: date,
    current_days: int,
    previous_days: int,
    visitors_current: int,
    visitors_previous: int,
) -> list[dict[str, object]]:
    rows = []
    for offset in range(1, current_days + 1):
        rows.append({
            "metric_date": (today - timedelta(days=offset)).isoformat(),
            "visitors": visitors_current,
        })
    for offset in range(current_days + 1, current_days + previous_days + 1):
        rows.append({
            "metric_date": (today - timedelta(days=offset)).isoformat(),
            "visitors": visitors_previous,
        })
    return rows


class PlausibleChangeTests(unittest.TestCase):
    def test_known_dataset_returns_correct_change(self) -> None:
        today = date(2026, 7, 24)
        rows = rows_for_periods(
            today=today,
            current_days=30,
            previous_days=30,
            visitors_current=12,
            visitors_previous=10,
        )
        result = PAGE.summarize_plausible_visitors(rows, today=today)

        self.assertAlmostEqual(result["change_7_days"], 0.0)
        self.assertAlmostEqual(result["change_30_days"], 20.0)
        self.assertEqual(PAGE.format_plausible_change(20), "+20,0 %")

    def test_periods_are_adjacent_and_do_not_overlap(self) -> None:
        today = date(2026, 7, 24)
        rows = rows_for_periods(
            today=today,
            current_days=7,
            previous_days=7,
            visitors_current=20,
            visitors_previous=10,
        )
        result = PAGE.summarize_plausible_visitors(rows, today=today)

        self.assertEqual(result["last_7_days"], 140)
        self.assertAlmostEqual(result["change_7_days"], 100.0)

    def test_incomplete_comparison_period_returns_not_enough_data(self) -> None:
        today = date(2026, 7, 24)
        rows = rows_for_periods(
            today=today,
            current_days=7,
            previous_days=6,
            visitors_current=10,
            visitors_previous=10,
        )
        result = PAGE.summarize_plausible_visitors(rows, today=today)

        self.assertIsNone(result["change_7_days"])
        self.assertEqual(
            PAGE.format_plausible_change(result["change_7_days"]),
            "Ikke nok data",
        )

    def test_zero_change_uses_neutral_text(self) -> None:
        self.assertEqual(
            PAGE.format_plausible_change(0),
            "0,0 % · Uændret",
        )


if __name__ == "__main__":
    unittest.main()
