"""Safe draft and decision workflow for traffic recommendations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.seo_experiment_engine import SEOExperimentEngine
from core.traffic_recommendation_store import (
    find_open_task_by_title,
    get_decision,
    upsert_decision,
)


VALID_STATUSES = {
    "draft", "approved", "experiment_running", "snoozed", "rejected",
}
EXPERIMENT_TYPES = {
    "title_meta", "internal_links", "content_update", "technical_fix", "schema",
}


class TrafficRecommendationWorkflow:
    """Persist user decisions without creating an operational task."""

    def __init__(
        self, database: Any, *, experiment_engine: Any | None = None
    ) -> None:
        self.database = database
        self.experiments = experiment_engine or SEOExperimentEngine(database)

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
        existing_task = find_open_task_by_title(
            self.database,
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

    def approve_draft(self, recommendation_key: str) -> dict[str, Any]:
        """Lock an edited draft as the user's approved change plan."""
        decision = self._required(recommendation_key)
        if decision["status"] == "approved":
            return decision
        if decision["status"] != "draft":
            raise ValueError("Kun en gemt opgavekladde kan godkendes.")
        return self._save_existing(
            decision,
            status="approved",
            evidence_updates={
                "approved_at": self._timestamp(),
            },
        )

    def mark_implemented(
        self,
        recommendation_key: str,
        *,
        change_description: str,
        experiment_type: str,
    ) -> dict[str, Any]:
        """Register a manual change and start its measured SEO experiment."""
        decision = self._required(recommendation_key)
        evidence = dict(decision.get("evidence") or {})
        existing_id = evidence.get("experiment_id")
        if decision["status"] == "experiment_running" and existing_id:
            existing = self.database.get_seo_experiment(int(existing_id))
            if existing:
                return existing
        if decision["status"] != "approved":
            raise ValueError("Opgavekladden skal godkendes før implementering.")
        clean_description = change_description.strip()
        if not clean_description:
            raise ValueError("Beskriv præcist, hvad du har ændret på websitet.")
        if experiment_type not in EXPERIMENT_TYPES:
            raise ValueError("Vælg en gyldig ændringstype.")
        target_url = str(decision.get("target_url", "")).strip()
        target_query = str(evidence.get("target_query") or "").strip()
        # Preflight before creating anything, so a missing baseline cannot
        # leave behind a planned experiment that locks the URL.
        self.experiments.calculate_baseline(
            str(decision["website_id"]), target_url, target_query
        )
        experiment_id = self.experiments.create_experiment({
            "website": str(decision["website_id"]),
            "target_url": target_url,
            "target_query": target_query,
            "experiment_type": experiment_type,
            "experiment_goal": self._hypothesis(decision),
            "task_description": clean_description,
            "goal_metric": self._goal_metric(decision),
            "goal_direction": "increase",
            "target_change_pct": 10,
            "waiting_period_days": 28,
            "confidence": self._confidence(evidence.get("confidence")),
        })
        self.experiments.approve_experiment(experiment_id)
        experiment = self.experiments.start_experiment(experiment_id)
        self._save_existing(
            decision,
            status="experiment_running",
            description=clean_description,
            evidence_updates={
                "experiment_id": experiment_id,
                "experiment_type": experiment_type,
                "implemented_at": self._timestamp(),
                "planned_evaluation_date":
                    experiment.get("planned_evaluation_date"),
            },
        )
        return experiment

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
                    "confidence", "total_score", "target_query",
                    "measurement_method", "completion_criterion",
                )
            },
        }
        upsert_decision(self.database, values)
        return get_decision(self.database, values["recommendation_key"])

    def _save_existing(
        self,
        decision: dict[str, Any],
        *,
        status: str,
        description: str | None = None,
        evidence_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        evidence = {
            **(decision.get("evidence") or {}),
            **(evidence_updates or {}),
        }
        upsert_decision(self.database, {
            "recommendation_key": decision["recommendation_key"],
            "website_id": decision["website_id"],
            "task_type": decision["task_type"],
            "target_url": decision["target_url"],
            "measured_cause": decision["measured_cause"],
            "title": decision["title"],
            "description": (
                description
                if description is not None else decision["description"]
            ),
            "priority": decision["priority"],
            "status": status,
            "snoozed_until": None,
            "evidence": evidence,
        })
        return self._required(str(decision["recommendation_key"]))

    def _required(self, recommendation_key: str) -> dict[str, Any]:
        decision = get_decision(self.database, recommendation_key)
        if decision is None:
            raise ValueError("Opgavekladden kunne ikke findes.")
        return decision

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _confidence(value: Any) -> int:
        if isinstance(value, (int, float)):
            return max(0, min(100, int(value)))
        return {
            "høj": 85, "high": 85, "middel": 65, "medium": 65,
            "lav": 40, "low": 40,
        }.get(str(value).strip().casefold(), 60)

    @staticmethod
    def _goal_metric(decision: dict[str, Any]) -> str:
        return (
            "ctr"
            if "ctr" in str(decision.get("measured_cause", "")).casefold()
            else "clicks"
        )

    @staticmethod
    def _hypothesis(decision: dict[str, Any]) -> str:
        metric = (
            "CTR"
            if TrafficRecommendationWorkflow._goal_metric(decision) == "ctr"
            else "organiske klik"
        )
        return (
            f"{decision['title']} forventes at øge {metric} på den valgte "
            "URL i den 28-dages måleperiode."
        )
