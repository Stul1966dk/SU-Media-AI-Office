"""Targeted retry of external integrations that failed in the latest refresh."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core.partner_ads_import import execute_partner_ads_check
from core.plausible_import import PlausibleImportService
from core.refresh_status import (
    classify_step, normalize_step, summarize_steps,
)
from core.sync_status import sanitize_status
from integrations.search_console_integration import SearchConsoleIntegration


STEP_DAILY = "Search Console-dagstal"
STEP_DIMENSIONS = "Search Console-sider og søgeord"
STEP_PLAUSIBLE = "Plausible"
STEP_PARTNER = "Partner Ads"


def retry_plan(refresh: dict[str, Any] | None) -> dict[str, Any]:
    """Extract only concrete failed properties and websites."""
    steps = {
        str(item.get("step")): item
        for item in (refresh or {}).get("steps", [])
        if isinstance(item, dict)
    }
    daily = _failed_properties(steps.get(STEP_DAILY))
    dimensions = _failed_properties(steps.get(STEP_DIMENSIONS))
    plausible = _failed_websites(steps.get(STEP_PLAUSIBLE))
    concrete = bool(daily or dimensions or plausible)
    return {
        "search_console_daily": daily,
        "search_console_dimensions": dimensions,
        "plausible": plausible,
        "partner_ads": (
            concrete
            and _step_failed(steps.get(STEP_PARTNER))
        ),
        "has_concrete_failures": concrete,
    }


class FailedIntegrationRetryService:
    """Retry selected external integrations without derived refresh steps."""

    def __init__(
        self, database: Any, *, project_root: Path | None = None,
        search_console: Any | None = None,
        plausible: Any | None = None,
        partner_refresh: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.database = database
        root = project_root or Path(__file__).resolve().parents[1]
        self.search_console = search_console or SearchConsoleIntegration(
            root, database
        ).search_service()
        self.plausible = plausible or PlausibleImportService(database)
        self.partner_refresh = partner_refresh or execute_partner_ads_check

    def retry(self) -> dict[str, Any]:
        previous = self.database.get_last_data_refresh_result() or {}
        plan = retry_plan(previous)
        started = datetime.now().astimezone()
        if not plan["has_concrete_failures"]:
            return {
                "status": "skipped",
                "message": "Ingen konkrete fejl kan genkøres automatisk",
                "started_at": started.isoformat(timespec="seconds"),
                "completed_at": started.isoformat(timespec="seconds"),
                "integrations": [],
            }

        integrations: list[dict[str, Any]] = []
        if plan["search_console_daily"]:
            integrations.append(self._run(
                STEP_DAILY,
                {"properties": plan["search_console_daily"]},
                lambda: asdict(self.search_console.sync_all_properties(
                    days=35,
                    property_urls=plan["search_console_daily"],
                    force_full_refresh=False,
                )),
            ))
        if plan["search_console_dimensions"]:
            integrations.append(self._run(
                STEP_DIMENSIONS,
                {"properties": plan["search_console_dimensions"]},
                lambda: asdict(self.search_console.sync_dimensions(
                    property_urls=plan["search_console_dimensions"],
                    force_dimensions_refresh=True,
                )),
            ))
        if plan["plausible"]:
            integrations.append(self._run(
                STEP_PLAUSIBLE,
                {"websites": plan["plausible"]},
                lambda: self.plausible.import_active_websites(
                    website_ids=plan["plausible"],
                    force_full_refresh=False,
                ),
            ))
        if plan["partner_ads"]:
            integrations.append(self._run(
                STEP_PARTNER, {},
                lambda: self.partner_refresh(
                    self.database, force_full_refresh=False
                ),
            ))

        completed = datetime.now().astimezone()
        summary = summarize_steps(integrations)
        result = sanitize_status({
            **summary,
            "started_at": started.isoformat(timespec="seconds"),
            "completed_at": completed.isoformat(timespec="seconds"),
            "integrations": integrations,
        })
        self._persist(result, previous)
        return result

    def _run(
        self, name: str, scope: dict[str, Any],
        action: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            values = action()
        except Exception as error:
            values = {
                "error_type": type(error).__name__,
                "error_message": "Integrationen kunne ikke genkøres.",
            }
            status = "error"
        else:
            values = _safe_integration_values(values)
            status = classify_step(values)
        return sanitize_status(normalize_step(
            name, status, {**scope, **values}
        ))

    def _persist(
        self, result: dict[str, Any], previous: dict[str, Any]
    ) -> None:
        replacements = {
            item["step"]: item for item in result["integrations"]
        }
        updated = dict(previous)
        updated["steps"] = [
            replacements.get(step.get("step"), step)
            for step in previous.get("steps", [])
            if isinstance(step, dict)
        ]
        summary = summarize_steps(updated["steps"])
        updated.update(summary)
        updated["completed_at"] = result["completed_at"]
        self.database.save_data_refresh_result(sanitize_status(updated))
        if hasattr(self.database, "save_integration_retry_result"):
            self.database.save_integration_retry_result(
                result, sanitize_status(previous)
            )
        for item in result["integrations"]:
            self.database.save_feature_run(
                feature_name=f"integration_retry:{item['step']}",
                status=item["status"],
                started_at=result["started_at"],
                completed_at=result["completed_at"],
                records_processed=int(item.get("processed", 0)),
                records_created=int(item.get("rows_created", 0) or 0),
                records_updated=int(item.get("rows_updated", 0) or 0),
                error_type=item.get("error_type"),
                error_message=item.get("error_message"),
            )


def _failed_properties(step: dict[str, Any] | None) -> list[str]:
    if not step:
        return []
    values = {
        str(item.get("site_url"))
        for item in step.get("errors", [])
        if isinstance(item, dict) and item.get("site_url")
    }
    values.update(
        str(item.get("site_url"))
        for item in step.get("property_results", [])
        if isinstance(item, dict)
        and item.get("site_url")
        and item.get("status") in {"error", "failed", "warning"}
    )
    return sorted(values)


def _failed_websites(step: dict[str, Any] | None) -> list[str]:
    if not step:
        return []
    values = {
        str(item.get("website") or item.get("website_id"))
        for item in step.get("errors", [])
        if isinstance(item, dict)
        and (item.get("website") or item.get("website_id"))
    }
    values.update(
        str(item.get("website_id") or item.get("website"))
        for item in step.get("website_results", [])
        if isinstance(item, dict)
        and (item.get("website_id") or item.get("website"))
        and item.get("status") in {"error", "failed", "warning"}
    )
    return sorted(values)


def _step_failed(step: dict[str, Any] | None) -> bool:
    return bool(step and step.get("status") in {"error", "failed"})


def _safe_integration_values(values: dict[str, Any]) -> dict[str, Any]:
    """Keep identifiers and counts while replacing external error text."""
    safe = sanitize_status(values)
    for error in safe.get("errors", []):
        if isinstance(error, dict):
            error.pop("error", None)
            error["message"] = "Integrationen fejlede for elementet."
    for key in ("property_results", "website_results"):
        for item in safe.get(key, []):
            if (
                isinstance(item, dict)
                and item.get("status") in {"error", "failed", "warning"}
            ):
                item.pop("error", None)
                item["reason"] = "Integrationen fejlede for elementet."
    return safe
