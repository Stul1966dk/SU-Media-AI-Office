"""Sprint 30 single decision, experiment, and safe cleanup tests."""

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from core.database import Database
from core.decision_engine import DecisionEngine
from core.seo_experiment_engine import SEOExperimentEngine
from core.website_registry import WebsiteRegistry


class Sprint30Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        for website in ("high.dk", "low.dk", "robotland.dk"):
            self.database.upsert_website({
                "website": website, "display_name": website, "active": True,
                "monetized": True, "priority": "high",
                "primary_income_source": "affiliate", "niche": "test",
                "domain_age": "1", "notes": "", "status": "active",
            })
        self.registry = WebsiteRegistry(self.database)
        self.experiments = SEOExperimentEngine(self.database)
        self.engine = DecisionEngine(
            self.database, self.registry,
            experiment_engine=self.experiments,
        )

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _period(
        self, website: str, url: str, query: str,
        start: str, end: str, clicks: int, impressions: int,
    ) -> None:
        for dimension, page, word in (
            ("page", url, None),
            ("query", None, query),
            ("page_query", url, query),
        ):
            self.database.upsert_search_console_dimension(
                dimension_type=dimension, website_id=website,
                site_url=f"https://{website}/", page_url=page, query=word,
                period_start=start, period_end=end, clicks=clicks,
                impressions=impressions,
                ctr=clicks / impressions if impressions else 0,
                average_position=7,
            )

    def _evidence(self) -> None:
        self._period(
            "high.dk", "https://high.dk/guide/", "bedste guide",
            "2026-05-24", "2026-06-20", 500, 5000,
        )
        self._period(
            "high.dk", "https://high.dk/guide/", "bedste guide",
            "2026-06-21", "2026-07-18", 350, 5100,
        )
        self._period(
            "low.dk", "https://low.dk/lille/", "lille",
            "2026-05-24", "2026-06-20", 1, 3,
        )
        self._period(
            "low.dk", "https://low.dk/lille/", "lille",
            "2026-06-21", "2026-07-18", 0, 3,
        )

    def test_one_concrete_decision_and_low_volume_is_downgraded(self) -> None:
        self._evidence()
        ranked = self.engine.rank_candidates(self.engine.collect_candidates())
        self.assertEqual("high.dk", ranked[0]["website"])
        self.assertLessEqual(next(
            item["priority_score"] for item in ranked
            if item["website"] == "low.dk"
        ), 25)
        decision = self.engine.select_single_decision()
        self.assertEqual("https://high.dk/guide/", decision["target_url"])
        self.assertEqual("bedste guide", decision["target_query"])
        self.assertLessEqual(len(decision["exact_steps"]), 5)
        self.assertEqual(
            decision["decision_id"],
            self.engine.select_single_decision()["decision_id"],
        )
        self.assertEqual({
            "traffic_potential", "traffic_trend", "affiliate_income",
            "monetization_opportunity",
            "seo_health", "data_quality", "ai_confidence",
            "existing_work_penalty", "active_experiment_penalty",
            "waiting_time", "expected_gain", "learning",
        }, set(ranked[0]["score_factors"]))

    def test_active_work_only_gives_moderate_diversity_adjustment(self) -> None:
        self._evidence()
        self.database.create_project_record({
            "website_id": "high.dk", "title": "Aktivt arbejde",
            "description": "Allerede prioriteret", "status": "planning",
            "priority": "high", "expected_effect": "Test",
            "created_at": "2026-07-19T10:00:00+02:00",
        })
        ranked = self.engine.rank_candidates(self.engine.collect_candidates())
        self.assertEqual("high.dk", ranked[0]["website"])
        decision = self.engine.select_single_decision()
        self.assertEqual("high.dk", decision["website"])

    def test_approval_is_idempotent_and_persists_baseline(self) -> None:
        self._evidence()
        decision = self.engine.select_single_decision("high.dk")
        first = self.engine.send_decision_to_project_manager(
            decision["decision_id"]
        )
        second = self.engine.send_decision_to_project_manager(
            decision["decision_id"]
        )
        self.assertEqual(first, second)
        experiment = self.database.get_seo_experiment(first["experiment_id"])
        self.assertEqual(350, experiment["baseline_clicks"])
        self.assertEqual("2026-07-18", experiment["baseline_end"])

    def test_generic_task_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DecisionEngine._validate_decision({
                "website": "high.dk", "target_url": "https://high.dk/",
                "task_title": "Optimér siden",
                "task_description": "Optimér siden",
                "exact_steps": ["Gør noget"], "completion_criteria": "Færdig",
                "assigned_agent": "SEO", "estimated_minutes": 60,
                "expected_effect": "Mere", "expected_effect_reason": "Data",
                "priority_score": 50, "priority_label": "Mellem",
                "confidence": 80, "measurement_method": "Mål",
                "experiment_type": "title_meta", "experiment_goal": "CTR",
                "waiting_period_days": 28, "why_selected": "Data",
                "why_not_other_tasks": [],
            })

    def test_baseline_lock_evaluation_learning_and_release(self) -> None:
        self._evidence()
        decision = self.engine.select_single_decision("high.dk")
        created = self.engine.send_decision_to_project_manager(
            decision["decision_id"]
        )
        experiment_id = created["experiment_id"]
        self.assertFalse(self.experiments.is_url_locked(decision["target_url"]))
        self.experiments.approve_experiment(experiment_id)
        self.assertTrue(self.experiments.is_url_locked(decision["target_url"]))
        started = self.experiments.start_experiment(
            experiment_id, started_at=datetime.fromisoformat(
                "2026-07-19T10:00:00+02:00"
            )
        )
        self.assertEqual(350, started["baseline_clicks"])
        self.assertEqual("2026-08-16", started["planned_evaluation_date"])
        self._period(
            "high.dk", "https://high.dk/guide/", "bedste guide",
            "2026-07-19", "2026-08-15", 430, 5200,
        )
        evaluated = self.experiments.evaluate_experiment(experiment_id)
        self.assertEqual("completed", evaluated["status"])
        self.assertIn(evaluated["result"], {
            "successful", "partially_successful", "no_measurable_effect",
            "negative_effect",
        })
        self.assertTrue(self.experiments.is_url_locked(decision["target_url"]))
        self.assertTrue(
            self.database.get_seo_url_status(decision["target_url"])
        )
        self.assertTrue(
            self.experiments.get_experiment_learning(experiment_id)
        )

    def test_robotland_cleanup_preserves_registry_and_search_data(self) -> None:
        project_id = self.database.create_project_record({
            "website_id": "robotland.dk", "title": "Redesign af Robotland.dk",
            "description": "test", "status": "ready", "priority": "high",
            "expected_effect": "test", "created_at": "2026-01-01",
        })
        subproject_id = self.database.create_subproject_record({
            "project_id": project_id, "title": "Analyse og plan",
            "description": "test", "status": "ready", "sequence": 1,
            "created_at": "2026-01-01",
        })
        self.database.create_task_record({
            "subproject_id": subproject_id, "website_id": "robotland.dk",
            "title": "Lav forslag til ny navigation", "description": "test",
            "reason": "test", "assigned_agent": "test",
            "estimated_minutes": 60, "expected_effect": "test",
            "measurement_method": "", "priority_score": 80,
            "status": "ready", "depends_on_task_id": None,
            "created_at": "2026-01-01",
        })
        self.database.upsert_search_console_daily_metric(
            website_id="robotland.dk", site_url="https://robotland.dk/",
            metric_date="2026-07-18", clicks=2, impressions=10,
            ctr=.2, average_position=3,
        )
        preview = self.database.preview_robotland_redesign_cleanup()
        self.assertEqual(1, preview["tasks"])
        self.database.cleanup_robotland_redesign_test_data()
        self.assertIsNone(self.database.get_project_record(project_id))
        self.assertIsNotNone(self.database.get_website("robotland.dk"))
        self.assertEqual(
            1, len(self.database.get_search_console_daily_metrics("robotland.dk"))
        )


if __name__ == "__main__":
    unittest.main()
