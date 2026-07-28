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
from core.plausible_diagnosis import PlausibleDiagnosisService
from core.experiment_monitoring import ExperimentMonitoringService
from core.seo_history import SEOHistory
from core.system_health import check_runtime_services
from core.refresh_status import classify_step, normalize_step, summarize_steps
from core.search_console_diagnosis import SearchConsoleDiagnosisService
from core.website_registry import WebsiteRegistry
from integrations.search_console_integration import SearchConsoleIntegration


Progress = Callable[[str, str, dict[str, Any]], None]


class DataRefreshService:
    """Refresh persisted sources without triggering analytical AI calls."""

    STEPS = (
        "Website Registry", "Partner Ads", "Search Console-properties",
        "Search Console-dagstal", "Search Console-sider og søgeord",
        "Plausible", "SEO History", "Website Intelligence",
        "SEO-eksperimentovervågning", "Systemstatus", "Prioriteringsscore",
    )

    def __init__(
        self, database: Any, *, project_root: Path | None = None,
        registry: Any | None = None, partner_refresh: Callable | None = None,
        search_console: Any | None = None, seo_history: Any | None = None,
        intelligence: Any | None = None,
        plausible_import: Any | None = None,
        plausible_diagnosis: Any | None = None,
        search_diagnosis: Any | None = None,
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
        self.plausible_diagnosis = (
            plausible_diagnosis or PlausibleDiagnosisService(database)
        )
        self.search_diagnosis = (
            search_diagnosis
            or SearchConsoleDiagnosisService(database, self.search_console)
        )
        self.health_check = health_check or check_runtime_services

    def refresh_all(
        self, progress: Progress | None = None,
        website_ids: list[str] | None = None,
        *, force_dimensions_refresh: bool = False,
        force_derived_refresh: bool = False,
        force_system_check: bool = False,
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
        if daily["status"] not in {"success", "warning"}:
            dimensions = self._skip(
                "Search Console-sider og søgeord",
                "Ikke kørt, fordi Search Console-opdateringen fejlede.",
                notify, steps,
            )
        else:
            dimensions = self._run(
                "Search Console-sider og søgeord",
                lambda: self.refresh_search_console_dimensions(
                    website_ids,
                    new_daily_website_ids={
                        str(item["website_id"])
                        for item in daily.get("property_results", [])
                        if int(item.get("rows_created", 0)) > 0
                    },
                    force_dimensions_refresh=force_dimensions_refresh,
                ),
                notify, steps,
            )
        plausible = self._run(
            "Plausible",
            lambda: self.refresh_plausible(website_ids),
            notify,
            steps,
        )
        partner = self._step_named(steps, "Partner Ads")
        changes = self._collect_input_changes(
            registry, partner, daily, dimensions, plausible
        )
        selected = (
            set(website_ids) if website_ids is not None
            else set(self.database.get_active_website_ids())
        )
        seo_websites = selected if force_derived_refresh else {
            website for website in selected
            if changes["by_website"].get(website, set())
            & {"search_console_daily", "search_console_dimensions", "plausible"}
        }
        seo_result = self._run_or_skip_derived(
            "SEO History", seo_websites,
            lambda: self.refresh_seo_history(seo_websites),
            self._sources_for(changes, seo_websites),
            force_derived_refresh, notify, steps, changes["unknown"], selected,
        )
        for website in seo_result.get("changed_websites", []):
            changes["by_website"].setdefault(website, set()).add("seo_history")
        intelligence_global = bool(
            changes["global"] & {"website_registry", "partner_ads"}
        )
        intelligence_websites = (
            selected if force_derived_refresh or intelligence_global else {
                website for website in selected
                if changes["by_website"].get(website, set())
                & {"search_console_daily", "seo_history"}
            }
        )
        intelligence_result = self._run_or_skip_derived(
            "Website Intelligence", intelligence_websites,
            lambda: self.refresh_website_intelligence(intelligence_websites),
            self._sources_for(changes, intelligence_websites),
            force_derived_refresh, notify, steps, changes["unknown"], selected,
        )
        if intelligence_result.get("data_changed"):
            changes["global"].add("website_intelligence")
        experiment_websites, due_websites = self._experiment_trigger_websites(
            selected, changes, force_derived_refresh
        )
        experiment_sources = self._sources_for(changes, experiment_websites)
        if due_websites:
            experiment_sources.add("evalueringsdato")
        experiment_result = self._run_or_skip_derived(
            "SEO-eksperimentovervågning", experiment_websites,
            lambda: self.refresh_experiment_monitoring(
                experiment_websites,
                due_only=not force_derived_refresh and not experiment_sources,
            ),
            experiment_sources, force_derived_refresh,
            notify, steps, changes["unknown"], selected,
        )
        if experiment_result.get("data_changed"):
            changes["global"].add("experiment_status")
        self._run(
            "Systemstatus",
            lambda: self.refresh_system_status(force_system_check),
            notify, steps,
        )
        priority_sources = self._priority_sources(changes, seo_result)
        self._run_or_skip_derived(
            "Prioriteringsscore",
            selected if (force_derived_refresh or priority_sources) else set(),
            lambda: self.refresh_priority_scores(website_ids),
            priority_sources, force_derived_refresh,
            notify, steps, changes["unknown"], selected,
        )
        completed = datetime.now().astimezone()
        summary = summarize_steps(steps)
        result = {
            "started_at": started.isoformat(timespec="seconds"),
            "completed_at": completed.isoformat(timespec="seconds"),
            "duration_seconds": round((completed - started).total_seconds(), 1),
            "steps": steps,
            **summary,
            "optional_steps": ["Website Discovery", "Content Explorer"],
        }
        try:
            self.database.save_feature_run(
                feature_name="data_refresh_all",
                status=result["status"],
                started_at=result["started_at"],
                completed_at=result["completed_at"],
                records_processed=len(steps),
                records_created=result["completed_steps"],
                records_updated=result["skipped_steps"],
                error_type=(
                    "PartialRefreshError"
                    if result["status"] in {"warning", "error"} else None
                ),
                error_message=(
                    f"{result['failed_steps']} trin fejlede og "
                    f"{result['warning_steps']} trin havde advarsler."
                    if result["status"] in {"warning", "error"} else None
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
        return self.partner_refresh(
            self.database, force_full_refresh=False
        )

    def refresh_search_console_properties(self) -> dict[str, Any]:
        return asdict(self.search_console.synchronize())

    def refresh_search_console(
        self, website_ids: list[str] | None = None
    ) -> dict[str, Any]:
        return asdict(self.search_console.sync_all_properties(
            days=35, website_ids=website_ids, force_full_refresh=False
        ))

    def refresh_search_console_dimensions(
        self, website_ids: list[str] | None = None, *,
        new_daily_website_ids: set[str] | None = None,
        force_dimensions_refresh: bool = False,
    ) -> dict[str, Any]:
        result = asdict(self.search_console.sync_dimensions(
            website_ids=website_ids,
            new_daily_website_ids=new_daily_website_ids,
            force_dimensions_refresh=force_dimensions_refresh,
        ))
        diagnosis_websites = (
            list(website_ids) if website_ids is not None else sorted({
                str(item.get("website_id"))
                for item in result.get("property_results", [])
                if item.get("website_id")
                and item.get("status") != "error"
            })
        )
        diagnosis = self.search_diagnosis.analyze_sites(
            diagnosis_websites
        )
        result.update({
            "diagnoses_processed": diagnosis["websites_processed"],
            "diagnoses_created": diagnosis["rows_created"],
            "diagnoses_updated": diagnosis["rows_updated"],
            "diagnoses_unchanged": diagnosis["rows_unchanged"],
        })
        return result

    def refresh_seo_history(
        self, website_ids: set[str] | None = None
    ) -> dict[str, Any]:
        websites = website_ids or set()
        results = [
            item
            for website in sorted(websites)
            for item in self.seo_history.analyze_site(website)
        ]
        changed_websites = sorted({
            item.website for item in results if item.action != "unchanged"
        })
        return {
            "data_changed": bool(changed_websites),
            "websites_processed": len(websites),
            "websites_skipped": 0,
            "websites_failed": 0,
            "processed_websites": sorted(websites),
            "changed_websites": changed_websites,
            "rows_created": sum(item.action == "created" for item in results),
            "rows_updated": sum(item.action == "updated" for item in results),
        }

    def refresh_plausible(
        self, website_ids: list[str] | None = None
    ) -> dict[str, Any]:
        result = self.plausible_import.import_active_websites(
            website_ids=website_ids,
            force_full_refresh=False,
        )
        diagnosis_websites = (
            list(website_ids) if website_ids is not None else [
                str(item["website_id"])
                for item in result.get("website_results", [])
                if item.get("website_id")
                and item.get("status") in {"completed", "skipped"}
            ]
        )
        diagnosis = self.plausible_diagnosis.analyze_sites(
            diagnosis_websites
        )
        result.update({
            "diagnoses_processed": diagnosis["websites_processed"],
            "diagnoses_created": diagnosis["rows_created"],
            "diagnoses_updated": diagnosis["rows_updated"],
            "diagnoses_unchanged": diagnosis["rows_unchanged"],
        })
        return result

    def refresh_website_intelligence(
        self, website_ids: set[str] | None = None
    ) -> dict[str, Any]:
        websites = website_ids or set()
        results = [
            self.intelligence.analyze_site(website)
            for website in sorted(websites)
        ]
        changed = [
            item for item in results
            if any((
                item.profile_action != "unchanged",
                item.statistics_action != "unchanged",
                item.history_action != "unchanged",
            ))
        ]
        return {
            "data_changed": bool(changed),
            "websites_processed": len(results),
            "websites_skipped": 0,
            "websites_failed": 0,
            "processed_websites": [item.website for item in results],
            "changed_websites": [item.website for item in changed],
            "rows_created": sum(
                item.profile_action == "created" for item in results
            ),
            "rows_updated": sum(
                item.profile_action == "updated" for item in results
            ),
        }

    def refresh_experiment_monitoring(
        self, website_ids: set[str], *, due_only: bool
    ) -> dict[str, Any]:
        updates = ExperimentMonitoringService(
            self.database
        ).update_active_experiments(
            website_ids=website_ids, due_only=due_only
        )
        return {
            "data_changed": any(
                item.get("data_changed", False) for item in updates
            ),
            "objects_processed": len(updates),
            "objects_skipped": 0,
            "objects_failed": 0,
            "processed_websites": sorted(website_ids),
            "rows_created": sum(
                bool(item.get("data_changed")) for item in updates
            ),
            "rows_updated": 0,
        }

    def refresh_system_status(
        self, force_system_check: bool = False
    ) -> dict[str, Any]:
        checks = self.health_check(
            project_root=self.project_root,
            database=self.database,
            force_openai=force_system_check,
        )
        for component, health in checks.items():
            self.database.set_system_health(component, health)
        openai = checks.get("openai", {})
        failed = sum(not bool(item.get("is_ok")) for item in checks.values())
        return {
            "checks": len(checks),
            "checks_succeeded": len(checks) - failed,
            "checks_failed": failed,
            "openai": openai,
            "openai_test_calls_executed": int(
                openai.get("openai_test_calls_executed", 0)
            ),
            "openai_test_calls_avoided": int(
                openai.get("openai_test_calls_avoided", 0)
            ),
        }

    def refresh_priority_scores(
        self, website_ids: list[str] | None = None
    ) -> dict[str, Any]:
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
            search_diagnoses=context.get("search_diagnoses", []),
            plausible_diagnoses=context.get("plausible_diagnoses", []),
            limit=None,
        )
        if website_ids is not None:
            selected = set(website_ids)
            items = [
                item for item in items
                if not item.get("website") or item.get("website") in selected
            ]
        existing = self.database.get_priority_task_scores(limit=None)
        comparable_existing = [
            {key: value for key, value in item.items() if key != "calculated_at"}
            for item in existing
        ]
        data_changed = comparable_existing != items
        saved_result = (
            self.database.replace_priority_task_scores(items)
            if data_changed else len(items)
        )
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
            "data_changed": data_changed,
            "records_updated": saved,
            "tasks_scored": saved,
            "highest_score": (
                items[0]["total_score"] if items else 0
            ),
        }

    @staticmethod
    def _step_named(
        steps: list[dict[str, Any]], name: str
    ) -> dict[str, Any]:
        return next(
            (item for item in reversed(steps) if item["step"] == name),
            {"status": "skipped"},
        )

    @staticmethod
    def _collect_input_changes(
        registry: dict[str, Any], partner: dict[str, Any],
        daily: dict[str, Any], dimensions: dict[str, Any],
        plausible: dict[str, Any],
    ) -> dict[str, Any]:
        by_website: dict[str, set[str]] = {}
        global_sources: set[str] = set()
        unknown: set[str] = set()

        def add(website: str, source: str) -> None:
            by_website.setdefault(str(website), set()).add(source)

        if any(int(registry.get(key, 0)) > 0 for key in (
            "created", "updated", "phased_out"
        )):
            global_sources.add("website_registry")
        if any(int(partner.get(key, 0)) > 0 for key in ("new", "updated")):
            global_sources.add("partner_ads")
        for item in daily.get("property_results", []):
            if int(item.get("rows_changed", item.get("rows_created", 0))) > 0:
                add(item["website_id"], "search_console_daily")
        for item in dimensions.get("property_results", []):
            if int(item.get("rows_changed", 0)) > 0:
                add(item["website_id"], "search_console_dimensions")
        for item in plausible.get("website_results", []):
            if int(item.get("rows_changed", item.get("rows_created", 0))) > 0:
                add(item["website_id"], "plausible")
        for name, result in (
            ("website_registry", registry), ("partner_ads", partner),
            ("search_console_daily", daily),
            ("search_console_dimensions", dimensions),
            ("plausible", plausible),
        ):
            if result.get("status") in {"error", "warning"}:
                unknown.add(name)
        state = (
            "data_changed"
            if by_website or global_sources
            else "unknown_due_to_error" if unknown
            else "no_data_changed"
        )
        return {
            "by_website": by_website,
            "global": global_sources,
            "unknown": unknown,
            "state": state,
        }

    @staticmethod
    def _sources_for(
        changes: dict[str, Any], websites: set[str]
    ) -> set[str]:
        sources = set(changes["global"])
        for website in websites:
            sources.update(changes["by_website"].get(website, set()))
        return sources

    def _run_or_skip_derived(
        self, name: str, websites: set[str],
        function: Callable[[], dict[str, Any]], sources: set[str],
        forced: bool, notify: Progress, steps: list[dict[str, Any]],
        unknown_sources: set[str],
        eligible_websites: set[str],
    ) -> dict[str, Any]:
        if not websites:
            if unknown_sources:
                result = normalize_step(name, "warning", {
                    "reason": (
                        "Kunne ikke afgøre ændringer, fordi en nødvendig "
                        "datakilde fejlede"
                    ),
                    "warnings": ["Nødvendig datakilde fejlede"],
                })
                steps.append(result)
                notify(name, "warning", result)
            else:
                result = self._skip(
                    name,
                    "Ingen relevante nye eller ændrede data siden seneste "
                    "beregning",
                    notify, steps,
                )
            result.update({
                "data_changed": False,
                "processed_websites": [],
                "skipped_websites": sorted(eligible_websites),
                "websites_processed": 0,
                "websites_skipped": len(eligible_websites),
                "websites_failed": 0,
                "trigger_sources": [],
                "unknown_due_to_error": bool(unknown_sources),
            })
            return result
        result = self._run(name, function, notify, steps)
        result["trigger_sources"] = sorted(
            sources | ({"tvungen genberegning"} if forced else set())
        )
        result.setdefault("data_changed", False)
        try:
            self.database.set_derived_refresh_state(name, {
                "completed_at": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
                "data_changed": result["data_changed"],
                "processed_websites": result.get("processed_websites", []),
                "trigger_sources": result["trigger_sources"],
                "status": result["status"],
            })
        except Exception:
            logging.getLogger(__name__).warning(
                "Afledt refresh-status kunne ikke gemmes for %s.", name
            )
        return result

    def _experiment_trigger_websites(
        self, selected: set[str], changes: dict[str, Any], forced: bool
    ) -> tuple[set[str], set[str]]:
        active = self.database.get_seo_experiments(statuses=(
            "approved", "running", "waiting_for_data", "ready_for_evaluation",
        ))
        today = datetime.now().astimezone().date()
        due = {
            str(item["website_id"]) for item in active
            if item.get("website_id") in selected
            and item.get("planned_evaluation_date")
            and datetime.fromisoformat(
                str(item["planned_evaluation_date"])
            ).date() <= today
        }
        changed = {
            website for website in selected
            if changes["by_website"].get(website, set())
            & {"search_console_daily", "search_console_dimensions"}
        }
        active_websites = {
            str(item["website_id"]) for item in active
            if item.get("website_id") in selected
        }
        triggered = (
            active_websites if forced else active_websites & (due | changed)
        )
        return triggered, due & active_websites

    @staticmethod
    def _priority_sources(
        changes: dict[str, Any], seo_result: dict[str, Any]
    ) -> set[str]:
        relevant = {
            "search_console_daily", "plausible", "seo_history",
            "experiment_status",
        }
        sources = set(changes["global"]) & relevant
        for website_sources in changes["by_website"].values():
            sources.update(website_sources & relevant)
        if seo_result.get("data_changed"):
            sources.add("seo_history")
        return sources

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
                "error_message": "Trinnets hovedopgave fejlede.",
            }
        else:
            status = classify_step(values)
            result = normalize_step(name, status, values)
        if result.get("status") == "error" and "processed" not in result:
            result = normalize_step(name, "error", result)
        steps.append(result)
        notify(name, result["status"], result)
        return result

    @staticmethod
    def _skip(
        name: str, reason: str, notify: Progress,
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result = normalize_step(
            name, "skipped", {"reason": reason, "skipped": 1}
        )
        steps.append(result)
        notify(name, "skipped", result)
        return result
