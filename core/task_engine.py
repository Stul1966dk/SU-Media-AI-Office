"""Project and task lifecycle rules for SU Media AI Office."""

from datetime import datetime
from typing import Any

from .database import Database


VALID_STATUSES = {
    "planning",
    "ready",
    "in_progress",
    "blocked",
    "completed",
    "cancelled",
}
MAX_TASK_MINUTES = 120


class TaskEngine:
    """Create and manage projects, subprojects, tasks, and dependencies."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_project(
        self,
        website_id: str,
        title: str,
        description: str,
        status: str = "planning",
        priority: str = "middle",
        expected_effect: str = "",
    ) -> int:
        """Create a project and return its stable database ID."""
        self._validate_status(status)
        return self.database.create_project_record(
            {
                "website_id": website_id,
                "title": title,
                "description": description,
                "status": status,
                "priority": priority,
                "expected_effect": expected_effect,
                "created_at": self._now(),
            }
        )

    def create_subproject(
        self,
        project_id: int,
        title: str,
        description: str,
        sequence: int,
        status: str = "planning",
    ) -> int:
        """Create an ordered subproject."""
        self._validate_status(status)
        if self.get_project(project_id) is None:
            raise ValueError(f"Projekt {project_id} findes ikke.")
        return self.database.create_subproject_record(
            {
                "project_id": project_id,
                "title": title,
                "description": description,
                "status": status,
                "sequence": sequence,
                "created_at": self._now(),
            }
        )

    def create_task(
        self,
        subproject_id: int,
        website_id: str,
        title: str,
        description: str,
        reason: str,
        assigned_agent: str,
        estimated_minutes: int,
        expected_effect: str,
        priority_score: int,
        status: str = "ready",
        depends_on_task_id: int | None = None,
        measurement_method: str = "",
    ) -> int:
        """Create one executable task of at most 120 minutes."""
        self._validate_status(status)
        if not 1 <= estimated_minutes <= MAX_TASK_MINUTES:
            raise ValueError("En konkret opgave skal vare 1-120 minutter.")
        if depends_on_task_id is not None and self.database.get_task_record(
            depends_on_task_id
        ) is None:
            raise ValueError(
                f"Afhængighedsopgave {depends_on_task_id} findes ikke."
            )
        return self.database.create_task_record(
            {
                "subproject_id": subproject_id,
                "website_id": website_id,
                "title": title,
                "description": description,
                "reason": reason,
                "assigned_agent": assigned_agent,
                "estimated_minutes": estimated_minutes,
                "expected_effect": expected_effect,
                "measurement_method": measurement_method,
                "priority_score": priority_score,
                "status": status,
                "depends_on_task_id": depends_on_task_id,
                "created_at": self._now(),
            }
        )

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        """Return one project."""
        return self.database.get_project_record(project_id)

    def get_tasks_for_project(self, project_id: int) -> list[dict[str, Any]]:
        """Return all tasks belonging to a project."""
        return self.database.get_task_records_for_project(project_id)

    def get_next_task(
        self, project_id: int | None = None
    ) -> dict[str, Any] | None:
        """Return the highest-priority ready task with met dependencies."""
        tasks = self.database.get_task_records_for_project(project_id)
        by_id = {task["id"]: task for task in tasks}
        eligible = []
        for task in tasks:
            if task["status"] != "ready":
                continue
            dependency_id = task["depends_on_task_id"]
            if dependency_id is not None:
                dependency = by_id.get(dependency_id)
                if dependency is None:
                    dependency = self.database.get_task_record(dependency_id)
                if dependency is None or dependency["status"] != "completed":
                    continue
            eligible.append(task)

        if not eligible:
            return None
        return sorted(
            eligible,
            key=lambda task: (
                -task["priority_score"],
                task["subproject_sequence"],
                task["id"],
            ),
        )[0]

    def start_task(self, task_id: int) -> None:
        """Mark an eligible ready task as in progress."""
        task = self.database.get_task_record(task_id)
        if task is None:
            raise ValueError(f"Opgave {task_id} findes ikke.")
        if task["status"] != "ready":
            raise ValueError("Kun en ready-opgave kan startes.")
        dependency_id = task["depends_on_task_id"]
        if dependency_id is not None:
            dependency = self.database.get_task_record(dependency_id)
            if dependency is None or dependency["status"] != "completed":
                raise ValueError("Opgavens afhængighed er ikke færdig.")
        self.database.update_task_status(
            task_id,
            "in_progress",
            started_at=self._now(),
        )

    def complete_task(self, task_id: int) -> None:
        """Mark an in-progress task as completed."""
        task = self.database.get_task_record(task_id)
        if task is None:
            raise ValueError(f"Opgave {task_id} findes ikke.")
        if task["status"] != "in_progress":
            raise ValueError("Kun en igangværende opgave kan færdigmarkeres.")
        self.database.update_task_status(
            task_id,
            "completed",
            completed_at=self._now(),
        )

    def block_task(self, task_id: int) -> None:
        """Mark a non-final task as blocked."""
        task = self.database.get_task_record(task_id)
        if task is None:
            raise ValueError(f"Opgave {task_id} findes ikke.")
        if task["status"] in {"completed", "cancelled"}:
            raise ValueError("En afsluttet opgave kan ikke blokeres.")
        self.database.update_task_status(task_id, "blocked")

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Ugyldig status: {status}")

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")
