"""Ordered, fault-isolated refresh of AI Office's persisted data sources."""

import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from agents.website_intelligence import WebsiteIntelligenceAgent
from core.partner_ads_import import execute_partner_ads_check
from core.plausible_import import PlausibleImportService
from core.experiment_monitoring import ExperimentMonitoringService
from core.seo_history import SEOHistory
from core.system_health import check_runtime_services
from core.website_registry import WebsiteRegistry
from integrations.search_console_integration import SearchConsoleIntegration


Progress = Callable[[str, str, dict[str, Any]], None]


class DataRefreshService:
    """Refresh persisted sources without triggering analytical AI calls."""

    STEPS = (
        "Website Registry", "Partner Ads", "Search Console-properties",
        "Search Console-dagstal", "Search Console-sider og søgeord",
        "Plausible", "SEO History", "Website Intelligence", "Systemstatus",
        "Prioriteringsscore",
    )

    def __init__(
        self, database: Any, *, project_root: Path | None = None,
        registry: Any | None = None, partner_refresh: Callable | None = None,
        search_console: Any | None = None, seo_history: Any | None = None,
        intelligence: Any | None = None,
        plausible_import: Any | None = None,
        health_check: Callable | None = None,
    ) -> None:
        self.database = database
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        load_dotenv(self.project_root / ".env", override=False)
        self.registry = registry or WebsiteRegistry(database)
        self.partner_refresh = partner_refresh or execute_partner_ads_check
        self.search_console_integration = SearchConsoleIntegration(
            self.project_root, database
        )
        self.search_console = (
            search_console or self.search_console_integration.search_service()
        )
        self.seo_history = seo_history or SEOHistory(database)
        self.intelligence = intelligence or WebsiteIntelligenceAgent(
            database, self.registry
        )
        self.plausible_import = plausible_import or PlausibleImportService(
            database
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
                        or values.get("websites_attempted", 0)
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
        self._run(
            "Plausible",
            lambda: self.refresh_plausible(website_ids),
            notify,
            steps,
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
        self._run(
            "Prioriteringsscore", self.refresh_priority_scores, notify, steps
        )
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
            days=35, website_ids=website_ids, force_full_refresh=False
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

    def refresh_plausible(
        self, website_ids: list[str] | None = None
    ) -> dict[str, Any]:
        return self.plausible_import.import_active_websites(
            website_ids=website_ids,
            force_full_refresh=False,
        )

    def refresh_website_intelligence(self) -> dict[str, Any]:
        result = self.intelligence.analyze_all_sites()
        return asdict(result)

    def refresh_system_status(self) -> dict[str, Any]:
        checks = self.health_check(project_root=self.project_root)
        for component, health in checks.items():
            self.database.set_system_health(component, health)
        return {"checks": len(checks)}

    def refresh_priority_scores(self) -> dict[str, Any]:
        """Build and persist one deterministic snapshot after all data sync."""
        from dashboard.components.data import build_dashboard_priority_tasks

        context = self.database.get_dashboard_action_context()
        system_status = self.database.get_dashboard_system_health()
        project_tasks = self.database.get_priority_tasks(limit=1000)
        if not isinstance(context, dict):
            context = {}
        if not isinstance(system_status, dict):
            system_status = {}
        if not isinstance(project_tasks, list):
            project_tasks = []
        items = build_dashboard_priority_tasks(
            system_status=system_status,
            seo_sites=context.get("seo_health", []),
            project_tasks=project_tasks,
            experiments=context.get("experiments", []),
            active_experiments=context.get("active_experiments", []),
            coverage=context.get("coverage", []),
            plausible_rows=context.get("plausible_daily", []),
            limit=None,
        )
        saved_result = self.database.replace_priority_task_scores(items)
        saved = (
            saved_result if isinstance(saved_result, int) else len(items)
        )
        logging.getLogger(__name__).info(
            "Prioriteringsscore gemt for %s opgaver: %s",
            saved,
            [
                {
                    "task": item["description"],
                    "website": item["website"],
                    "total_score": item["total_score"],
                    "subscores": {
                        key: value for key, value in item.items()
                        if key.endswith("_score") and key != "total_score"
                    },
                }
                for item in items[:3]
            ],
        )
        return {
            "records_updated": saved,
            "tasks_scored": saved,
            "highest_score": (
                items[0]["total_score"] if items else 0
            ),
        }

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
