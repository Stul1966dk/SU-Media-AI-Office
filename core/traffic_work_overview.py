"""Practical overview of recommendation and experiment workflow state."""

from __future__ import annotations

from typing import Any


ACTIONABLE_STAGES = {"ready_for_evaluation", "approved", "draft"}
ACTIVE_EXPERIMENT_STATUSES = {
    "running", "waiting_for_data", "ready_for_evaluation", "evaluating",
}
STAGE_ORDER = {
    "ready_for_evaluation": 0,
    "approved": 1,
    "draft": 2,
    "measurement": 3,
}


def build_traffic_work_overview(
    decisions: list[dict[str, Any]],
    experiments: list[dict[str, Any]],
    *,
    website_id: str | None = None,
) -> list[dict[str, Any]]:
    """Combine recommendation decisions and live experiments without duplicates."""
    experiments_by_id = {
        int(item["id"]): item
        for item in experiments
        if item.get("id") is not None
    }
    linked_experiments: set[int] = set()
    items: list[dict[str, Any]] = []
    for decision in decisions:
        if website_id and decision.get("website_id") != website_id:
            continue
        status = str(decision.get("status") or "")
        if status not in {"draft", "approved", "experiment_running"}:
            continue
        evidence = decision.get("evidence") or {}
        experiment_id = _optional_int(evidence.get("experiment_id"))
        experiment = (
            experiments_by_id.get(experiment_id)
            if experiment_id else None
        )
        if experiment_id:
            linked_experiments.add(experiment_id)
        item = _decision_item(decision, experiment)
        if item:
            items.append(item)
    for experiment in experiments:
        experiment_id = int(experiment["id"])
        if (
            experiment_id in linked_experiments
            or experiment.get("status") not in ACTIVE_EXPERIMENT_STATUSES
            or (
                website_id
                and experiment.get("website_id") != website_id
            )
        ):
            continue
        items.append(_experiment_item(experiment))
    return sorted(
        items,
        key=lambda item: (
            STAGE_ORDER[item["stage"]],
            str(item.get("website") or ""),
            str(item.get("title") or ""),
        ),
    )


def next_actionable_work(
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the first stage that requires an explicit user action."""
    return next(
        (item for item in items if item["stage"] in ACTIONABLE_STAGES),
        None,
    )


def _decision_item(
    decision: dict[str, Any],
    experiment: dict[str, Any] | None,
) -> dict[str, Any] | None:
    status = str(decision["status"])
    if status == "draft":
        stage = "draft"
        status_label = "Kladde klar"
        next_action = "Gennemgå og godkend opgavekladden."
        target = "pages/9_SEO.py"
        link_label = "Åbn kladden i SEO"
    elif status == "approved":
        stage = "approved"
        status_label = "Afventer implementering"
        next_action = (
            "Udfør den godkendte ændring på websitet og registrér den."
        )
        target = "pages/9_SEO.py"
        link_label = "Registrér implementeringen"
    elif experiment and experiment.get("status") == "ready_for_evaluation":
        stage = "ready_for_evaluation"
        status_label = "Klar til evaluering"
        next_action = "Evaluér resultatet af SEO-eksperimentet."
        target = "pages/13_Eksperimenter.py"
        link_label = "Åbn eksperimentet"
    elif experiment and experiment.get("status") in {
        "completed", "cancelled", "failed",
    }:
        return None
    else:
        stage = "measurement"
        status_label = "Under 28-dages måling"
        next_action = (
            "Afvent den planlagte evalueringsdato; der skal ikke ændres mere "
            "på URL'en imens."
        )
        target = "pages/13_Eksperimenter.py"
        link_label = "Følg målingen"
    return {
        "stage": stage,
        "status_label": status_label,
        "website": decision["website_id"],
        "title": decision["title"],
        "target_url": decision.get("target_url", ""),
        "next_action": next_action,
        "target": target,
        "link_label": link_label,
        "experiment_id": experiment.get("id") if experiment else None,
        "planned_evaluation_date": (
            experiment.get("planned_evaluation_date")
            if experiment else (decision.get("evidence") or {}).get(
                "planned_evaluation_date"
            )
        ),
    }


def _experiment_item(experiment: dict[str, Any]) -> dict[str, Any]:
    ready = experiment.get("status") == "ready_for_evaluation"
    return {
        "stage": "ready_for_evaluation" if ready else "measurement",
        "status_label": (
            "Klar til evaluering" if ready else "Under 28-dages måling"
        ),
        "website": experiment["website_id"],
        "title": experiment.get("change_description") or "SEO-eksperiment",
        "target_url": experiment.get("target_url", ""),
        "next_action": (
            "Evaluér resultatet af SEO-eksperimentet."
            if ready else
            "Afvent den planlagte evalueringsdato; URL'en er låst imens."
        ),
        "target": "pages/13_Eksperimenter.py",
        "link_label": (
            "Åbn eksperimentet" if ready else "Følg målingen"
        ),
        "experiment_id": experiment["id"],
        "planned_evaluation_date": experiment.get(
            "planned_evaluation_date"
        ),
    }


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
