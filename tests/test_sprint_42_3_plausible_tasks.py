"""Sprint 42.3 tests for Plausible traffic decline tasks."""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from core.database import Database
from dashboard.components.data import build_dashboard_priority_tasks


TODAY = date(2026, 7, 24)


def plausible_rows(
    website: str,
    *,
    current: int,
    previous: int,
    missing_offset: int | None = None,
) -> list[dict[str, object]]:
    rows = []
    for offset in range(1, 15):
        if offset == missing_offset:
            continue
        rows.append({
            "website": website,
            "metric_date": (TODAY - timedelta(days=offset)).isoformat(),
            "visitors": current if offset <= 7 else previous,
        })
    return rows


def build(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return build_dashboard_priority_tasks(
        system_status={},
        seo_sites=[],
        project_tasks=[],
        experiments=[],
        coverage=[],
        plausible_rows=rows,
        today=TODAY,
    )


class PlausibleTrafficTaskTests(unittest.TestCase):
    def test_decline_of_at_least_twenty_percent_creates_one_task(self) -> None:
        tasks = build(plausible_rows(
            "fall.dk", current=8, previous=10
        ))
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["priority"], "Høj")
        self.assertEqual(tasks[0]["website"], "fall.dk")
        self.assertEqual(tasks[0]["description"], "Plausible-trafikken er faldet.")
        self.assertEqual(tasks[0]["change"], "-20,0 %")
        self.assertEqual(tasks[0]["target"], "pages/1_Website_Profile.py")

    def test_smaller_decline_creates_no_task(self) -> None:
        self.assertEqual(
            build(plausible_rows("small.dk", current=81, previous=100)),
            [],
        )

    def test_missing_period_data_creates_no_task(self) -> None:
        self.assertEqual(
            build(plausible_rows(
                "missing.dk", current=5, previous=10, missing_offset=14
            )),
            [],
        )

    def test_growing_traffic_creates_no_task(self) -> None:
        self.assertEqual(
            build(plausible_rows("growth.dk", current=12, previous=10)),
            [],
        )

    def test_database_context_excludes_inactive_websites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.sqlite3")
            database.initialize()
            try:
                for website, active, status in (
                    ("active.dk", True, "active"),
                    ("inactive.dk", False, "inactive"),
                ):
                    database.upsert_website({
                        "website": website,
                        "display_name": website,
                        "active": active,
                        "monetized": False,
                        "priority": "normal",
                        "primary_income_source": "",
                        "niche": "test",
                        "domain_age": "",
                        "notes": "",
                        "status": status,
                    })
                    for row in plausible_rows(
                        website, current=5, previous=10
                    ):
                        database.upsert_plausible_daily_metric(
                            website_id=website,
                            metric_date=str(row["metric_date"]),
                            visitors=int(row["visitors"]),
                        )
                context = database.get_dashboard_action_context()
            finally:
                database.close()

        self.assertEqual(
            {row["website"] for row in context["plausible_daily"]},
            {"active.dk"},
        )


if __name__ == "__main__":
    unittest.main()
