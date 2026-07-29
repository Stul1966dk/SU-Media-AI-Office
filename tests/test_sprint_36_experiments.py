"""Sprint 36 live experiment, evaluation, and learning tests."""

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core.database import Database
from core.decision_engine import DecisionEngine
from core.experiment_monitoring import ExperimentMonitoringService
from core.seo_experiment_engine import SEOExperimentEngine
from core.website_registry import WebsiteRegistry
from core.work_queue_service import WorkQueueService


class Sprint36ExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "sprint36.db")
        self.database.initialize()
        self.database.upsert_website({
            "website": "site.dk", "display_name": "Site", "active": True,
            "monetized": True, "priority": "high",
            "primary_income_source": "affiliate", "niche": "test",
            "domain_age": "1", "notes": "", "status": "active",
        })
        self.registry = WebsiteRegistry(self.database)
        self.experiments = SEOExperimentEngine(self.database)
        self.decisions = DecisionEngine(
            self.database, self.registry,
            experiment_engine=self.experiments,
        )
        self.url = "https://site.dk/guide/"
        self._period("2026-05-24", "2026-06-20", 30, 1000, .03, 6.8)

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _period(
        self, start: str, end: str, clicks: int, impressions: int,
        ctr: float, position: float,
    ) -> None:
        self.database.upsert_search_console_dimension(
            dimension_type="page", website_id="site.dk",
            site_url="https://site.dk/", page_url=self.url, query=None,
            period_start=start, period_end=end, clicks=clicks,
            impressions=impressions, ctr=ctr, average_position=position,
        )

    def _started_experiment(self) -> dict:
        experiment_id = self.experiments.create_experiment({
            "website": "site.dk", "target_url": self.url,
            "target_query": "", "experiment_type": "title_meta",
            "experiment_goal": "En mere konkret title øger CTR.",
            "task_description": "Test en ny title og meta.",
            "goal_metric": "ctr", "goal_direction": "increase",
            "target_change_pct": 15, "waiting_period_days": 28,
            "confidence": 80,
        })
        self.database.update_seo_experiment(
            experiment_id,
            self.experiments.calculate_baseline("site.dk", self.url),
        )
        return self.experiments.start_experiment(
            experiment_id, approved=True,
            started_at=datetime.fromisoformat("2026-07-19T10:00:00+02:00"),
        )

    def test_pulse_is_cautious_and_observations_are_idempotent(self) -> None:
        experiment = self._started_experiment()
        self._period("2026-06-21", "2026-07-18", 40, 1050, .038, 5.7)
        monitor = ExperimentMonitoringService(self.database)
        first = monitor.update_experiment(
            experiment["id"], date.fromisoformat("2026-07-25")
        )
        before = self.database.get_experiment_observations(experiment["id"])
        second = monitor.update_experiment(
            experiment["id"], date.fromisoformat("2026-07-25")
        )
        after = self.database.get_experiment_observations(experiment["id"])
        self.assertEqual("Positiv udvikling", first["pulse_status"])
        self.assertIn("fortsætter", first["observation"])
        self.assertEqual(first["pulse_status"], second["pulse_status"])
        self.assertEqual(len(before), len(after))
        self.assertEqual(
            1, len(self.database.get_experiment_snapshots(experiment["id"]))
        )

    def test_lower_position_is_better_and_low_data_is_inconclusive(self) -> None:
        experiment = self._started_experiment()
        improved = self.experiments.classify_result(experiment, {
            "baseline_start": "2026-06-21", "baseline_end": "2026-07-18",
            "baseline_clicks": 42, "baseline_impressions": 1050,
            "baseline_ctr": .04, "baseline_position": 5.7,
        })
        self.assertGreater(improved["position_gain"], 0)
        self.assertIn(improved["classification"], {
            "Tydeligt forbedret", "Forbedret", "Delvist forbedret",
        })
        insufficient = self.experiments.classify_result(experiment, {
            "baseline_start": "2026-07-15", "baseline_end": "2026-07-18",
            "baseline_clicks": 1, "baseline_impressions": 20,
            "baseline_ctr": .05, "baseline_position": 5.0,
        })
        self.assertEqual("Utilstrækkelige data", insufficient["classification"])

    def test_sitewide_conflict_but_other_url_is_allowed(self) -> None:
        self._started_experiment()
        self.assertTrue(self.decisions.has_conflict({
            "website": "site.dk", "target_url": "https://site.dk/",
            "experiment_type": "technical_fix", "scope": "sitewide",
        }))
        self.assertFalse(self.decisions.has_conflict({
            "website": "site.dk", "target_url": "https://site.dk/andet/",
            "experiment_type": "title_meta", "scope": "url",
        }))

    def test_daily_work_helpers_require_concrete_title_and_meta(self) -> None:
        page = (
            Path(__file__).resolve().parents[1]
            / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
        )
        spec = importlib.util.spec_from_file_location("daily_work_test", page)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertFalse(module._has_concrete_change({
            "change_type": "title_meta",
            "approved_title": "Kun title", "approved_meta": "",
        }))
        self.assertTrue(module._has_concrete_change({
            "change_type": "title_meta", "approved_title": "Valgt title",
            "approved_meta": "Valgt metabeskrivelse",
        }))

    def test_daily_work_shows_selected_change_and_protects_implementation(
        self,
    ) -> None:
        candidate = {
            "website": "site.dk", "target_url": self.url,
            "target_query": "guide",
            "task_title": "Title og meta på guidesiden",
            "task_description": "Opdater title og metabeskrivelse.",
            "expected_effect": "Flere relevante klik",
            "confidence": 82, "estimated_minutes": 30,
            "priority_score": 82,
            "implementation_content": {
                "type": "title_meta",
                "current_title": "Gammel title",
                "new_title": "Brugerens valgte title",
                "current_meta": "Gammel metabeskrivelse",
                "new_meta": "Brugerens valgte metabeskrivelse",
                "previous_titles": [{"text": "Tidligere AI-title"}],
                "previous_metas": [{"text": "Tidligere AI-meta"}],
            },
        }
        self.database.replace_queued_work([candidate])
        item = self.database.get_work_queue()[0]
        self.database.update_work_queue_item(item["id"], {
            "status": "awaiting_implementation",
        })
        self.database.save_approved_change({
            "website_id": "site.dk", "change_type": "title_meta",
            "target_url": self.url, "target_query": "guide",
            "current_title": "Gammel title",
            "approved_title": "Brugerens valgte title",
            "current_meta": "Gammel metabeskrivelse",
            "approved_meta": "Brugerens valgte metabeskrivelse",
            "hypothesis": "En tydeligere title øger CTR.",
            "reason": "Siden har mange visninger.",
            "expected_effect": "Flere relevante klik",
            "project_id": None, "task_id": None, "experiment_id": None,
            "source_draft_id": 999, "status": "awaiting_implementation",
        })
        # Link the fixture through the same persisted foreign key used by UI.
        self.database.update_work_queue_item(item["id"], {
            "experiment_id": None,
        })
        approved = self.database.get_approved_changes(source_draft_id=999)[0]
        # This fixture has no draft relation, so use a matching experiment key.
        self.database._connection.execute(
            "UPDATE approved_changes SET experiment_id = 999 WHERE id = ?",
            (approved["id"],),
        )
        self.database.update_work_queue_item(item["id"], {
            "experiment_id": 999,
        })
        self.database._connection.commit()
        page = (
            Path(__file__).resolve().parents[1]
            / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
        )
        with patch.dict(
            os.environ,
            {"SU_MEDIA_DATABASE_PATH": str(self.database.path)},
        ):
            app = AppTest.from_file(str(page)).run(timeout=20)
        self.assertFalse(app.exception)
        visible = " ".join(
            [item.value for item in app.markdown]
            + [item.value for item in app.code]
            + [item.value for item in app.success]
        )
        self.assertIn("Brugerens valgte title", visible)
        self.assertIn("Brugerens valgte metabeskrivelse", visible)
        self.assertIn(
            "🟢 Markér som implementeret",
            [button.label for button in app.button],
        )
        self.assertEqual(
            ["Udviklerværktøjer · midlertidig test"],
            [expander.label for expander in app.expander],
        )
        normal_buttons = [
            button.label for button in app.button
            if not button.label.startswith("Test ")
        ]
        self.assertEqual(1, len(normal_buttons))
        self.assertTrue(normal_buttons[0].endswith("som implementeret"))
        source = page.read_text(encoding="utf-8")
        self.assertNotIn("Vis godkendelsesgrundlag", source)
        self.assertIn("Kopiér title", source)
        self.assertIn("Kopiér metabeskrivelse", source)
        self.assertIn("st.code(", source)
        self.assertNotIn("components.html(", source)

        self.database._connection.execute(
            """UPDATE approved_changes SET approved_meta = ''
               WHERE experiment_id = 999"""
        )
        self.database._connection.commit()
        with patch.dict(
            os.environ,
            {"SU_MEDIA_DATABASE_PATH": str(self.database.path)},
        ):
            missing = AppTest.from_file(str(page)).run(timeout=20)
        self.assertNotIn(
            "🟢 Markér som implementeret",
            [button.label for button in missing.button],
        )
        self.assertTrue(any(
            "Ingen kandidat opfylder" in info.value
            for info in missing.info
        ))

    def test_daily_work_has_only_complete_recommendation_actions(self) -> None:
        self.database.upsert_website({
            "website": "empty.dk", "display_name": "Empty.dk",
            "active": True, "monetized": True, "priority": "medium",
            "primary_income_source": "affiliate", "niche": "test",
            "domain_age": "1", "notes": "", "status": "active",
        })
        self.database.create_title_optimization_draft({
            "website": "site.dk", "target_url": self.url,
            "target_query": "guide", "current_title": "Den gamle guide",
            "current_meta": "Den gamle metabeskrivelse",
            "page_analysis": {"search_console": {
                "clicks": 30, "impressions": 1000, "ctr": .03,
                "position": 6.8,
            }},
            "analysis": {},
            "title_proposals": [{
                "text": "Den anbefalede guide til det rigtige valg",
                "reason": "Mere konkret",
            }],
            "meta_proposals": [{
                "text": "Læs guiden og få et klart overblik over de vigtigste muligheder og dit næste valg.",
                "reason": "Mere konkret",
            }],
            "reviewer": {"approved": True},
            "recommended_title_index": 0, "recommended_meta_index": 0,
            "confidence": 85, "expected_effect": "Flere klik",
            "measurement_method": "Sammenlign CTR",
        }, [])
        page = (
            Path(__file__).resolve().parents[1]
            / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
        )
        with patch.dict(
            os.environ, {"SU_MEDIA_DATABASE_PATH": str(self.database.path)}
        ):
            app = AppTest.from_file(str(page)).run(timeout=20)
        self.assertFalse(app.exception)
        normal_buttons = [
            button.label for button in app.button
            if not button.label.startswith("Test ")
        ]
        self.assertEqual(
            ["🟢 Accepter opgave", "⚪ Spring over"],
            normal_buttons,
        )
        self.assertEqual("Alle websites", app.selectbox[0].value)
        visible = " ".join(
            [item.value for item in app.markdown]
            + [item.value for item in app.code]
        )
        self.assertIn("Den anbefalede guide", visible)
        self.assertIn("site.dk", visible)
        self.assertNotIn("Vis analyse", visible)
        self.assertNotIn("Aktive eksperimenter", visible)
        source = page.read_text(encoding="utf-8")
        self.assertNotIn('pop("daily_work_website_filter"', source)
        with patch.dict(
            os.environ, {"SU_MEDIA_DATABASE_PATH": str(self.database.path)}
        ):
            app = app.selectbox[0].select("empty.dk").run(timeout=20)
        self.assertEqual("empty.dk", app.selectbox[0].value)
        self.assertEqual([], [
            button.label for button in app.button
            if not button.label.startswith("Test ")
        ])
        self.assertTrue(any(
            "mangler Search Console-data" in item.value
            for item in app.info
        ))

    def test_migration_recovers_selected_copy_from_approved_draft(self) -> None:
        draft_id = self.database.create_title_optimization_draft({
            "website": "site.dk", "target_url": self.url,
            "target_query": "guide", "current_title": "Gammel title",
            "current_meta": "Gammel meta", "page_analysis": {},
            "analysis": {}, "title_proposals": [{
                "text": "Godkendt migreret title", "reason": "Test",
            }], "meta_proposals": [{
                "text": "Godkendt migreret metabeskrivelse", "reason": "Test",
            }],
            "reviewer": {"approved": True},
            "recommended_title_index": 0, "recommended_meta_index": 0,
            "confidence": 80, "expected_effect": "Flere klik",
            "measurement_method": "Sammenlign CTR",
        }, [])
        self.database.update_title_optimization_draft(draft_id, {
            "status": "approved", "approved_at": "2026-07-19T10:00:00+02:00",
        })
        candidate = {
            "website": "site.dk", "target_url": self.url,
            "target_query": "guide", "task_title": "Title og meta",
            "task_description": "Godkendt ændring",
            "expected_effect": "Flere klik", "confidence": 80,
            "estimated_minutes": 30, "priority_score": 80,
            "draft_id": draft_id,
            "implementation_content": {"type": "title_meta"},
        }
        self.database.replace_queued_work([candidate])
        queue_item = self.database.get_work_queue()[0]
        self.database.update_work_queue_item(queue_item["id"], {
            "status": "awaiting_implementation",
        })
        queue = WorkQueueService(self.database, self.registry)
        result = queue.migrate_approved_changes()
        migrated = self.database.get_approved_change_for_work_item(
            self.database.get_work_queue_item(queue_item["id"])
        )
        self.assertEqual(1, result["recovered"])
        self.assertEqual(
            "Godkendt migreret title",
            migrated["approved_title"],
        )
        self.assertEqual(
            "Godkendt migreret metabeskrivelse",
            migrated["approved_meta"],
        )


if __name__ == "__main__":
    unittest.main()
