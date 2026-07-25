"""Sprint 42.4 tests for the Plausible traffic minimum basis."""

import unittest
from datetime import date, timedelta

from dashboard.components.data import build_dashboard_priority_tasks


TODAY = date(2026, 7, 24)


def rows(website: str, current: list[int], previous: list[int]):
    values = current + previous
    return [
        {
            "website": website,
            "metric_date": (TODAY - timedelta(days=offset)).isoformat(),
            "visitors": visitors,
        }
        for offset, visitors in enumerate(values, start=1)
    ]


def tasks(plausible_rows):
    return build_dashboard_priority_tasks(
        system_status={},
        seo_sites=[],
        project_tasks=[],
        experiments=[],
        coverage=[],
        plausible_rows=plausible_rows,
        today=TODAY,
    )


class PlausibleMinimumBasisTests(unittest.TestCase):
    def test_twenty_percent_decline_with_twenty_previous_visitors(self) -> None:
        result = tasks(rows(
            "enough.dk",
            current=[2, 2, 2, 2, 2, 3, 3],
            previous=[2, 3, 3, 3, 3, 3, 3],
        ))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["change"], "-20,0 %")

    def test_decline_with_fewer_than_twenty_previous_visitors_is_ignored(self) -> None:
        result = tasks(rows(
            "small.dk",
            current=[1, 1, 1, 1, 1, 1, 1],
            previous=[2, 2, 2, 2, 2, 2, 2],
        ))
        self.assertEqual(result, [])

    def test_growth_and_smaller_decline_are_still_ignored(self) -> None:
        self.assertEqual(tasks(rows(
            "growth.dk", current=[4] * 7, previous=[3] * 7
        )), [])
        self.assertEqual(tasks(rows(
            "small-fall.dk", current=[9] * 7, previous=[10] * 7
        )), [])


if __name__ == "__main__":
    unittest.main()
