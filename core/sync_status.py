"""Read-only formatting of persisted synchronization status."""

from __future__ import annotations

import re
from typing import Any


INTEGRATIONS = (
    ("partner_ads", "Partner Ads", "Partner Ads"),
    ("search_console_daily", "Search Console dagstal", "Search Console-dagstal"),
    (
        "search_console_dimensions",
        "Search Console dimensioner",
        "Search Console-sider og søgeord",
    ),
    ("plausible", "Plausible", "Plausible"),
    ("derived", "Afledte beregninger", None),
    ("openai", "OpenAI systemstatus", "Systemstatus"),
)
SECRET_KEYS = ("token", "api_key", "apikey", "credential", "authorization")
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*\b"),
)


def load_sync_status(database: Any) -> dict[str, Any]:
    """Build one display model exclusively from already persisted data."""
    refresh = database.get_last_data_refresh_result() or {}
    feature_runs = database.get_feature_runs()
    health = database.get_dashboard_system_health()
    openai_cache = database.get_openai_health_cache()
    steps = {
        str(step.get("step")): step
        for step in refresh.get("steps", [])
        if isinstance(step, dict)
    }
    items = [
        _integration_item(
            key, label, step_name, steps, feature_runs, health, openai_cache
        )
        for key, label, step_name in INTEGRATIONS
    ]
    return {
        "overall_status": _overall_status(items),
        "items": items,
        "last_refresh_started": refresh.get("started_at"),
        "last_refresh_completed": refresh.get("completed_at"),
    }


def _integration_item(
    key: str,
    label: str,
    step_name: str | None,
    steps: dict[str, dict[str, Any]],
    feature_runs: dict[str, dict[str, Any]],
    health: dict[str, dict[str, Any]],
    openai_cache: dict[str, Any] | None,
) -> dict[str, Any]:
    if key == "derived":
        names = ("SEO History", "Website Intelligence",
                 "SEO-eksperimentovervågning", "Prioriteringsscore")
        parts = [steps[name] for name in names if name in steps]
        item = _combined_derived(label, parts)
        runs = [feature_runs.get(f"data_refresh:{name}") for name in names]
        runs = [run for run in runs if run]
        if runs:
            item["last_attempt"] = max(
                (run.get("completed_at") or run.get("started_at") or "")
                for run in runs
            ) or None
        return sanitize_status(item)
    if key == "openai":
        return sanitize_status(_openai_item(label, health, openai_cache))
    step = steps.get(step_name or "")
    run = feature_runs.get(f"data_refresh:{step_name}")
    return sanitize_status(_step_item(key, label, step, run))


def _step_item(
    key: str, label: str, step: dict[str, Any] | None,
    run: dict[str, Any] | None,
) -> dict[str, Any]:
    values = step or {}
    details_key = (
        "property_results" if key.startswith("search_console")
        else "website_results" if key == "plausible" else None
    )
    details = values.get(details_key, []) if details_key else []
    errors = _error_count(values, details)
    status = _status_label(values.get("status"), errors, bool(step or run))
    last_attempt = (
        (run or {}).get("completed_at") or (run or {}).get("started_at")
    )
    return {
        "key": key,
        "label": label,
        "status": status,
        "last_attempt": last_attempt,
        "last_success": last_attempt if status in {
            "Gennemført", "Gennemført med advarsler", "Sprunget over"
        } else None,
        "import_type": (
            values.get("import_type") or values.get("import_mode")
            or values.get("refresh_mode")
        ),
        "start_date": values.get("start_date") or values.get("period_start"),
        "end_date": values.get("end_date") or values.get("period_end"),
        "processed": _first(values, "properties_processed",
                            "websites_attempted", "websites_processed",
                            "fetched"),
        "failed": errors or None,
        "rows_created": _first(
            values, "rows_created", "records_created", "new"
        ),
        "rows_updated": _first(
            values, "rows_updated", "records_updated", "updated"
        ),
        "skipped": _first(values, "properties_skipped", "websites_skipped",
                          "objects_skipped"),
        "next_update": values.get("next_update_at"),
        "message": values.get("error_message") or _first_error(values, details),
        "details": details if isinstance(details, list) else [],
    }


