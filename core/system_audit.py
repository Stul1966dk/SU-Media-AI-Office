"""Read-only integrity audit and explicitly invoked safe repairs."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from core.action_logging import log_action
from core.seo_experiment_engine import LOCKED_STATUSES, SEOExperimentEngine
from core.website_registry import WebsiteRegistry
from core.work_queue_service import WorkQueueService


REQUIRED_APPROVED_CHANGE_FIELDS = (
    "website_id", "target_url", "change_type", "current_title",
    "approved_title", "current_meta", "approved_meta", "hypothesis",
    "reason", "expected_effect", "approved_at", "status", "project_id",
    "task_id", "experiment_id",
)


class SystemIntegrityAudit:
    """Report cross-table integrity problems without changing data."""

    def __init__(self, database: Any, logger: logging.Logger | None = None):
        self.database = database
        self.logger = logger or logging.getLogger(__name__)
        self.experiments = SEOExperimentEngine(database)

    def run(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        queue = self.database.get_work_queue((
            "queued", "skipped", "awaiting_implementation", "implemented",
            "completed", "cancelled",
        ))
        experiments = self.database.get_seo_experiments()
        projects = self.database.get_projects()
        tasks = self.database.get_task_records_for_project()
        approved = self.database.get_approved_changes()

        for item in queue:
            if (
                item["status"] == "awaiting_implementation"
                and not self.database.get_approved_change_for_work_item(item)
            ):
                self._add(
                    findings, "critical", "approved_task_without_change",
                    "Godkendt køopgave mangler Approved Change.",
                    queue_id=item["id"], url=item["target_url"],
                )

        for item in approved:
            missing = [
                field for field in REQUIRED_APPROVED_CHANGE_FIELDS
                if item.get(field) in (None, "")
            ]
            if missing:
                self._add(
                    findings, "critical", "approved_change_missing_fields",
                    "Approved Change mangler obligatoriske felter.",
                    approved_change_id=item["id"], fields=missing,
                    url=item["target_url"],
                )

        for item in experiments:
            if item["status"] in LOCKED_STATUSES and not all((
                item.get("baseline_start"), item.get("baseline_end"),
                item.get("baseline_impressions") is not None,
            )):
                self._add(
                    findings, "high", "active_experiment_without_baseline",
                    "Aktivt eksperiment mangler baseline.",
                    experiment_id=item["id"], url=item["target_url"],
                )
            if (
                item["status"] in LOCKED_STATUSES
                and not self.experiments.is_url_locked(item["target_url"])
            ):
                self._add(
                    findings, "critical", "active_experiment_without_lock",
                    "Aktivt eksperiment låser ikke URL'en.",
                    experiment_id=item["id"], url=item["target_url"],
                )
            if not item.get("project_id") or not item.get("task_id"):
                self._add(
                    findings, "high", "experiment_missing_relation",
                    "Eksperiment mangler projekt- eller opgavereference.",
                    experiment_id=item["id"], url=item["target_url"],
                )

        active_experiment_urls = {
            item["target_url"] for item in experiments
            if item["status"] in LOCKED_STATUSES
        }
        for draft in self.database.get_title_optimization_drafts():
            if (
                draft["status"] in {"approved", "converted_to_experiment"}
                and draft["target_url"] not in active_experiment_urls
            ):
                self._add(
                    findings, "high", "draft_lock_without_active_experiment",
                    "Titlekladde låser URL uden et aktivt eksperiment.",
                    draft_id=draft["id"], url=draft["target_url"],
                )

        approved_by_experiment = {
            item["experiment_id"]: item for item in approved
            if item.get("experiment_id")
        }
        queue_by_experiment = {
            item["experiment_id"]: item for item in queue
            if item.get("experiment_id")
        }
        for experiment in experiments:
            change = approved_by_experiment.get(experiment["id"])
            queue_item = queue_by_experiment.get(experiment["id"])
            if experiment["status"] == "waiting_for_data":
                if not change or change["status"] != "measurement_period":
                    self._add(
                        findings, "high", "status_mismatch",
                        "Eksperimentets måleperiode stemmer ikke med "
                        "Approved Change.",
                        experiment_id=experiment["id"],
                        approved_change_status=(
                            change["status"] if change else None
                        ),
                    )
                if not queue_item or queue_item["status"] != "implemented":
                    self._add(
                        findings, "high", "status_mismatch",
                        "Eksperimentets måleperiode stemmer ikke med køen.",
                        experiment_id=experiment["id"],
                        queue_status=(
                            queue_item["status"] if queue_item else None
                        ),
                    )
            if experiment["status"] == "completed":
                if change and change["status"] != "completed":
                    self._add(
                        findings, "medium", "status_mismatch",
                        "Afsluttet eksperiment har en aktiv Approved Change.",
                        experiment_id=experiment["id"],
                        approved_change_status=change["status"],
                    )

        project_ids = {item["id"] for item in projects}
        task_project_ids = {item["project_id"] for item in tasks}
        for task in tasks:
            if task["project_id"] not in project_ids:
                self._add(
                    findings, "critical", "task_without_project",
                    "Opgave peger ikke på et eksisterende projekt.",
                    task_id=task["id"], project_id=task["project_id"],
                )
        for project in projects:
            if project["id"] not in task_project_ids:
                self._add(
                    findings, "medium", "project_without_tasks",
                    "Projekt har ingen opgaver.",
                    project_id=project["id"],
                )

        self._duplicates(
            findings, queue, ("target_url", "status"),
            {"queued", "skipped", "awaiting_implementation"},
            "duplicate_active_queue_items", "Aktiv arbejdskø har dubletter.",
        )
        self._duplicates(
            findings, experiments,
            ("target_url", "baseline_start", "baseline_end"),
            set(LOCKED_STATUSES),
            "duplicate_active_baselines",
            "Aktive eksperimenter bruger en dubleret baseline på samme URL.",
        )
        self._duplicates(
            findings, tasks, ("website_id", "title", "status"),
            {"planning", "ready", "in_progress"},
            "duplicate_active_tasks", "Aktive opgaver er dubleret.",
        )

        return {
            "ok": not findings,
            "finding_count": len(findings),
            "by_severity": dict(Counter(x["severity"] for x in findings)),
            "findings": findings,
        }

    def repair_safe(self) -> dict[str, Any]:
        """Run only deterministic, non-deleting repairs with audit logging."""
        queue = WorkQueueService(
            self.database, WebsiteRegistry(self.database),
            experiment_engine=self.experiments,
        )
        repaired_approvals = queue.repair_invalid_approval_states()
        marked_for_review = 0
        for item in self.database.get_approved_changes():
            missing = [
                field for field in REQUIRED_APPROVED_CHANGE_FIELDS
                if item.get(field) in (None, "")
            ]
            if missing and item["status"] != "needs_review":
                self.database.update_approved_change_status(
                    item["id"], "needs_review"
                )
                marked_for_review += 1
                log_action(
                    self.logger, action="mark_approved_change_for_review",
                    website=item.get("website_id", ""),
                    target_url=item.get("target_url", ""),
                    record_ids={"approved_change_id": item["id"]},
                    previous_status=item["status"],
                    new_status="needs_review",
                )
        return {
            "repaired_invalid_approvals": repaired_approvals,
            "marked_approved_changes_for_review": marked_for_review,
        }

    @staticmethod
    def _add(
        findings: list[dict[str, Any]], severity: str, code: str,
        message: str, **details: Any,
    ) -> None:
        findings.append({
            "severity": severity, "code": code,
            "message": message, "details": details,
        })

    def _duplicates(
        self, findings: list[dict[str, Any]], rows: list[dict[str, Any]],
        fields: tuple[str, ...], active_statuses: set[str],
        code: str, message: str,
    ) -> None:
        groups: dict[tuple[Any, ...], list[int]] = {}
        for item in rows:
            if item.get("status") not in active_statuses:
                continue
            key = tuple(item.get(field) for field in fields)
            groups.setdefault(key, []).append(item["id"])
        for key, ids in groups.items():
            if len(ids) > 1:
                self._add(
                    findings, "high", code, message,
                    key=list(key), record_ids=ids,
                )
