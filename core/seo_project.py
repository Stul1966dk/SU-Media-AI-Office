"""Goal-driven, multi-experiment SEO projects.

A project binds a persistent goal (e.g. "earn from this traffic") to one URL and
runs a *series* of measured 28-day experiments toward it: propose a change →
measure → evaluate → propose the next → … until the goal is reached or the page
is exhausted. Completion is only *suggested*; the user confirms.

The project reuses the income-first, learning-aware delivery already in place:
it enqueues the next experiment for its URL via the daily work queue, and
associates experiments to the project by URL and start time (so it never fights
the queue's own per-experiment bookkeeping).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from core.revenue_attribution import page_key_for_url, revenue_by_page


GOAL_METRICS = {"commission", "position", "ctr"}
GOAL_LABELS = {
    "commission": "Tjen på trafikken",
    "position": "Forbedr placeringen",
    "ctr": "Forbedr klikraten",
}
# A page ranking at or above this position counts as a reached ranking goal.
POSITION_GOAL_MAX = 10.0
ACTIVE_PROJECT_STATUSES = {"active", "awaiting_confirmation"}


class SEOProjectService:
    """Create and advance goal-driven SEO projects."""

    def __init__(
        self, database: Any, *, preparation: Any | None = None,
        ai_service: Any | None = None,
    ) -> None:
        # preparation is only needed to enqueue new experiments (start/advance);
        # reads (progress, dialog, confirm) work without it.
        self.database = database
        self.preparation = preparation
        self.ai_service = ai_service

    # -- creation -----------------------------------------------------------

    def start_project(
        self, website_id: str, target_url: str, goal_metric: str
    ) -> int:
        """Create a goal project for a URL and enqueue its first experiment."""
        if goal_metric not in GOAL_METRICS:
            raise ValueError("Ukendt målemetrik for projektet.")
        target_url = str(target_url).strip()
        if not target_url:
            raise ValueError("Et projekt kræver en konkret URL.")
        if self.active_project_for_url(target_url):
            raise ValueError(
                "Der er allerede et aktivt projekt for denne side."
            )
        goal_label = GOAL_LABELS[goal_metric]
        project_id = self.database.create_project_record({
            "website_id": website_id,
            "title": f"Projekt: {goal_label} — {target_url}",
            "description": (
                f"Mål: {goal_label} på {target_url}. Projektet kører en serie "
                "målte 28-dages-eksperimenter, indtil målet er nået eller siden "
                "er udtømt."
            ),
            "status": "active",
            "priority": "high",
            "expected_effect": goal_label,
            "created_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "target_url": target_url,
            "goal_metric": goal_metric,
        })
        self._enqueue_next(website_id, target_url)
        return project_id

    def active_project_for_url(self, target_url: str) -> dict[str, Any] | None:
        return next(
            (
                project
                for project in self.database.get_seo_goal_projects()
                if project["target_url"] == target_url
                and project["status"] in ACTIVE_PROJECT_STATUSES
            ),
            None,
        )

    # -- the loop -----------------------------------------------------------

    def advance_due_projects(
        self, reference_date: date | None = None
    ) -> list[dict[str, Any]]:
        """Advance every active project whose current experiment has finished."""
        results = []
        for project in self.database.get_seo_goal_projects(status="active"):
            try:
                results.append(self._advance(project))
            except Exception:  # isolate each project
                results.append(
                    {"project_id": project["id"], "action": "failed"}
                )
        return results

    def _advance(self, project: dict[str, Any]) -> dict[str, Any]:
        website_id = project["website_id"]
        target_url = project["target_url"]
        experiments = self._project_experiments(project)
        if not experiments:
            self._enqueue_next(website_id, target_url)
            return {"project_id": project["id"], "action": "enqueued_first"}
        latest = experiments[-1]
        if str(latest.get("status")) != "completed":
            return {"project_id": project["id"], "action": "waiting"}
        if self._goal_reached(project):
            self.database.set_project_status(
                project["id"], "awaiting_confirmation"
            )
            return {"project_id": project["id"], "action": "goal_met"}
        if self._exhausted(target_url):
            self.database.set_project_status(
                project["id"], "awaiting_confirmation"
            )
            return {"project_id": project["id"], "action": "exhausted"}
        self._enqueue_next(website_id, target_url)
        return {"project_id": project["id"], "action": "enqueued_next"}

    def confirm_completion(self, project_id: int) -> None:
        self.database.set_project_status(
            project_id, "completed",
            completed_at=datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
        )

    def abandon(self, project_id: int) -> None:
        self.database.set_project_status(
            project_id, "abandoned",
            completed_at=datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
        )

    # -- reads --------------------------------------------------------------

    def project_progress(self, project_id: int) -> dict[str, Any]:
        project = self.database.get_project_record(project_id) or {}
        experiments = self._project_experiments(project) if project else []
        return {
            "project": project,
            "goal_metric": project.get("goal_metric"),
            "goal_label": GOAL_LABELS.get(project.get("goal_metric"), ""),
            "target_url": project.get("target_url"),
            "status": project.get("status"),
            "goal_reached": bool(project) and self._goal_reached(project),
            "experiments": [
                {
                    "experiment_type": item.get("experiment_type"),
                    "status": item.get("status"),
                    "result": item.get("result"),
                    "result_summary": item.get("result_summary"),
                    "started_at": item.get("started_at"),
                }
                for item in experiments
            ],
        }

    def answer_question(self, project_id: int, question: str) -> str:
        """Answer a question about a project, grounded in its measured data."""
        progress = self.project_progress(project_id)
        if not progress.get("project"):
            return "Projektet kunne ikke findes."
        fallback = self._fallback_answer(progress)
        if self.ai_service is None:
            return fallback
        prompt = (
            "Du er en SEO-rådgiver. Svar kort og konkret på dansk på brugerens "
            "spørgsmål om projektet. Brug KUN de givne fakta; opdigt intet.\n"
            f"Spørgsmål: {question}\n"
            + json.dumps(progress, ensure_ascii=False, default=str)
        )
        try:
            text = self.ai_service.generate_response(prompt).text.strip()
            return text or fallback
        except Exception:
            return fallback

    @staticmethod
    def _fallback_answer(progress: dict[str, Any]) -> str:
        experiments = progress["experiments"]
        done = [item for item in experiments if item["status"] == "completed"]
        active = [
            item for item in experiments if item["status"] != "completed"
        ]
        lines = [
            f"Mål: {progress['goal_label']} på {progress['target_url']}.",
            f"Status: {progress['status']}.",
            f"Eksperimenter i alt: {len(experiments)} "
            f"({len(done)} afsluttet).",
        ]
        if active:
            lines.append(
                f"Aktuelt skridt: {active[-1]['experiment_type']} er under "
                "måling."
            )
        elif progress["status"] == "awaiting_confirmation":
            lines.append(
                "Projektet ser ud til at være fuldført og afventer din "
                "bekræftelse."
            )
        elif progress["goal_reached"]:
            lines.append("Målet er nået.")
        return " ".join(lines)

    # -- helpers ------------------------------------------------------------

    def _enqueue_next(self, website_id: str, target_url: str) -> Any:
        if self.preparation is None:
            raise ValueError(
                "Et forberedelses-led er påkrævet for at oprette eksperimenter."
            )
        return self.preparation.prepare_next(
            website_id, only_url=target_url
        ).item

    def _project_experiments(
        self, project: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Experiments on the project's URL, started at or after it began."""
        started_floor = str(project.get("created_at") or "")
        rows = [
            item for item in self.database.get_seo_experiments(
                target_url=project["target_url"]
            )
            if str(item.get("started_at") or item.get("created_at") or "")
            >= started_floor
        ]
        return sorted(rows, key=lambda item: str(item.get("started_at") or ""))

    def _goal_reached(self, project: dict[str, Any]) -> bool:
        goal_metric = project.get("goal_metric")
        target_url = project["target_url"]
        if goal_metric == "commission":
            revenue = revenue_by_page(self.database.get_commission_records())
            return revenue.get(page_key_for_url(target_url), 0.0) > 0
        if goal_metric == "position":
            position = self._latest_position(target_url)
            return position is not None and position <= POSITION_GOAL_MAX
        return False

    def _latest_position(self, target_url: str) -> float | None:
        rows = self.database.get_search_console_dimensions(
            "page", page_url=target_url
        )
        if not rows:
            return None
        latest = max(rows, key=lambda row: str(row.get("period_end") or ""))
        return float(latest.get("average_position") or 0) or None

    def _exhausted(self, target_url: str) -> bool:
        return any(
            str(row.get("status")) == "Kræver ny strategi"
            for row in self.database.get_seo_url_status(target_url)
        )


__all__ = ["SEOProjectService"]