def _combined_derived(label: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    if not parts:
        status = "Ikke kørt endnu"
    elif any(part.get("status") == "error" for part in parts):
        status = "Fejlet"
    elif any(part.get("status") == "skipped" for part in parts):
        status = "Sprunget over"
    else:
        status = "Gennemført"
    return {
        "key": "derived", "label": label, "status": status,
        "last_attempt": None, "last_success": None,
        "processed": sum(int(_first(x, "websites_processed",
                                    "objects_processed") or 0) for x in parts),
        "failed": sum(_error_count(x, []) for x in parts) or None,
        "rows_created": sum(int(x.get("rows_created", 0) or 0) for x in parts),
        "rows_updated": sum(int(x.get("rows_updated", 0) or 0) for x in parts),
        "skipped": sum(int(_first(x, "websites_skipped",
                                  "objects_skipped") or 0) for x in parts),
        "details": [],
    }


def _openai_item(
    label: str, health: dict[str, dict[str, Any]],
    cache: dict[str, Any] | None,
) -> dict[str, Any]:
    state = cache or {}
    detail = health.get("openai", {})
    has_data = bool(state or detail.get("checked_at"))
    is_ok = state.get("is_ok", detail.get("is_ok"))
    return {
        "key": "openai", "label": label,
        "status": (
            "Ikke kørt endnu" if not has_data
            else "Gennemført" if is_ok else "Fejlet"
        ),
        "last_attempt": state.get("last_attempt") or detail.get("checked_at"),
        "last_success": state.get("last_success"),
        "next_update": state.get("next_test_at"),
        "message": None if is_ok else (
            detail.get("detail") or state.get("detail")
        ),
        "error_type": state.get("error_type") or detail.get("error_type"),
        "details": [],
    }


def _status_label(raw: Any, errors: int, has_data: bool) -> str:
    if not has_data:
        return "Ikke kørt endnu"
    if raw in {"error", "failed", "failure"}:
        return "Fejlet"
    if raw in {"warning", "completed_with_warnings"}:
        return "Gennemført med advarsler"
    if raw in {"skipped", "skip"}:
        return "Sprunget over"
    if errors:
        return "Gennemført med advarsler"
    return "Gennemført"


def _overall_status(items: list[dict[str, Any]]) -> str:
    statuses = {item["status"] for item in items}
    if statuses == {"Ikke kørt endnu"}:
        return "Ingen synkronisering er kørt endnu"
    if "Fejlet" in statuses:
        return "En eller flere integrationer fejler"
    if "Gennemført med advarsler" in statuses:
        return "Synkronisering gennemført med advarsler"
    return "Alle integrationer fungerer"


def _error_count(values: dict[str, Any], details: list[Any]) -> int:
    count = int(_first(values, "properties_failed", "websites_failed",
                       "objects_failed", "telegram_errors") or 0)
    api_errors = values.get("api_errors")
    if isinstance(api_errors, list):
        count += len(api_errors)
    if count:
        return count
    return sum(
        isinstance(item, dict)
        and item.get("status") in {"error", "failed"}
        for item in details
    )


def _first(values: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in values and values[key] is not None:
            return values[key]
    return None


def _first_error(values: dict[str, Any], details: list[Any]) -> Any:
    errors = values.get("errors")
    if isinstance(errors, list) and errors:
        return errors[0]
    for detail in details:
        if isinstance(detail, dict) and detail.get("status") == "error":
            return detail.get("error") or detail.get("reason")
    return None


def sanitize_status(value: Any) -> Any:
    """Remove secret-bearing fields and common credential patterns."""
    if isinstance(value, dict):
        return {
            key: sanitize_status(item)
            for key, item in value.items()
            if not any(secret in key.lower() for secret in SECRET_KEYS)
        }
    if isinstance(value, list):
        return [sanitize_status(item) for item in value]
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            value = pattern.sub("[skjult]", value)
    return value
