"""Project Manager agent for turning projects into executable tasks."""

from math import ceil
from typing import Any

from core.database import Database
from core.task_engine import MAX_TASK_MINUTES, TaskEngine
from core.website_registry import WebsiteRegistry


ROBOTLAND_PROJECT = "Redesign af Robotland.dk"
ROBOTLAND_SUBPROJECTS = (
    "Analyse og plan",
    "Fælles layout",
    "Forside",
    "Kategorisider",
    "Artikler og produktsider",
    "Test og lancering",
)


class ProjectManager:
    """Plan projects, split large work, and select executable next tasks."""

    def __init__(
        self,
        task_engine: TaskEngine,
        website_registry: WebsiteRegistry,
        database: Database,
    ) -> None:
        if task_engine.database is not database:
            raise ValueError("TaskEngine og ProjectManager skal dele database.")
        if website_registry.database is not database:
            raise ValueError("WebsiteRegistry og ProjectManager skal dele database.")
        self.task_engine = task_engine
        self.website_registry = website_registry
        self.database = database

    def create_project(
        self,
        website_id: str,
        title: str,
        description: str,
        priority: str,
        expected_effect: str,
    ) -> int:
        """Create a ready project for a registered website."""
        website = self.website_registry.get(website_id)
        if website is None:
            raise ValueError(f"Website findes ikke: {website_id}")
        return self.task_engine.create_project(
            website_id=website["website"],
            title=title,
            description=description,
            status="ready",
            priority=priority,
            expected_effect=expected_effect,
        )

    def divide_project(
        self,
        project_id: int,
        subprojects: list[tuple[str, str]],
    ) -> list[int]:
        """Create ordered subprojects from a project plan."""
        return [
            self.task_engine.create_subproject(
                project_id=project_id,
                title=title,
                description=description,
                sequence=sequence,
                status="ready",
            )
            for sequence, (title, description) in enumerate(
                subprojects, start=1
            )
        ]

    def create_concrete_task(
        self,
        *,
        subproject_id: int,
        website_id: str,
        title: str,
        description: str,
        reason: str,
        assigned_agent: str,
        estimated_minutes: int,
        expected_effect: str,
        priority_score: int,
        depends_on_task_id: int | None = None,
    ) -> list[int]:
        """Create one task or split work exceeding 120 minutes into a chain."""
        if estimated_minutes <= MAX_TASK_MINUTES:
            return [
                self.task_engine.create_task(
                    subproject_id=subproject_id,
                    website_id=website_id,
                    title=title,
                    description=description,
                    reason=reason,
                    assigned_agent=assigned_agent,
                    estimated_minutes=estimated_minutes,
                    expected_effect=expected_effect,
                    priority_score=priority_score,
                    depends_on_task_id=depends_on_task_id,
                )
            ]

        number_of_parts = ceil(estimated_minutes / MAX_TASK_MINUTES)
        base_minutes, remainder = divmod(estimated_minutes, number_of_parts)
        task_ids: list[int] = []
        dependency = depends_on_task_id
        for part in range(1, number_of_parts + 1):
            minutes = base_minutes + (1 if part <= remainder else 0)
            task_id = self.task_engine.create_task(
                subproject_id=subproject_id,
                website_id=website_id,
                title=f"{title} (del {part}/{number_of_parts})",
                description=(
                    f"{description}\n\nDel {part} af {number_of_parts}."
                ),
                reason=reason,
                assigned_agent=assigned_agent,
                estimated_minutes=minutes,
                expected_effect=expected_effect,
                priority_score=priority_score,
                depends_on_task_id=dependency,
            )
            task_ids.append(task_id)
            dependency = task_id
        return task_ids

    def choose_next_task(
        self, project_id: int | None = None
    ) -> dict[str, Any] | None:
        """Choose the next concrete task with satisfied dependencies."""
        return self.task_engine.get_next_task(project_id)

    def ensure_robotland_test_project(self) -> int:
        """Create the Robotland redesign plan once and return its project ID."""
        project_id = self.create_project(
            website_id="robotland.dk",
            title=ROBOTLAND_PROJECT,
            description=(
                "Planlæg og gennemfør et samlet redesign af Robotland.dk."
            ),
            priority="high",
            expected_effect="Bedre brugeroplevelse og højere affiliateindtægt.",
        )
        subproject_ids = self.divide_project(
            project_id,
            [
                (title, f"Arbejde relateret til {title.lower()}.")
                for title in ROBOTLAND_SUBPROJECTS
            ],
        )

        existing_titles = {
            task["title"]
            for task in self.task_engine.get_tasks_for_project(project_id)
        }
        initial_tasks = (
            {
                "title": "Gennemgå den nuværende header og noter problemer",
                "description": (
                    "Gennemgå desktop og mobil og dokumentér konkrete problemer."
                ),
                "reason": (
                    "Den nuværende header skal forstås, før en ny løsning tegnes."
                ),
                "assigned_agent": "Webmaster",
                "estimated_minutes": 45,
                "expected_effect": "Et dokumenteret grundlag for redesign.",
                "priority_score": 100,
            },
            {
                "title": "Lav forslag til ny navigation",
                "description": (
                    "Udarbejd et konkret forslag til informationsarkitektur."
                ),
                "reason": (
                    "Navigationen skal gøre produkter og indhold lettere at finde."
                ),
                "assigned_agent": "UX Designer",
                "estimated_minutes": 60,
                "expected_effect": "En enklere og tydeligere navigation.",
                "priority_score": 90,
            },
            {
                "title": "Definér krav til en ny header",
                "description": (
                    "Beskriv funktionelle og visuelle krav til den nye header."
                ),
                "reason": (
                    "Klare krav reducerer fejl og omarbejde i implementeringen."
                ),
                "assigned_agent": "Project Manager",
                "estimated_minutes": 60,
                "expected_effect": "Et implementerbart kravgrundlag.",
                "priority_score": 80,
            },
        )

        dependency: int | None = None
        existing_tasks = {
            task["title"]: task
            for task in self.task_engine.get_tasks_for_project(project_id)
        }
        for task in initial_tasks:
            if task["title"] in existing_titles:
                dependency = existing_tasks[task["title"]]["id"]
                continue
            created = self.create_concrete_task(
                subproject_id=subproject_ids[0],
                website_id="robotland.dk",
                depends_on_task_id=dependency,
                **task,
            )
            dependency = created[-1]
        return project_id
