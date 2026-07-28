"""Safe draft and decision workflow for traffic recommendations."""

from __future__ import annotations

from datetime import date
from typing import Any


VALID_STATUSES = {"draft", "snoozed", "rejected"}


class TrafficRecommendationWorkflow:
    """Persist user decisions without creating an operational task."""

    def __init__(self, database: Any) -> None:
        self.database = database

    def create_draft(
        self,
        recommendation: dict[str, Any],
        *,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        clean_title = title.strip()
        clean_description = description.strip()
        if not clean_title:
            raise ValueError("Opgavekladden skal have en titel.")
        if not clean_description:
            raise ValueError("Opgavekladden skal have en beskrivelse.")
        existing_task = self.database.find_open_task_by_title(
            str(recommendation["website"]), clean_title
        )
        if existing_task:
            raise ValueError(
                "Der findes allerede en åben opgave med samme titel."
            )
        return self._save(
            recommendation,
            status="draft",
            title=clean_title,
            description=clean_description,
            snoozed_until=None,
        )

    def snooze(
        self, recommendation: dict[str, Any], until: date
    ) -> dict[str, Any]:
        if until <= date.today():
            raise ValueError("Udsættelsesdatoen skal ligge i fremtiden.")
        return self._save(
            recommendation,
            status="snoozed",
            title=str(recommendation["description"]),
            description=str(recommendation.get("explanation", "")),
            snoozed_until=until.isoformat(),
        )

    def reject(
        self, recommendation: dict[str, Any]
    ) -> dict[str, Any]:
        return self._save(
            recommendation,
            status="rejected",
            title=str(recommendation["description"]),
            description=str(recommendation.get("explanation", "")),
            snoozed_until=None,
        )

    def _save(
        self,
        recommendation: dict[str, Any],
        *,
        status: str,
        title: str,
        description: str,
        snoozed_until: str | None,
    ) -> dict[str, Any]:
        if status not in VALID_STATUSES:
            raise ValueError("Ugyldig anbefalingsstatus.")
        values = {
            "recommendation_key": str(recommendation["task_key"]),
            "website_id": str(recommendation["website"]),
            "task_type": str(recommendation["task_type"]),
            "target_url": str(recommendation.get("target_url", "")),
            "measured_cause": str(
                recommendation.get("measured_cause", "")
            ),
            "title": title,
            "description": description,
            "priority": str(recommendation.get("priority", "Lav")),
            "status": status,
            "snoozed_until": snoozed_until,
            "evidence": {
                key: recommendation.get(key)
                for key in (
                    "click_change", "plausible_change", "explanation",
                    "confidence", "total_score",
                )
            },
        }
        self.database.upsert_traffic_recommendation_decision(values)
        return self.database.get_traffic_recommendation_decision(
            values["recommendation_key"]
        )
