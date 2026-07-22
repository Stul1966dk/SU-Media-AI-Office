"""Ordered, fault-isolated refresh of AI Office's persisted data sources."""

import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from agents.website_intelligence import WebsiteIntelligenceAgent
from core.partner_ads_import import execute_partner_ads_check
from core.search_console_service import SearchConsoleService
from core.experiment_monitoring import ExperimentMonitoringService
from core.seo_history import SEOHistory
from core.system_health import check_runtime_services
from core.website_registry import WebsiteRegistry
from integrations.search_console import SearchConsoleConnector


Progress = Callable[[str, str, dict[str, Any]], None]


class DataRefreshService:
    """Refresh persisted sources without triggering analytical AI calls."""

    STEPS = (
        "Website Registry", "Partner Ads", "Search Console-properties",
        "Search Console-dagstal", "Search Console-sider og søgeord", "SEO History",
        "Website Intelligence", "Systemstatus",
    )

    def __init__(
        self, database: Any, *, project_root: Path | None = None,
        registry: Any | None = None, partner_refresh: Callable | None = None,
        search_console: Any | None = None, seo_history: Any | None = None,
        intelligence: Any | None = None,
        health_check: Callable | None = None,
    ) -> None:
        self.database = database
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.registry = registry or WebsiteRegistry(database)
        self.partner_refresh = partner_refresh or execute_partner_ads_check
        self.search_console = search_console or SearchConsoleService(
            connector=SearchConsoleConnector(
                credentials_path=self.project_root / "credentials.json",
                token_path=self.project_root / "token.json",
            ),
            database=database, website_registry=self.registry,
            logger=logging.getLogger(__name__),
        )
        self.seo_history = seo_history or SEOHistory(database)
        self.intelligence = intelligence or WebsiteIntelligenceAgent(
            database, self.registry
        )
        self.health_check = health_check or check_runtime_services

    def refresh_all(
        self, progress: Progress | None = None,
        website_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run all refresh steps in order and skip only direct dependencies."""
        external_notify = progress or (
            lambda _step, _status, _result: None
        )
        started = datetime.now().astimezone()
        steps: list[dict[str, Any]] = []

        def notify(
            step: str, status: str, values: dict[str, Any]
        ) -> None:
            timestamp = datetime.now().astimezone().isoformat(
                timespec="seconds"
            )
            try:
                self.database.save_feature_run(
                    feature_name=f"data_refresh:{step}",
                    status=status,
                    started_at=started.isoformat(timespec="seconds"),
                    completed_at=timestamp,
                    records_processed=int(
                        values.get("properties_processed", 0)
                        or values.get("records_processed", 0)
                    ),
                    records_created=int(
                        values.get("rows_created", 0)
                        or values.get("records_created", 0)
                    ),
                    records_updated=int(
                        values.get("rows_updated", 0)
                        or values.get("records_updated", 0)
                    ),
                    error_type=values.get("error_type"),
                    error_message=values.get("error_message"),
                )
            except Exception:
                logging.getLogger(__name__).warning(
                    "Refresh-status kunne ikke gemmes for %s.", step
                )
            external_notify(step, status, values)

        registry = self._run(
            "Website Registry", self.refresh_website_registry, notify, steps
        )
        self._run("Partner Ads", self.refresh_partner_ads, notify, steps)
        properties = self._run(
            "Search Console-properties",
            self.refresh_search_console_properties, notify, steps,
        )
        if properties["status"] == "error":
            daily = self._skip(
                "Search Console-dagstal",
                "Ikke kørt, fordi Search Console-opdateringen fejlede.",
                notify, steps,
            )
        else:
            daily = self._run(
                "Search Console-dagstal",
                lambda: self.refresh_search_console(website_ids), notify, steps,
            )
        if daily["status"] != "completed":
            dimensions = self._skip(
                "Search Console-sider og søgeord",
                "Ikke kørt, fordi Search Console-opdateringen fejlede.",
                notify, steps,
            )
        else:
            dimensions = self._run(
                "Search Console-sider og søgeord",
                lambda: self.refresh_search_console_dimensions(website_ids),
                notify, steps,
            )
        if daily["status"] != "completed":
            self._skip(
                "SEO History",
                "Ikke kørt, fordi Search Console-opdateringen fejlede.",
                notify, steps,
            )
        else:
            self._run("SEO History", self.refresh_seo_history, notify, steps)
        self._run(
            "Website Intelligence", self.refresh_website_intelligence,
            notify, steps,
        )
        self._run("Systemstatus", self.refresh_system_status, notify, steps)
        completed = datetime.now().astimezone()
        result = {
            "started_at": started.isoformat(timespec="seconds"),
            "completed_at": completed.isoformat(timespec="seconds"),
            "duration_seconds": round((completed - started).total_seconds(), 1),
            "steps": steps,
            "completed_steps": sum(x["status"] == "completed" for x in steps),
            "failed_steps": sum(x["status"] == "error" for x in steps),
            "skipped_steps": sum(x["status"] == "skipped" for x in steps),
            "optional_steps": ["Website Discovery", "Content Explorer"],
        }
        try:
            self.database.save_feature_run(
                feature_name="data_refresh_all",
                status=(
                    "error" if result["failed_steps"] else "success"
                ),
                started_at=result["started_at"],
                completed_at=result["completed_at"],
                records_processed=len(steps),
                records_created=result["completed_steps"],
                records_updated=result["skipped_steps"],
                error_type=(
                    "PartialRefreshError"
                    if result["failed_steps"] else None
                ),
                error_message=(
                    f"{result['failed_steps']} trin fejlede."
                    if result["failed_steps"] else None
                ),
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "Samlet refresh-status kunne ikke gemmes."
            )
        try:
            self.database.save_data_refresh_result(result)
        except Exception:
            logging.getLogger(__name__).warning(
                "Refresh-resultatet kunne ikke gemmes."
            )
        return result

    def refresh_website_registry(self) -> dict[str, Any]:
        return asdict(self.registry.sync())

    def refresh_partner_ads(self) -> dict[str, Any]:
        return self.partner_refresh(self.database)

    def refresh_search_console_properties(self) -> dict[str, Any]:
        return asdict(self.search_console.synchronize())

    def refresh_search_console(
        self, website_ids: list[str] | None = None
    ) -> dict[str, Any]:
        return asdict(self.search_console.sync_all_properties(
            days=35, website_ids=website_ids
        ))

    def refresh_search_console_dimensions(
        self, website_ids: list[str] | None = None
    ) -> dict[str, Any]:
        result = asdict(self.search_console.sync_dimensions(
            website_ids=website_ids
        ))
        try:
            updates = ExperimentMonitoringService(
                self.database
            ).update_active_experiments()
        except Exception as error:
            # A monitoring compatibility issue must not turn a successful
            # Search Console import into a failed data refresh.
            updates = []
            result["experiment_update_error"] = type(error).__name__
        result["experiments_updated"] = len(updates)
        return result

    def refresh_seo_history(self) -> dict[str, Any]:
        results = self.seo_history.analyze_all_sites()
        return {
            "records_updated": len(results),
            "websites_updated": len({item.website for item in results}),
        }

    def refresh_website_intelligence(self) -> dict[str, Any]:
        result = self.intelligence.analyze_all_sites()
        return asdict(result)

    def refresh_system_status(self) -> dict[str, Any]:
        checks = self.health_check(project_root=self.project_root)
        for component, health in checks.items():
            self.database.set_system_health(component, health)
        return {"checks": len(checks)}

    @staticmethod
    def _run(
        name: str, function: Callable[[], dict[str, Any]], notify: Progress,
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        notify(name, "running", {})
        try:
            values = function()
        except Exception as error:
            result = {
                "step": name, "status": "error",
                "error_type": type(error).__name__,
                "error_message": str(error)[:300],
            }
        else:
            result = {"step": name, "status": "completed", **values}
        steps.append(result)
        notify(name, result["status"], result)
        return result

    @staticmethod
    def _skip(
        name: str, reason: str, notify: Progress,
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result = {"step": name, "status": "skipped", "reason": reason}
        steps.append(result)
        notify(name, "skipped", result)
        return result
