"""Sprint 43.6 tests for the practical SEO work overview."""

import unittest

from core.traffic_work_overview import (
    build_traffic_work_overview,
    next_actionable_work,
)


def decision(status: str, *, website: str = "site.dk", evidence=None):
    return {
        "recommendation_key": f"key-{status}-{website}",
        "website_id": website,
        "status": status,
        "title": f"Arbejde på {website}",
        "target_url": f"https://{website}/guide/",
        "evidence": evidence or {},
    }


def experiment(
    experiment_id: int,
    status: str,
    *,
    website: str = "site.dk",
):
    return {
        "id": experiment_id,
        "website_id": website,
        "status": status,
        "target_url": f"https://{website}/guide/",
        "change_description": f"Ændring {experiment_id}",
        "planned_evaluation_date": "2026-08-25",
    }


class TrafficWorkOverviewTests(unittest.TestCase):
    def test_action_order_is_evaluate_implement_approve_measure(self):
        rows = build_traffic_work_overview(
            [
                decision("draft", website="draft.dk"),
                decision("approved", website="approved.dk"),
                decision(
                    "experiment_running",
                    website="measure.dk",
                    evidence={"experiment_id": 3},
                ),
                decision(
                    "experiment_running",
                    website="evaluate.dk",
                    evidence={"experiment_id": 4},
                ),
            ],
            [
                experiment(3, "waiting_for_data", website="measure.dk"),
                experiment(
                    4, "ready_for_evaluation", website="evaluate.dk"
                ),
            ],
        )
        self.assertEqual(
            ["ready_for_evaluation", "approved", "draft", "measurement"],
            [item["stage"] for item in rows],
        )
        self.assertEqual(
            "ready_for_evaluation", next_actionable_work(rows)["stage"]
        )

    def test_linked_experiment_is_not_duplicated(self):
        rows = build_traffic_work_overview(
            [decision(
                "experiment_running", evidence={"experiment_id": 7}
            )],
            [experiment(7, "waiting_for_data")],
        )
        self.assertEqual(1, len(rows))
        self.assertEqual(7, rows[0]["experiment_id"])
        self.assertEqual("measurement", rows[0]["stage"])

    def test_standalone_active_experiment_is_included(self):
        rows = build_traffic_work_overview(
            [], [experiment(9, "waiting_for_data")]
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("Følg målingen", rows[0]["link_label"])
        self.assertIsNone(next_actionable_work(rows))

    def test_old_queue_approved_experiment_is_left_to_existing_queue(self):
        rows = build_traffic_work_overview(
            [], [experiment(10, "approved")]
        )
        self.assertEqual([], rows)

    def test_completed_rejected_and_snoozed_work_is_hidden(self):
        rows = build_traffic_work_overview(
            [
                decision("rejected"),
                decision("snoozed"),
                decision(
                    "experiment_running",
                    evidence={"experiment_id": 11},
                ),
            ],
            [experiment(11, "completed")],
        )
        self.assertEqual([], rows)

    def test_website_filter_applies_to_decisions_and_experiments(self):
        rows = build_traffic_work_overview(
            [
                decision("draft", website="a.dk"),
                decision("approved", website="b.dk"),
            ],
            [
                experiment(1, "waiting_for_data", website="a.dk"),
                experiment(2, "waiting_for_data", website="b.dk"),
            ],
            website_id="a.dk",
        )
        self.assertTrue(rows)
        self.assertEqual({"a.dk"}, {item["website"] for item in rows})


if __name__ == "__main__":
    unittest.main()
