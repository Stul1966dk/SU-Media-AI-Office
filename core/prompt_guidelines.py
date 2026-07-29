"""User-managed global and task-specific AI prompt guidelines."""

from __future__ import annotations

from typing import Any


STATE_KEY = "prompt_guidelines"
TASK_TYPES = {
    "title_meta": "Title og metabeskrivelse",
    "content_update": "Indholdsopdatering",
    "content_gap": "Content Gap",
    "internal_links": "Interne links",
    "technical_fix": "Teknisk forbedring",
    "schema": "Strukturerede data",
    "traffic_analysis": "Trafikanalyse",
    "ai_analysis": "AI-analyse",
    "executive_briefing": "Executive Briefing",
    "experiment_evaluation": "Evaluering af eksperimenter",
}


class PromptGuidelines:
    def __init__(self, database: Any) -> None:
        self.database = database

    def get(self) -> dict[str, Any]:
        state = self.database.get_integration_state(STATE_KEY) or {}
        if not isinstance(state, dict):
            state = {}
        tasks = state.get("tasks")
        return {
            "global": str(state.get("global") or ""),
            "tasks": tasks if isinstance(tasks, dict) else {},
        }

    def save(self, global_text: str, tasks: dict[str, str]) -> None:
        self.database.set_integration_state(STATE_KEY, {
            "global": str(global_text or "").strip(),
            "tasks": {
                key: str(value or "").strip()
                for key, value in tasks.items()
                if key in TASK_TYPES and str(value or "").strip()
            },
        })

    def text_for(self, task_type: str) -> str:
        state = self.get()
        parts = []
        if state["global"].strip():
            parts.append("Overordnede retningslinjer:\n" + state["global"].strip())
        task_text = str(state["tasks"].get(task_type) or "").strip()
        if task_text:
            parts.append(
                f"Retningslinjer for {TASK_TYPES.get(task_type, task_type)}:\n"
                + task_text
            )
        return "\n\n".join(parts)

    def apply(self, prompt: str, task_type: str) -> str:
        guidelines = self.text_for(task_type)
        if not guidelines:
            return prompt
        return (
            f"{prompt}\n\nBRUGERADMINISTREREDE RETNINGSLINJER "
            f"(skal overholdes):\n{guidelines}"
        )
