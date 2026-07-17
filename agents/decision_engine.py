"""Rule-based Decision Engine for SU Media AI Office."""

from dataclasses import dataclass
from typing import Any

from core.database import Database
from core.website_registry import WebsiteRegistry
from agents.project_manager import ProjectManager


PRIORITY_SCORES = {
    "high": 3,
    "middle": 2,
    "medium": 2,
    "low": 1,
}

NOTE_SCORES = {
    "needs design": 3,
    "needs content": 2,
    "high potential": 4,
    "drop": 2,
}


@dataclass(frozen=True)
class Recommendation:
    """One prioritized action returned by the Decision Engine."""

    website: str
    reason: str
    score: int
    recommended_action: str
    item_type: str = "project"
    task_id: int | None = None
    project_id: int | None = None


class DecisionEngine:
    """Select the most important website action using transparent rules."""

    def __init__(
        self,
        website_registry: WebsiteRegistry,
        database: Database,
        project_manager: ProjectManager | None = None,
    ) -> None:
        """Create an engine using the shared registry and database."""
        if website_registry.database is not database:
            raise ValueError(
                "Decision Engine og Website Registry skal bruge samme database."
            )
        self.website_registry = website_registry
        self.database = database
        self.project_manager = project_manager

    def get_top_recommendation(self) -> Recommendation | None:
        """Return a Project Manager task or a new project recommendation."""
        if self.project_manager is not None:
            task = self.project_manager.choose_next_task()
            if task is not None:
                return Recommendation(
                    website=task["website_id"],
                    reason=task["reason"],
                    score=task["priority_score"],
                    recommended_action=task["title"],
                    item_type="task",
                    task_id=task["id"],
                    project_id=task["project_id"],
                )

        candidates: list[tuple[int, dict[str, Any]]] = []
        for website in self.website_registry.get_all():
            if not website["active"] or website["status"] == "phasing_out":
                continue
            candidates.append((self._score(website), website))

        if not candidates:
            return None

        score, website = sorted(
            candidates,
            key=lambda candidate: (
                -candidate[0],
                candidate[1]["website"],
            ),
        )[0]
        return Recommendation(
            website=website["display_name"] or website["website"],
            reason=self._reason(website),
            score=score,
            recommended_action=self._recommended_action(website["notes"]),
        )

    @staticmethod
    def _score(website: dict[str, Any]) -> int:
        score = PRIORITY_SCORES.get(website["priority"].lower(), 0)
        if website["monetized"]:
            score += 2

        notes = website["notes"].lower()
        score += sum(
            points for phrase, points in NOTE_SCORES.items() if phrase in notes
        )
        return score

    @staticmethod
    def _recommended_action(notes: str) -> str:
        normalized = notes.lower()
        if "needs design" in normalized:
            return "Opdater design"
        if "needs content" in normalized:
            return "Opdater indhold"
        if "drop" in normalized:
            return "Analysér fald i performance"
        if "high potential" in normalized:
            return "Udarbejd vækstplan"
        return "Gennemgå website"

    @staticmethod
    def _reason(website: dict[str, Any]) -> str:
        reasons: list[str] = []
        priority = website["priority"].lower()
        if priority == "high":
            reasons.append("høj prioritet")
        elif priority in {"middle", "medium"}:
            reasons.append("mellem prioritet")
        elif priority == "low":
            reasons.append("lav prioritet")

        if website["monetized"]:
            reasons.append("websitet er monetized")

        notes = website["notes"].lower()
        note_reasons = {
            "needs design": "noten angiver behov for designopdatering",
            "needs content": "noten angiver behov for indholdsopdatering",
            "high potential": "noten angiver højt potentiale",
            "drop": "noten angiver et fald",
        }
        reasons.extend(
            description
            for phrase, description in note_reasons.items()
            if phrase in notes
        )

        if not reasons:
            return "Websitet bør gennemgås."
        if len(reasons) == 1:
            return f"{reasons[0].capitalize()}."
        return f"{', '.join(reasons[:-1]).capitalize()} og {reasons[-1]}."
