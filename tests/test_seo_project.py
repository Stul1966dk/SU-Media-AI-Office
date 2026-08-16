"""Goal-driven, multi-experiment SEO projects (P1).

A project turns a roadmap goal into a persistent track on one URL: it enqueues
the first experiment, proposes the next after each completes, and suggests
completion (for the user to confirm) once the goal is reached or the page is
exhausted.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.daily_work_preparation import DailyWorkPreparationService
from core.database import Database
from core.decision_engine import DecisionEngine
from core.seo_experiment_engine import SEOExperimentEngine
from core.seo_project import SEOProjectService
from core.website_registry import WebsiteRegistry
from core.work_queue_service import WorkQueueService


GAP_URL = "https://earner.dk/gap/"
EARLY = "2026-01-01T00:00:00+00:00"


class SEOProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        self.database.upsert_website({
            "website": "earner.dk", "display_name": "earner.dk", "active": True,
            "monetized": True, "priority": "high",
            "primary_income_source": "affiliate", "niche": "test",
            "domain_age": "1", "notes": "", "status": "active",
        })
        # /gap/: real traffic on page 2, earns nothing itself; the site earns
        # elsewhere -> a monetisation-gap candidate for /gap/.
        for start, end in (
            ("2026-05-24", "2026-06-20"), ("2026-06-21", "2026-07-18"),
        ):
            self.database.upsert_search_console_dimension(
                dimension_type="page", website_id="earner.dk",
                site_url="https://earner.dk/", page_url=GAP_URL,
                period_start=start, period_end=end, clicks=2, impressions=2000,
                ctr=0.001, average_position=18,
            )
        self._sale("/andet/", "500")
        self.registry = WebsiteRegistry(self.database)
        self.queue = WorkQueueService(
            self.database, self.registry,
            experiment_engine=SEOExperimentEngine(self.database),
            decision_engine=DecisionEngine(
                self.database, self.registry,
                experiment_engine=SEOExperimentEngine(self.database),
            ),
        )
        preparation = DailyWorkPreparationService(
            database=self.database, queue=self.queue, title_optimizer=Mock(),
        )
        self.service = SEOProjectService(self.database, preparation=preparation)

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _sale(self, uid: str, provision: str) -> None:
        self.database.upsert_partner_ads_sale({
            "kombiid": f"k{uid}", "provision": provision,
            "url": "https://earner.dk/", "uid": uid, "uid2": "",
            "valuta": "DKK", "dato": "01-06-2026",
        })

    def _project(self) -> int:
        return self.database.create_project_record({
            "website_id": "earner.dk",
            "title": f"Projekt: Tjen på trafikken — {GAP_URL}",
            "description": "d", "status": "active", "priority": "high",
            "expected_effect": "e", "created_at": EARLY,
            "target_url": GAP_URL, "goal_metric": "commission",
        })

    def _completed_experiment(self) -> int:
        return self.database.create_seo_experiment({
            "website_id": "earner.dk", "target_url": GAP_URL,
            "target_query": "", "experiment_type": "monetization",
            "hypothesis": "h", "change_description": "c",
            "goal_metric": "commission", "goal_direction": "increase",
            "target_change_pct": 25, "waiting_period_days": 28,
            "status": "completed", "confidence": 60,
        })

    def _queued_for_gap(self) -> list:
        return [
            item for item in self.database.get_work_queue(("queued",))
            if item["target_url"] == GAP_URL
        ]

    def test_start_creates_project_and_enqueues_first_experiment(self) -> None:
        project_id = self.service.start_project(
            "earner.dk", GAP_URL, "commission"
        )
        project = self.database.get_project_record(project_id)
        self.assertEqual("active", project["status"])
        self.assertEqual(GAP_URL, project["target_url"])
        self.assertEqual("commission", project["goal_metric"])
        queued = self._queued_for_gap()
        self.assertTrue(queued)
        self.assertEqual(
            "monetization", queued[0]["candidate"]["experiment_type"]
        )

    def test_a_second_project_on_the_same_url_is_rejected(self) -> None:
        self.service.start_project("earner.dk", GAP_URL, "commission")
        with self.assertRaises(ValueError):
            self.service.start_project("earner.dk", GAP_URL, "commission")

    def test_advance_suggests_completion_when_commission_arrives(self) -> None:
        project_id = self._project()
        self._completed_experiment()
        self._sale("/gap/", "300")  # the page now earns -> goal reached
        self.service.advance_due_projects()
        self.assertEqual(
            "awaiting_confirmation",
            self.database.get_project_record(project_id)["status"],
        )

    def test_advance_proposes_the_next_experiment_when_goal_not_reached(
        self,
    ) -> None:
        self._project()
        self._completed_experiment()  # done, but /gap/ still earns nothing
        self.service.advance_due_projects()
        self.assertTrue(self._queued_for_gap())

    def test_advance_suggests_completion_when_page_is_exhausted(self) -> None:
        project_id = self._project()
        self._completed_experiment()
        self.database.upsert_seo_url_status(
            target_url=GAP_URL, website_id="earner.dk",
            status="Kræver ny strategi", failed_same_type_count=2,
        )
        self.service.advance_due_projects()
        self.assertEqual(
            "awaiting_confirmation",
            self.database.get_project_record(project_id)["status"],
        )

    def test_confirm_completion_closes_the_project(self) -> None:
        project_id = self._project()
        self.service.confirm_completion(project_id)
        self.assertEqual(
            "completed", self.database.get_project_record(project_id)["status"]
        )

    def test_progress_and_answer_summarise_the_project(self) -> None:
        project_id = self._project()
        self._completed_experiment()
        progress = self.service.project_progress(project_id)
        self.assertEqual("commission", progress["goal_metric"])
        self.assertEqual(1, len(progress["experiments"]))
        answer = self.service.answer_question(project_id, "Hvad er status?")
        self.assertIn("Mål:", answer)


if __name__ == "__main__":
    unittest.main()
