"""Automatic, idempotent preparation of one complete daily SEO task."""

import logging
import threading
from dataclasses import dataclass
from typing import Any

from agents.title_optimizer import TitleOptimizationValidationError


@dataclass(frozen=True)
class PreparationResult:
    item: dict[str, Any] | None
    reason: str | None = None
    candidate_count: int = 0


class DailyWorkPreparationService:
    """Turn reviewed drafts or raw evidence into one ready queue item."""

    _preparation_lock = threading.Lock()

    def __init__(
        self, *, database: Any, queue: Any, title_optimizer: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self.database = database
        self.queue = queue
        self.optimizer = title_optimizer
        self.logger = logger or logging.getLogger(__name__)

    def prepare_next(self, website_id: str | None = None) -> PreparationResult:
        with self._preparation_lock:
            current = self.queue.current(website_id)
            if current:
                self._log("active_queue", "reused", website_id, item=current)
                return PreparationResult(current)

            reviewed = self._reviewed_candidates(website_id)
            if reviewed:
                try:
                    item = self.queue.enqueue_candidate(reviewed[0])
                except Exception as error:
                    self._log(
                        "enqueue_draft", "failed", website_id,
                        candidate=reviewed[0], error=error,
                    )
                    return PreparationResult(
                        None, "existing_draft_queue_failed", len(reviewed)
                    )
                self._log(
                    "enqueue_draft", "completed", website_id,
                    candidate=reviewed[0], item=item,
                )
                return PreparationResult(item)

            all_candidates = self.queue.decisions.rank_candidates(
                self.queue.decisions.collect_candidates(
                    website_id, include_locked=True
                )
            )
            candidates = [
                item for item in all_candidates
                if not self.queue.experiments.is_url_locked(item["target_url"])
                and not self.queue.decisions.has_conflict(item)
            ]
            if not candidates:
                reason = "all_candidates_locked" if all_candidates else (
                    "missing_search_console_data"
                    if not self._has_search_console_data(website_id)
                    else "no_eligible_candidates"
                )
                self._log("candidate_selection", reason, website_id)
                return PreparationResult(None, reason, len(all_candidates))

            candidate = candidates[0]
            target_url = candidate["target_url"]
            if self.queue.experiments.is_url_locked(target_url):
                self._log(
                    "pre_generation_lock", "locked", website_id,
                    candidate=candidate,
                )
                return PreparationResult(
                    None, "all_candidates_locked", len(candidates)
                )

            # Recheck after acquiring the process lock and before any AI call.
            reviewed = self._reviewed_candidates(website_id, target_url)
            if reviewed:
                item = self.queue.enqueue_candidate(reviewed[0])
                return PreparationResult(item)

            try:
                page = self.optimizer.analyze_current_snippet(
                    self._optimizer_candidate(candidate)
                )
                competitors = self.optimizer.analyze_competitors(
                    self._optimizer_candidate(candidate)
                )
                generated = self.optimizer.generate_title_proposals(
                    self._optimizer_candidate(candidate), page, competitors
                )
            except TitleOptimizationValidationError as error:
                reason = (
                    "reviewer_failed"
                    if "review" in str(error.phase) else "generation_failed"
                )
                self._log(
                    "proposal_generation", reason, website_id,
                    candidate=candidate, error=error,
                )
                return PreparationResult(None, reason, len(candidates))
            except Exception as error:
                self._log(
                    "proposal_generation", "generation_failed", website_id,
                    candidate=candidate, error=error,
                )
                return PreparationResult(
                    None, "generation_failed", len(candidates)
                )

            if self.queue.experiments.is_url_locked(target_url):
                self._log(
                    "post_generation_lock", "locked", website_id,
                    candidate=candidate,
                )
                return PreparationResult(
                    None, "all_candidates_locked", len(candidates)
                )
            try:
                draft_id = self.optimizer.create_approval_draft(
                    generated, competitors
                )
                draft = self.database.get_title_optimization_draft(draft_id)
                queued = self._candidate_from_draft(draft)
                item = self.queue.enqueue_candidate(queued)
            except Exception as error:
                self._log(
                    "persist_prepared_work", "failed", website_id,
                    candidate=candidate, error=error,
                )
                return PreparationResult(
                    None, "existing_draft_queue_failed", len(candidates)
                )
            self._log(
                "persist_prepared_work", "completed", website_id,
                candidate=candidate, draft=draft, item=item,
            )
            return PreparationResult(item)

    def _reviewed_candidates(
        self, website_id: str | None, target_url: str | None = None
    ) -> list[dict[str, Any]]:
        candidates = self.queue._queue_candidates()
        return [
            item for item in candidates
            if (website_id is None or item["website"] == website_id)
            and (target_url is None or item["target_url"] == target_url)
        ]

    def _has_search_console_data(self, website_id: str | None) -> bool:
        if website_id:
            return bool(self.database.get_search_console_dimensions(
                "page", website_id=website_id
            ))
        return bool(self.database.get_search_console_dimensions("page"))

    @staticmethod
    def _optimizer_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "website": candidate["website"],
            "target_url": candidate["target_url"],
            "target_query": candidate.get("target_query", ""),
            "clicks": candidate.get("current_clicks", 0),
            "impressions": candidate.get("current_impressions", 0),
            "ctr": candidate.get("current_ctr", 0),
            "position": candidate.get("current_position", 0),
            "period": "",
            "reason": candidate.get("expected_effect_reason", ""),
            "confidence": candidate.get("confidence", 0),
        }

    def _candidate_from_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        return next(
            item for item in self.queue._queue_candidates()
            if item.get("draft_id") == draft["id"]
        )

    def _log(
        self, step: str, result: str, website_id: str | None, *,
        candidate: dict[str, Any] | None = None,
        draft: dict[str, Any] | None = None,
        item: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.logger.info(
            "daily_work_preparation website=%s url=%s candidate_id=%s "
            "draft_id=%s queue_item_id=%s step=%s result=%s error_type=%s",
            website_id or "all",
            (candidate or item or {}).get("target_url", ""),
            (candidate or {}).get("id", ""),
            (draft or {}).get("id", (candidate or {}).get("draft_id", "")),
            (item or {}).get("id", ""), step, result,
            type(error).__name__ if error else "",
        )
