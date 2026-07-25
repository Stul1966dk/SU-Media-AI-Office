"""Sprint 42.6 dynamic priority score and persistence tests."""

import tempfile
import unittest
from pathlib import Path

from core.database import Database
from core.priority_config import PRIORITY_CONFIG
from core.priority_scoring import (
    SCORE_FIELDS,
    score_priority_item,
    stable_priority_key,
)


def item(task_type: str, **values):
    return {
        "task_key": f"{task_type}|example.dk",
        "task_type": task_type,
        "website": "example.dk",
        "description": "Test",
        "target": "app.py",
        "link_label": "Åbn",
        **values,
    }


class PriorityScoringTests(unittest.TestCase):
    def test_larger_plausible_decline_scores_higher(self) -> None:
        small = score_priority_item(item(
            "plausible_decline", plausible_change=-20
        ))
        large = score_priority_item(item(
            "plausible_decline", plausible_change=-60
        ))
        self.assertGreater(large["plausible_score"], small["plausible_score"])

    def test_larger_search_console_declines_score_higher(self) -> None:
        baseline = item("seo_health", seo_health_trend="stable")
        for field, mild, severe, score_field in (
            ("click_change", -5, -20, "search_console_click_score"),
            ("ctr_change", -0.5, -2, "ctr_score"),
            ("position_change", 1, 4, "position_score"),
        ):
            lower = score_priority_item({**baseline, field: mild})
            higher = score_priority_item({**baseline, field: severe})
            self.assertGreater(higher[score_field], lower[score_field])

    def test_critical_health_scores_higher_than_declining(self) -> None:
        critical = score_priority_item(item(
            "seo_health", seo_health_trend="critical"
        ))
        declining = score_priority_item(item(
            "seo_health", seo_health_trend="declining"
        ))
        self.assertGreater(
            critical["seo_health_score"], declining["seo_health_score"]
        )

    def test_active_experiment_contributes_its_own_subscore(self) -> None:
        active = score_priority_item(item(
            "seo_health", has_active_experiment=True
        ))
        inactive = score_priority_item(item("seo_health"))
        self.assertEqual(
            PRIORITY_CONFIG["weights"]["experiment_active"],
            active["experiment_score"],
        )
        self.assertGreater(active["total_score"], inactive["total_score"])

    def test_total_is_exact_sum_of_subscores(self) -> None:
        scored = score_priority_item(item(
            "combined_traffic_decline",
            plausible_change=-35,
            click_change=-12,
            ctr_change=-1.2,
            position_change=2,
            seo_health_trend="declining",
        ))
        self.assertEqual(
            scored["total_score"],
            round(sum(scored[field] for field in SCORE_FIELDS), 2),
        )

    def test_config_change_changes_result_without_algorithm_change(self) -> None:
        custom = {
            "thresholds": dict(PRIORITY_CONFIG["thresholds"]),
            "weights": dict(PRIORITY_CONFIG["weights"]),
        }
        custom["weights"]["position_per_position"] = 10
        default = score_priority_item(item(
            "seo_health", position_change=2
        ))
        changed = score_priority_item(
            item("seo_health", position_change=2), config=custom
        )
        self.assertGreater(changed["position_score"], default["position_score"])

    def test_sort_is_score_first_and_deterministic_on_ties(self) -> None:
        rows = [
            score_priority_item(item(
                "missing_plausible", task_key="b", website="b.dk"
            )),
            score_priority_item(item(
                "missing_search_console", task_key="c", website="c.dk"
            )),
            score_priority_item(item(
                "missing_plausible", task_key="a", website="a.dk"
            )),
        ]
        ordered = sorted(rows, key=stable_priority_key)
        self.assertEqual("missing_search_console", ordered[0]["task_type"])
        self.assertEqual(["a.dk", "b.dk"], [
            row["website"] for row in ordered[1:]
        ])


class PriorityPersistenceTests(unittest.TestCase):
    def test_migration_and_snapshot_preserve_scores(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "test.db")
            database.initialize()
            scored = score_priority_item(item(
                "combined_traffic_decline",
                plausible_change=-30,
                click_change=-10,
                seo_health_trend="declining",
            ))
            self.assertEqual(1, database.replace_priority_task_scores([scored]))
            stored = database.get_priority_task_scores()
            self.assertEqual(1, len(stored))
            self.assertEqual(scored["total_score"], stored[0]["total_score"])
            self.assertEqual(
                scored["plausible_score"], stored[0]["plausible_score"]
            )
            database.close()


if __name__ == "__main__":
    unittest.main()
