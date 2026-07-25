"""Pure, configurable scoring for AI Office action items."""

from __future__ import annotations

from typing import Any

from core.priority_config import PRIORITY_CONFIG


SCORE_FIELDS = (
    "plausible_score",
    "search_console_click_score",
    "ctr_score",
    "position_score",
    "seo_health_score",
    "experiment_score",
    "missing_data_score",
    "system_score",
    "existing_task_score",
)


def score_priority_item(
    item: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an item with component scores and their exact total."""
    selected = config or PRIORITY_CONFIG
    weights = selected["weights"]
    task_type = str(item.get("task_type", ""))
    scores = {field: 0.0 for field in SCORE_FIELDS}

    if task_type in {"plausible_decline", "combined_traffic_decline"}:
        decline = max(0.0, -_number(item.get("plausible_change")))
        threshold = selected["thresholds"]["plausible_decline_pct"]
        if decline >= threshold:
            scores["plausible_score"] = min(
                weights["plausible_max"],
                weights["plausible_base"]
                + (decline - threshold)
                * weights["plausible_per_percentage_point"],
            )

    if task_type in {"seo_health", "combined_traffic_decline"}:
        thresholds = selected["thresholds"]
        click_change = _optional_number(item.get("click_change"))
        if (
            click_change is not None
            and click_change
            < thresholds["search_console_click_decline_pct"]
        ):
            scores["search_console_click_score"] = min(
                weights["search_console_click_max"],
                -click_change
                * weights["search_console_click_per_percentage_point"],
            )
        ctr_change = _optional_number(item.get("ctr_change"))
        if (
            ctr_change is not None
            and ctr_change < thresholds["ctr_decline"]
        ):
            scores["ctr_score"] = min(
                weights["ctr_max"],
                -ctr_change * weights["ctr_per_percentage_point"],
            )
        position_change = _optional_number(item.get("position_change"))
        if (
            position_change is not None
            and position_change > thresholds["position_worsening"]
        ):
            scores["position_score"] = min(
                weights["position_max"],
                position_change * weights["position_per_position"],
            )
        trend = str(item.get("seo_health_trend", "")).lower()
        scores["seo_health_score"] = {
            "critical": weights["seo_health_critical"],
            "declining": weights["seo_health_declining"],
        }.get(trend, 0.0)

    if item.get("has_active_experiment"):
        scores["experiment_score"] = weights["experiment_active"]
    if task_type == "experiment_ready":
        scores["experiment_score"] = weights["experiment_ready"]
    elif task_type == "missing_search_console":
        scores["missing_data_score"] = weights["missing_search_console"]
    elif task_type == "missing_plausible":
        scores["missing_data_score"] = weights["missing_plausible"]
    elif task_type == "system_error":
        scores["system_score"] = weights["system_error"]
    elif task_type == "project_task":
        scores["existing_task_score"] = (
            max(0.0, _number(item.get("source_priority_score")))
            * weights["existing_task_multiplier"]
        )

    rounded = {key: round(value, 2) for key, value in scores.items()}
    total = round(sum(rounded.values()), 2)
    result = {**item, **rounded, "total_score": total}
    result["priority"] = priority_label(total, config=selected)
    return result


def priority_label(
    score: float,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    """Translate a total score to the existing Danish priority labels."""
    thresholds = (config or PRIORITY_CONFIG)["thresholds"]
    if score >= thresholds["critical_total_score"]:
        return "Kritisk"
    if score >= thresholds["high_total_score"]:
        return "Høj"
    if score >= thresholds["medium_total_score"]:
        return "Mellem"
    return "Lav"


def stable_priority_key(item: dict[str, Any]) -> tuple[Any, ...]:
    """Sort by score with deterministic, data-independent tie breakers."""
    return (
        -float(item.get("total_score", 0)),
        str(item.get("task_type", "")),
        str(item.get("website", "")),
        str(item.get("description", "")),
        str(item.get("task_key", "")),
    )


def _number(value: Any) -> float:
    result = _optional_number(value)
    return result if result is not None else 0.0


def _optional_number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
