"""Persistent, approval-gated daily SEO work queue."""

import json
import logging
import re
from datetime import datetime
from typing import Any

from core.action_logging import log_action
from core.decision_engine import DecisionEngine
from core.seo_experiment_engine import SEOExperimentEngine


class WorkQueueService:
    """Build one ranked snapshot and advance through it without recalculation."""

    def __init__(
        self, database: Any, website_registry: Any,
        *, decision_engine: DecisionEngine | None = None,
        experiment_engine: SEOExperimentEngine | None = None,
    ) -> None:
        self.database = database
        self.registry = website_registry
        self.experiments = experiment_engine or SEOExperimentEngine(database)
        self.decisions = decision_engine or DecisionEngine(
            database, website_registry, experiment_engine=self.experiments
        )
        self.logger = logging.getLogger(__name__)

    def ensure_queue(self) -> list[dict[str, Any]]:
        """Build the queue once; later navigation only reads the snapshot."""
        existing = self.database.get_work_queue((
            "queued", "skipped", "awaiting_implementation",
        ))
        if existing:
            return [self._attach_approved_change(item) for item in existing]
        candidates = self._queue_candidates()
        for candidate in candidates:
            self.enqueue_candidate(candidate)
        return self.database.get_work_queue((
            "queued", "skipped", "awaiting_implementation",
        ))

    def migrate_approved_changes(self) -> dict[str, int]:
        """Recover only previously persisted, approved implementation text."""
        recovered = errors = 0
        items = self.database.get_work_queue((
            "awaiting_implementation", "implemented", "completed",
        ))
        for item in items:
            if self.database.get_approved_change_for_work_item(item):
                continue
            recovered_values = self._recover_approved_title_meta(item)
            if recovered_values:
                candidate = item.get("candidate") or {}
                experiment = (
                    self.database.get_seo_experiment(item["experiment_id"])
                    if item.get("experiment_id") else {}
                ) or {}
                self.database.save_approved_change({
                    "website_id": item["website_id"],
                    "change_type": "title_meta",
                    "target_url": item["target_url"],
                    "target_query": item.get("target_query", ""),
                    "current_title": recovered_values["current_title"],
                    "approved_title": recovered_values["new_title"],
                    "current_meta": recovered_values["current_meta"],
                    "approved_meta": recovered_values["new_meta"],
                    "hypothesis": (
                        experiment.get("hypothesis")
                        or candidate.get("experiment_goal", "")
                    ),
                    "reason": (
                        candidate.get("why_selected")
                        or candidate.get("expected_effect_reason", "")
                    ),
                    "expected_effect": item["expected_impact"],
                    "project_id": item.get("project_id"),
                    "task_id": item.get("task_id"),
                    "experiment_id": item.get("experiment_id"),
                    "source_draft_id": item.get("draft_id"),
                    "status": (
                        "measurement_period"
                        if item["status"] == "implemented"
                        else "completed"
                        if item["status"] == "completed"
                        else "awaiting_implementation"
                    ),
                    "implemented_at": item.get("implemented_at"),
                })
                recovered += 1
            elif (item.get("implementation") or {}).get(
                "type"
            ) == "title_meta" or (
                item.get("candidate") or {}
            ).get("experiment_type") == "title_meta":
                errors += 1
        return {"recovered": recovered, "errors": errors}

    def repair_invalid_approval_states(self) -> int:
        """Undo legacy approvals that have no persisted approved change.

        A title/meta queue item is not approved merely because planning records
        were created. It must have an Approved Change containing both selected
        texts. Historical orphan planning records are cancelled for audit
        purposes and the queue item is returned to review.
        """
        repaired = 0
        items = self.database.get_work_queue(("awaiting_implementation",))
        for item in items:
            candidate = item.get("candidate") or {}
            if candidate.get("experiment_type") != "title_meta":
                continue
            approved = self.database.get_approved_change_for_work_item(item)
            if approved and (
                approved.get("approved_title", "").strip()
                and approved.get("approved_meta", "").strip()
            ):
                continue
            if item.get("experiment_id"):
                self.database.update_seo_experiment(
                    item["experiment_id"], {"status": "cancelled"}
                )
            if item.get("task_id"):
                self.database.update_task_status(
                    item["task_id"], "cancelled"
                )
            if item.get("project_id"):
                project = self.database.get_project_record(
                    item["project_id"]
                )
                if project:
                    self.database.update_project_record(
                        item["project_id"],
                        description=project.get("description", ""),
                        status="cancelled",
                        priority=project.get("priority", "medium"),
                        expected_effect=project.get("expected_effect", ""),
                    )
            self.database.update_work_queue_item(item["id"], {
                "status": "queued",
                "decision_id": None,
                "project_id": None,
                "task_id": None,
                "experiment_id": None,
                "edited_title": "",
                "edited_meta": "",
                "implementation_json": json.dumps({
                    "type": "title_meta",
                    "integrity_error": "approval_without_approved_change",
                }),
            })
            repaired += 1
        return repaired

    def rebuild_queue(self) -> list[dict[str, Any]]:
        """Explicitly calculate and persist a new ranked queue."""
        self.database.replace_queued_work(self._queue_candidates())
        return self.database.get_work_queue()

    def enqueue_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Idempotently append a candidate and return its persisted row."""
        item_id = self.database.enqueue_work_candidate(candidate)
        return self._required(item_id)

    def current(self, website_id: str | None = None) -> dict[str, Any] | None:
        items = self.ready_items(website_id)
        awaiting = [
            item for item in items
            if item["status"] == "awaiting_implementation"
        ]
        return awaiting[0] if awaiting else (items[0] if items else None)

    def ready_items(self, website_id: str | None = None) -> list[dict[str, Any]]:
        """Return actionable rows, optionally restricted by exact website ID."""
        items = self.ensure_queue()
        ready = []
        for item in items:
            website = self.database.get_website(item["website_id"])
            if (
                website is None
                or not website["active"]
                or website["status"] != "active"
            ):
                continue
            if website_id is not None and item["website_id"] != website_id:
                continue
            if item["status"] == "awaiting_implementation":
                approved = item.get("approved_change") or {}
                if (
                    approved.get("change_type") == "title_meta"
                    and str(approved.get("approved_title") or "").strip()
                    and str(approved.get("approved_meta") or "").strip()
                ):
                    ready.append(item)
                continue
            if item["status"] != "queued" or not item.get("draft_id"):
                continue
            change = item.get("implementation") or {}
            if not self._concrete_title_meta(change):
                continue
            if self.experiments.is_url_locked(item["target_url"]):
                continue
            ready.append(item)
        return ready

    def upcoming(
        self, limit: int = 10, website_id: str | None = None
    ) -> list[dict[str, Any]]:
        current = self.current(website_id)
        return [
            item for item in self.ready_items(website_id)
            if not current or item["id"] != current["id"]
        ][:limit]

    def skip(self, item_id: int, reason: str = "") -> None:
        item = self._required(item_id)
        if item["status"] not in {"queued", "skipped"}:
            raise ValueError("Kun en opgave i køen kan springes over.")
        self.database.skip_work_queue_item(item_id, reason)

    def approve(
        self, item_id: int, *, title: str = "", meta: str = "",
        title_optimizer: Any | None = None,
    ) -> dict[str, int]:
        """Create exactly one project, task, experiment, and baseline."""
        item = self._required(item_id)
        website = self.database.get_website(item["website_id"])
        if (
            website is None
            or not website["active"]
            or website["status"] != "active"
        ):
            raise ValueError("Et inaktivt website kan ikke få et nyt eksperiment.")
        if item["status"] == "awaiting_implementation":
            return {
                "project_id": item["project_id"],
                "task_id": item["task_id"],
                "experiment_id": item["experiment_id"],
            }
        if item["status"] not in {"queued", "skipped"}:
            raise ValueError("Opgaven kan ikke godkendes i den aktuelle status.")
        if item.get("draft_id"):
            if title_optimizer is None:
                raise ValueError("Title-værktøjet er ikke tilgængeligt.")
            draft = self.database.get_title_optimization_draft(item["draft_id"])
            selected_title = title.strip() or draft["selected_title"]
            selected_meta = meta.strip() or draft["selected_meta"]
            result = title_optimizer.approve_draft(
                item["draft_id"], selected_title, selected_meta
            )
        else:
            decision = dict(item["candidate"])
            if decision.get("experiment_type") == "title_meta":
                raise ValueError(
                    "Title- og metaopgaver skal godkendes gennem en "
                    "Title Optimization-kladde."
                )
            decision["why_selected"] = self.decisions.explain_decision(decision)
            decision["why_not_other_tasks"] = []
            if title.strip() or meta.strip():
                decision["task_description"] = (
                    (f"Title: {title.strip()}. " if title.strip() else "")
                    + (f"Meta: {meta.strip()}." if meta.strip() else "")
                )
            self.decisions._validate_decision(decision)
            decision_id = self.database.create_decision(decision)
            result = self.decisions.send_decision_to_project_manager(decision_id)
            result["decision_id"] = decision_id
            self.database.save_approved_change({
                "website_id": item["website_id"],
                "change_type": decision.get("experiment_type", "title_meta"),
                "target_url": item["target_url"],
                "target_query": item.get("target_query", ""),
                "current_title": (
                    item.get("implementation") or {}
                ).get("current_title", ""),
                "approved_title": title.strip(),
                "current_meta": (
                    item.get("implementation") or {}
                ).get("current_meta", ""),
                "approved_meta": meta.strip(),
                "hypothesis": decision["experiment_goal"],
                "reason": decision["why_selected"],
                "expected_effect": decision["expected_effect"],
                "project_id": result["project_id"],
                "task_id": result["task_id"],
                "experiment_id": result["experiment_id"],
                "source_draft_id": None,
                "status": "awaiting_implementation",
            })
        self.database.update_work_queue_item(item_id, {
            "status": "awaiting_implementation",
            "decision_id": result.get("decision_id"),
            "project_id": result["project_id"], "task_id": result["task_id"],
            "experiment_id": result["experiment_id"],
            "edited_title": title.strip(), "edited_meta": meta.strip(),
        })
        return result

    def mark_implemented(
        self, item_id: int, *, title_optimizer: Any | None = None
    ) -> dict[str, Any]:
        """Start measurement, lock the URL, and remove the task from the queue."""
        item = self._required(item_id)
        if item["status"] == "implemented" and item.get("experiment_id"):
            experiment = self.database.get_seo_experiment(
                item["experiment_id"]
            )
            if experiment:
                return experiment
        if item["status"] != "awaiting_implementation":
            raise ValueError("Opgaven afventer ikke implementering.")
        approved_change = item.get("approved_change")
        if not approved_change:
            raise ValueError(
                "Den godkendte ændring kunne ikke findes. "
                "Gennemgå forslaget igen."
            )
        if item.get("draft_id"):
            if title_optimizer is None:
                raise ValueError("Title-værktøjet er ikke tilgængeligt.")
            experiment = title_optimizer.mark_implemented(item["draft_id"])
        else:
            experiment = self.experiments.start_experiment(
                item["experiment_id"], approved=True
            )
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self.database.update_work_queue_item(item_id, {
            "status": "implemented", "implemented_at": timestamp,
        })
        self.database.update_approved_change_status(
            approved_change["id"], "measurement_period",
            implemented_at=timestamp,
        )
        if item.get("task_id"):
            self.database.update_task_status(
                item["task_id"], "completed", completed_at=timestamp
            )
        log_action(
            self.logger, action="mark_queue_item_implemented",
            website=item["website_id"], target_url=item["target_url"],
            record_ids={
                "queue_id": item_id,
                "approved_change_id": approved_change["id"],
                "experiment_id": item["experiment_id"],
            },
            previous_status=item["status"], new_status="implemented",
        )
        return experiment

    def _queue_candidates(self) -> list[dict[str, Any]]:
        """Return only complete, AI-selected and reviewer-approved changes.

        Raw Decision Engine opportunities do not belong in the daily work
        surface.  A queue item becomes actionable only after Title Optimizer
        has analysed the page, generated copy, selected a recommendation and
        passed its reviewer.
        """
        active = self.database.get_work_queue((
            "queued", "skipped", "awaiting_implementation",
        ))
        active_draft_ids = {
            item["draft_id"] for item in active if item.get("draft_id")
        }
        active_urls = {item["target_url"] for item in active}
        active_websites = set(self.database.get_active_website_ids())
        drafts = [
            item for item in self.database.get_title_optimization_drafts()
            if item["status"] == "awaiting_approval"
            and item["website_id"] in active_websites
            and (item.get("reviewer") or {}).get("approved") is True
            and str(item.get("selected_title") or "").strip()
            and str(item.get("selected_meta") or "").strip()
            and not self.experiments.is_url_locked(item["target_url"])
            and item["id"] not in active_draft_ids
            and item["target_url"] not in active_urls
        ]
        candidates: list[dict[str, Any]] = []
        for draft in drafts:
            search = (draft.get("page_analysis") or {}).get(
                "search_console", {}
            )
            candidates.append({
                "website": draft["website_id"],
                "target_url": draft["target_url"],
                "target_query": draft["target_query"],
                "task_title": "Gennemgå title og metabeskrivelse",
                "task_description": "Godkend et konkret title-forslag.",
                "exact_steps": [
                    "Gennemgå den anbefalede title.",
                    "Gennemgå metabeskrivelsen.",
                    "Godkend eller redigér teksten.",
                ],
                "completion_criteria": "Title og metabeskrivelse er godkendt.",
                "assigned_agent": "SEO Manager",
                "estimated_minutes": 10,
                "expected_effect": draft["expected_effect"],
                "expected_effect_reason": (
                    "Siden har synlighed i Google og potentiale for flere klik."
                ),
                "confidence": int(draft["confidence"]),
                "measurement_method": draft["measurement_method"],
                "experiment_type": "title_meta",
                "experiment_goal": "Øg CTR uden et væsentligt placeringsfald.",
                "goal_metric": "ctr", "goal_direction": "increase",
                "target_change_pct": 15, "waiting_period_days": 28,
                "risk": "Mellem",
                "data_quality": (
                    "Høj" if int(search.get("impressions", 0)) >= 500
                    else "Mellem"
                ),
                "current_clicks": int(search.get("clicks", 0)),
                "previous_clicks": int(search.get("previous_clicks", 0)),
                "current_impressions": int(search.get("impressions", 0)),
                "previous_impressions": int(
                    search.get("previous_impressions", 0)
                ),
                "current_ctr": float(search.get("ctr", 0)),
                "previous_ctr": float(search.get("previous_ctr", 0)),
                "current_position": float(search.get("position", 0)),
                "previous_position": float(search.get("position", 0)),
                "monetized": False, "manual_priority": "medium",
                "affiliate_commission": 0, "seo_health_score": 50,
                "seo_trend": "unknown", "has_active_work": False,
                "active_experiment_count": 0,
                "days_since_implementation": 90,
                "draft_id": draft["id"],
                "implementation_content": {
                    "type": "title_meta",
                    "current_title": draft["current_title"],
                    "new_title": draft["selected_title"],
                    "current_meta": draft["current_meta"],
                    "new_meta": draft["selected_meta"],
                    "wordpress_edit_url": (
                        (draft.get("page_analysis") or {}).get(
                            "wordpress_edit_url", ""
                        )
                    ),
                    "previous_titles": draft["title_proposals"],
                    "previous_metas": draft["meta_proposals"],
                    "reviewer": draft["reviewer"],
                },
                "priority_score": max(75, int(draft["confidence"])),
                "priority_label": "Høj",
                "score_factors": {"ai_confidence": draft["confidence"]},
            })
        return sorted(
            candidates,
            key=lambda item: (
                -int(item["priority_score"]),
                -int(item.get("current_impressions", 0)),
                item["website"], item["target_url"],
            ),
        )

    def _required(self, item_id: int) -> dict[str, Any]:
        item = self.database.get_work_queue_item(item_id)
        if not item:
            raise ValueError("Opgaven findes ikke i arbejdskøen.")
        return self._attach_approved_change(item)

    def _attach_approved_change(
        self, item: dict[str, Any]
    ) -> dict[str, Any]:
        implementation = item.get("implementation") or {}
        if item.get("draft_id") and item.get("status") in {"queued", "skipped"}:
            draft = self.database.get_title_optimization_draft(item["draft_id"])
            if draft and (draft.get("reviewer") or {}).get("approved") is True:
                implementation = {
                    "type": "title_meta",
                    "current_title": draft.get("current_title", ""),
                    "new_title": draft.get("selected_title", ""),
                    "current_meta": draft.get("current_meta", ""),
                    "new_meta": draft.get("selected_meta", ""),
                }
        return {
            **item,
            "implementation": implementation,
            "approved_change": (
                self.database.get_approved_change_for_work_item(item)
            ),
        }

    def _recover_approved_title_meta(
        self, item: dict[str, Any]
    ) -> dict[str, str] | None:
        """Follow persisted relations; never generate or infer new copy."""
        drafts = self.database.get_title_optimization_drafts(
            item["website_id"]
        )
        related = [
            draft for draft in drafts
            if draft["target_url"] == item["target_url"]
            and (
                (item.get("draft_id") and draft["id"] == item["draft_id"])
                or (
                    item.get("experiment_id")
                    and draft.get("experiment_id") == item["experiment_id"]
                )
                or (
                    item.get("task_id")
                    and draft.get("task_id") == item["task_id"]
                )
                or (
                    item.get("project_id")
                    and draft.get("project_id") == item["project_id"]
                )
            )
            and draft["status"] in {
                "converted_to_experiment", "approved"
            }
        ]
        if related:
            draft = max(related, key=lambda value: value["id"])
            if draft["selected_title"].strip() and draft["selected_meta"].strip():
                return {
                    "current_title": draft["current_title"],
                    "new_title": draft["selected_title"].strip(),
                    "current_meta": draft["current_meta"],
                    "new_meta": draft["selected_meta"].strip(),
                    "wordpress_edit_url": (
                        (draft.get("page_analysis") or {}).get(
                            "wordpress_edit_url", ""
                        )
                    ),
                    "previous_titles": draft["title_proposals"],
                    "previous_metas": draft["meta_proposals"],
                    "reviewer": draft["reviewer"],
                }
        if item.get("edited_title", "").strip() and item.get(
            "edited_meta", ""
        ).strip():
            return {
                "current_title": "",
                "new_title": item["edited_title"].strip(),
                "current_meta": "",
                "new_meta": item["edited_meta"].strip(),
            }
        task = next((
            task for task in self.database.get_task_records_for_project(
                item.get("project_id")
            )
            if task["id"] == item.get("task_id")
        ), None)
        parsed = self._parse_persisted_change(
            task.get("description", "") if task else ""
        )
        if parsed:
            return parsed
        experiment = (
            self.database.get_seo_experiment(item["experiment_id"])
            if item.get("experiment_id") else None
        )
        return self._parse_persisted_change(
            experiment.get("change_description", "") if experiment else ""
        )

    @staticmethod
    def _parse_persisted_change(text: str) -> dict[str, str] | None:
        title = re.search(
            r"(?:^|\n)Title:\s*(.+?)(?=\nMeta:|$)",
            text, flags=re.IGNORECASE | re.DOTALL,
        )
        meta = re.search(
            r"(?:^|\n)Meta:\s*(.+?)(?=\n|$)",
            text, flags=re.IGNORECASE | re.DOTALL,
        )
        if not title or not meta:
            return None
        title_value = title.group(1).strip()
        meta_value = meta.group(1).strip()
        if not title_value or not meta_value:
            return None
        return {
            "current_title": "", "new_title": title_value,
            "current_meta": "", "new_meta": meta_value,
        }

    @staticmethod
    def _concrete_title_meta(content: dict[str, Any]) -> bool:
        return bool(
            content.get("type") == "title_meta"
            and str(content.get("new_title", "")).strip()
            and str(content.get("new_meta", "")).strip()
        )
