"""Shared classification for data-refresh steps and aggregate results."""

from __future__ import annotations

from typing import Any


STATUSES = {"success", "warning", "error", "skipped"}
CENTRAL_DATA_STEPS = {
    "Partner Ads",
    "Search Console-dagstal",
    "Search Console-sider og søgeord",
    "Plausible",
}
STATUS_LABELS = {
    "success": "Gennemført",
    "warning": "Gennemført med advarsler",
    "error": "Fejlet",
    "skipped": "Sprunget over",
}


def classify_step(values: dict[str, Any]) -> str:
    """Classify one completed step from its persisted aggregate counts."""
    raw = values.get("status") or values.get("overall_status")
    if raw in {"skipped", "skip"}:
        return "skipped"
    if raw in {"error", "failed", "failure"}:
        return "error"
    if values.get("error") and not _count(
        values, "properties_processed", "websites_processed",
        "objects_processed",
    ):
        return "error"

    failed = _count(values, "failed", "properties_failed",
                    "websites_failed", "objects_failed")
    warned = _count(values, "warned", "warnings", "telegram_errors")
    succeeded = _count(
        values, "succeeded", "properties_processed", "websites_processed",
        "websites_updated", "objects_processed", "checks_succeeded",
    )
    if raw in {"warning", "completed_with_warnings"} or warned:
        return "warning" if succeeded or not failed else "error"
    if failed:
        return "warning" if succeeded else "error"
    return "success"


def normalize_step(
    step: str, status: str, values: dict[str, Any],
) -> dict[str, Any]:
    """Add the common counters without removing source-specific fields."""
    status = status if status in STATUSES else classify_step({
        **values, "status": status,
    })
    processed = _count(
        values, "processed", "properties_processed", "websites_attempted",
        "websites_processed", "objects_processed", "checks", "fetched",
    )
    failed = _count(values, "failed", "properties_failed",
                    "websites_failed", "objects_failed", "checks_failed")
    warned = _count(values, "warned", "warnings", "telegram_errors")
    skipped = _count(values, "skipped", "properties_skipped",
                     "websites_skipped", "objects_skipped")
    succeeded = _count(
        values, "succeeded", "properties_processed", "websites_updated",
        "websites_processed", "objects_processed", "checks_succeeded",
    )
    if status == "success" and not succeeded and processed:
        succeeded = max(0, processed - failed - skipped)
    if status == "warning" and not warned:
        warned = max(1, failed)
    if status == "error" and not failed:
        failed = max(1, processed)
    if status == "skipped" and not skipped:
        skipped = 1
    errors = values.get("errors")
    warnings = values.get("warnings")
    normalized_errors = errors if isinstance(errors, list) else []
    normalized_warnings = warnings if isinstance(warnings, list) else []
    if status == "error" and not normalized_errors:
        normalized_errors = [{
            "error_type": values.get("error_type"),
            "message": values.get("error_message") or "Trinnet fejlede.",
        }]
    if status == "warning" and not normalized_warnings:
        normalized_warnings = [{
            "message": (
                "En eller flere deloperationer gav en advarsel."
            ),
        }]
    return {
        "step": step,
        **values,
        "status": status,
        "processed": processed,
        "succeeded": succeeded,
        "warned": warned,
        "failed": failed,
        "skipped": skipped,
        "reason": values.get("reason") or values.get("skip_reason"),
        "errors": normalized_errors,
        "warnings": normalized_warnings,
    }


def summarize_steps(
    steps: list[dict[str, Any]],
    *, critical_steps: set[str] | None = None,
) -> dict[str, Any]:
    """Return aggregate status and separate counters for normalized steps."""
    statuses = [canonical_status(step) for step in steps]
    completed = statuses.count("success")
    warnings = statuses.count("warning")
    failed = statuses.count("error")
    skipped = statuses.count("skipped")
    critical = CENTRAL_DATA_STEPS if critical_steps is None else critical_steps
    central = [
        canonical_status(step)
        for step in steps if step.get("step") in critical
    ]
    central_worked = any(status in {"success", "warning"} for status in central)
    central_failed = bool(central) and not central_worked and any(
        status == "error" for status in central
    )
    if central_failed:
        overall = "error"
    elif failed or warnings:
        overall = "warning"
    elif completed:
        overall = "success"
    else:
        overall = "skipped"
    return {
        "status": overall,
        "completed_steps": completed,
        "warning_steps": warnings,
        "failed_steps": failed,
        "skipped_steps": skipped,
    }


def result_status(result: dict[str, Any] | None) -> str:
    """Read new and legacy aggregate results conservatively."""
    if not result:
        return "skipped"
    raw = result.get("status")
    if raw in STATUSES:
        return str(raw)
    warning_steps = int(result.get("warning_steps", 0) or 0)
    failed_steps = int(result.get("failed_steps", 0) or 0)
    completed_steps = int(result.get("completed_steps", 0) or 0)
    if warning_steps:
        return "warning"
    if failed_steps:
        return "warning" if completed_steps else "error"
    return "success" if completed_steps else "skipped"


def canonical_status(step: dict[str, Any]) -> str:
    """Map old per-step status names to the shared model."""
    raw = step.get("status")
    if raw == "completed":
        return classify_step({
            key: value for key, value in step.items() if key != "status"
        })
    return {
        "completed_with_warnings": "warning",
        "failed": "error",
    }.get(str(raw), str(raw) if raw in STATUSES else classify_step(step))


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, "Ikke kørt endnu")


def _count(values: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = values.get(key)
        if isinstance(value, list):
            return len(value)
        if value is not None and not isinstance(value, (dict, str)):
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return 0
