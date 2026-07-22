"""Measured SEO experiments with URL locking and explicit approval."""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from core.action_logging import log_action
from core.workflow_status import EXPERIMENT_TRANSITIONS, validate_transition


LOCKED_STATUSES = (
    "approved", "running", "waiting_for_data", "ready_for_evaluation",
)
WAITING_PERIODS = {
    "title_meta": (14, 28),
    "internal_links": (21, 28),
    "content_update": (28, 42),
    "technical_fix": (14, 28),
    "schema": (21, 28),
}


class SEOExperimentEngine:
    """Plan, start, evaluate, and learn from one SEO change at a time."""

    def __init__(self, database: Any) -> None:
        self.database = database
        self.logger = logging.getLogger(__name__)

    def create_experiment(
        self, decision: dict[str, Any], *, decision_id: int | None = None,
        project_id: int | None = None, task_id: int | None = None,
    ) -> int:
        target_url = str(decision.get("target_url", "")).strip()
        if not target_url:
            raise ValueError("Et SEO-eksperiment kræver en konkret URL.")
        if self.is_url_locked(target_url):
            raise ValueError("Denne side indgår allerede i et aktivt eksperiment.")
        experiment_type = decision.get("experiment_type", "title_meta")
        previous_same_type = [
            item for item in self.get_experiments_for_url(target_url)
            if item["experiment_type"] == experiment_type
            and item["status"] == "completed"
        ]
        hypothesis = (
            decision.get("experiment_goal")
            or decision.get("expected_effect_reason", "")
        )
        if any(
            item.get("hypothesis", "").strip().casefold()
            == hypothesis.strip().casefold()
            for item in previous_same_type
        ):
            raise ValueError(
                "En ny dokumenteret hypotese er nødvendig før samme "
                "ændringstype kan testes igen."
            )
        _minimum, recommended = WAITING_PERIODS.get(
            experiment_type, (14, 28)
        )
        waiting_days = max(
            _minimum, int(decision.get("waiting_period_days") or recommended)
        )
        return self.database.create_seo_experiment({
            "website_id": decision["website"], "decision_id": decision_id,
            "project_id": project_id, "task_id": task_id,
            "target_url": target_url,
            "target_query": decision.get("target_query", ""),
            "experiment_type": experiment_type,
            "hypothesis": hypothesis,
            "change_description": decision["task_description"],
            "goal_metric": decision.get("goal_metric", "ctr"),
            "goal_direction": decision.get("goal_direction", "increase"),
            "target_change_pct": float(
                decision.get("target_change_pct", 15)
            ),
            "waiting_period_days": waiting_days, "status": "planned",
            "confidence": int(decision["confidence"]),
        })

    def calculate_baseline(
        self, website_id: str, target_url: str,
        target_query: str = "",
    ) -> dict[str, Any]:
        dimension = "page_query" if target_query else "page"
        rows = self.database.get_search_console_dimensions(
            dimension, website_id=website_id, page_url=target_url
        )
        if target_query:
            rows = [row for row in rows if row["query"] == target_query]
        if not rows:
            raise ValueError(
                "Eksperimentet kan ikke startes, fordi der mangler en "
                "stabil baseline."
            )
        latest = max(rows, key=lambda row: row["period_end"])
        covered_days = (
            date.fromisoformat(latest["period_end"])
            - date.fromisoformat(latest["period_start"])
        ).days + 1
        if covered_days < 14 or int(latest["impressions"]) < 1:
            raise ValueError(
                "Eksperimentet kan ikke startes, fordi der mangler en "
                "stabil baseline."
            )
        source = self.database.get_website_intelligence_source(website_id) or {}
        commission = float(
            (source.get("partner_ads") or {}).get("commission", 0) or 0
        )
        return {
            "baseline_start": latest["period_start"],
            "baseline_end": latest["period_end"],
            "baseline_clicks": latest["clicks"],
            "baseline_impressions": latest["impressions"],
            "baseline_ctr": latest["ctr"],
            "baseline_position": latest["average_position"],
            "baseline_commission": commission,
        }

    def start_experiment(
        self, experiment_id: int, *, approved: bool = False,
        started_at: datetime | None = None,
    ) -> dict[str, Any]:
        experiment = self._required(experiment_id)
        if experiment["status"] in {
            "waiting_for_data", "ready_for_evaluation", "completed"
        }:
            return experiment
        if not approved and experiment["status"] != "approved":
            raise ValueError("Eksperimentet skal godkendes før start.")
        baseline = self.calculate_baseline(
            experiment["website_id"], experiment["target_url"],
            experiment["target_query"],
        )
        started = started_at or datetime.now().astimezone()
        waiting_days = int(experiment["waiting_period_days"])
        minimum_days = WAITING_PERIODS.get(
            experiment["experiment_type"], (14, 28)
        )[0]
        values = {
            **baseline, "status": "waiting_for_data",
            "started_at": started.isoformat(timespec="seconds"),
            "minimum_evaluation_date": (
                started.date() + timedelta(days=minimum_days)
            ).isoformat(),
            "planned_evaluation_date": (
                started.date() + timedelta(days=waiting_days)
            ).isoformat(),
        }
        self.database.update_seo_experiment(experiment_id, values)
        log_action(
            self.logger, action="start_seo_experiment",
            website=experiment["website_id"],
            target_url=experiment["target_url"],
            record_ids={"experiment_id": experiment_id},
            previous_status=experiment["status"],
            new_status="waiting_for_data",
        )
        return self._required(experiment_id)

    def approve_experiment(self, experiment_id: int) -> None:
        experiment = self._required(experiment_id)
        if experiment["status"] == "approved":
            return
        if experiment["status"] != "planned":
            raise ValueError("Kun et planlagt eksperiment kan godkendes.")
        validate_transition(
            EXPERIMENT_TRANSITIONS, experiment["status"], "approved",
            "eksperiment",
        )
        self.database.update_seo_experiment(
            experiment_id, {"status": "approved"}
        )

    def get_active_experiment(
        self, website_id: str | None = None
    ) -> dict[str, Any] | None:
        rows = self.database.get_seo_experiments(
            website_id=website_id, statuses=LOCKED_STATUSES
        )
        return rows[0] if rows else None

    def get_experiments_for_website(
        self, website_id: str
    ) -> list[dict[str, Any]]:
        return self.database.get_seo_experiments(website_id=website_id)

    def get_experiments_for_url(
        self, target_url: str
    ) -> list[dict[str, Any]]:
        return self.database.get_seo_experiments(target_url=target_url)

    def is_url_locked(self, target_url: str) -> bool:
        experiment_locked = bool(self.database.get_seo_experiments(
            target_url=target_url, statuses=LOCKED_STATUSES
        ))
        draft_locked = any(
            item["target_url"] == target_url
            and item["status"] in {"approved", "converted_to_experiment"}
            for item in self.database.get_title_optimization_drafts()
        )
        observation_locked = any(
            item.get("observation_until")
            and date.fromisoformat(item["observation_until"]) > date.today()
            for item in self.database.get_seo_url_status(target_url)
        )
        return experiment_locked or draft_locked or observation_locked

    def evaluate_due_experiments(
        self, reference_date: date | None = None
    ) -> list[dict[str, Any]]:
        today = reference_date or date.today()
        due = [
            item for item in self.database.get_seo_experiments(
                statuses=("waiting_for_data", "ready_for_evaluation")
            )
            if item["planned_evaluation_date"]
            and date.fromisoformat(item["planned_evaluation_date"]) <= today
        ]
        return [self.evaluate_experiment(item["id"]) for item in due]

    def evaluate_experiment(self, experiment_id: int) -> dict[str, Any]:
        experiment = self._required(experiment_id)
        if experiment["status"] == "completed":
            return experiment
        if experiment["status"] not in {
            "waiting_for_data", "ready_for_evaluation"
        }:
            raise ValueError(
                "Kun et eksperiment i måleperioden kan evalueres."
            )
        measurement = self.calculate_baseline(
            experiment["website_id"], experiment["target_url"],
            experiment["target_query"],
        )
        if measurement["baseline_end"] <= (experiment["baseline_end"] or ""):
            if int(experiment.get("extension_count", 0)) < 1:
                extended = date.fromisoformat(
                    experiment["planned_evaluation_date"]
                ) + timedelta(days=14)
                self.database.update_seo_experiment(experiment_id, {
                    "planned_evaluation_date": extended.isoformat(),
                    "extension_count": 1, "result": "inconclusive",
                    "result_summary": (
                        "Måleperioden er forlænget én gang, fordi der endnu "
                        "ikke findes en ny stabil dataperiode."
                    ),
                })
                return self._required(experiment_id)
            return self.complete_experiment(
                experiment_id, "inconclusive",
                "Der kom ikke tilstrækkelige nye data efter forlængelsen.",
                measurement,
            )
        click_pct = self._pct(
            measurement["baseline_clicks"], experiment["baseline_clicks"]
        )
        impression_pct = self._pct(
            measurement["baseline_impressions"],
            experiment["baseline_impressions"],
        )
        ctr_change = (
            measurement["baseline_ctr"] - experiment["baseline_ctr"]
        )
        position_change = (
            measurement["baseline_position"]
            - experiment["baseline_position"]
        )
        target = float(experiment["target_change_pct"])
        metric_pct = (
            self._pct(measurement["baseline_ctr"], experiment["baseline_ctr"])
            if experiment["goal_metric"] == "ctr" else click_pct
        )
        evaluation = self.classify_result(experiment, measurement)
        outcome = {
            "Tydeligt forbedret": "successful",
            "Forbedret": "successful",
            "Delvist forbedret": "partially_successful",
            "Uændret": "no_measurable_effect",
            "Forværret": "negative_effect",
            "Utilstrækkelige data": "inconclusive",
        }[evaluation["classification"]]
        completed = self.complete_experiment(
            experiment_id, outcome,
            evaluation["summary"],
            {
                **measurement, "actual_click_change_pct": click_pct,
                "actual_impression_change_pct": impression_pct,
                "actual_ctr_change": ctr_change,
                "actual_position_change": position_change,
            },
        )
        self._save_structured_learning(
            experiment, completed, measurement, evaluation
        )
        completion_created = self.database.save_experiment_observation(
            experiment_id=experiment_id,
            observation_date=date.today().isoformat(),
            observation_type="afsluttet", event_key="completed",
            description=(
                f"Eksperimentet blev afsluttet som "
                f"{evaluation['classification'].lower()}."
            ),
        )
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        if completion_created:
            self.database.create_event_record({
                "event_type": "seo_experiment_completed",
                "source": "seo_experiment_engine",
                "website": experiment["website_id"],
                "title": "Eksperiment afsluttet",
                "description": evaluation["summary"],
                "priority": 70,
                "data_json": json.dumps({
                    "experiment_id": experiment_id,
                    "classification": evaluation["classification"],
                }, ensure_ascii=False),
                "status": "pending", "created_at": timestamp,
            })
        return completed

    def classify_result(
        self, experiment: dict[str, Any], measurement: dict[str, Any]
    ) -> dict[str, Any]:
        """Classify multiple KPIs with position direction handled correctly."""
        days = (
            date.fromisoformat(measurement["baseline_end"])
            - date.fromisoformat(measurement["baseline_start"])
        ).days + 1
        baseline_days = (
            date.fromisoformat(experiment["baseline_end"])
            - date.fromisoformat(experiment["baseline_start"])
        ).days + 1
        impressions = int(measurement["baseline_impressions"])
        clicks = int(measurement["baseline_clicks"])
        quality = (
            "Høj" if days >= 21 and impressions >= 500 and clicks >= 20
            else "Middel" if days >= 14 and impressions >= 100 and clicks >= 5
            else "Lav"
        )
        if days != baseline_days:
            quality = "Lav"
        click_pct = self._pct(
            clicks, float(experiment.get("baseline_clicks") or 0)
        )
        ctr_pct = self._pct(
            float(measurement["baseline_ctr"]),
            float(experiment.get("baseline_ctr") or 0),
        )
        impression_pct = self._pct(
            impressions, float(experiment.get("baseline_impressions") or 0)
        )
        # A positive position gain means the numerical position became lower.
        position_gain = (
            float(experiment.get("baseline_position") or 0)
            - float(measurement["baseline_position"])
        )
        if quality == "Lav":
            classification = "Utilstrækkelige data"
            next_step = "Indsaml flere data"
        elif ctr_pct >= 20 and click_pct >= 10 and position_gain >= -1:
            classification = "Tydeligt forbedret"
            next_step = "Afslut opgaven"
        elif (
            (ctr_pct >= 10 or click_pct >= 10 or position_gain >= 1)
            and impression_pct > -20 and position_gain >= -1.5
        ):
            classification = "Forbedret"
            next_step = "Observer siden"
        elif ctr_pct > 3 or click_pct > 3 or position_gain > .5:
            classification = "Delvist forbedret"
            next_step = "Observer siden"
        elif ctr_pct <= -10 or click_pct <= -10 or position_gain <= -1.5:
            classification = "Forværret"
            next_step = "Arbejd videre med en ny hypotese"
        else:
            classification = "Uændret"
            next_step = "Arbejd videre med en ny hypotese"
        return {
            "classification": classification, "data_quality": quality,
            "click_change_pct": click_pct, "ctr_change_pct": ctr_pct,
            "impression_change_pct": impression_pct,
            "position_gain": position_gain, "next_step": next_step,
            "summary": (
                f"{classification}. CTR ændrede sig {ctr_pct:+.1f} %, "
                f"klik {click_pct:+.1f} %, og placeringen "
                f"{'forbedredes' if position_gain > 0 else 'ændrede sig'} "
                f"{position_gain:+.1f}."
            ),
        }

    def complete_experiment(
        self, experiment_id: int, result: str, summary: str,
        measurements: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allowed = {
            "successful", "partially_successful", "no_measurable_effect",
            "negative_effect", "inconclusive",
        }
        if result not in allowed:
            raise ValueError("Ugyldigt eksperimentresultat.")
        experiment = self._required(experiment_id)
        if experiment["status"] == "completed":
            return experiment
        validate_transition(
            EXPERIMENT_TRANSITIONS, experiment["status"], "completed",
            "eksperiment",
        )
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        values = {
            "status": "completed", "result": result,
            "result_summary": summary, "actual_evaluation_date": now,
            "completed_at": now,
        }
        values.update({
            key: value for key, value in (measurements or {}).items()
            if key.startswith("actual_")
        })
        self.database.update_seo_experiment(experiment_id, values)
        learning = (
            f"{experiment['experiment_type']} på {experiment['target_url']}: "
            f"{summary}"
        )
        self.database.save_experiment_learning(
            experiment_id=experiment_id,
            website_id=experiment["website_id"],
            target_url=experiment["target_url"],
            experiment_type=experiment["experiment_type"],
            outcome=result, learning=learning,
        )
        if experiment.get("decision_id"):
            self.database.update_decision_status(
                experiment["decision_id"], "completed"
            )
        log_action(
            self.logger, action="complete_seo_experiment",
            website=experiment["website_id"],
            target_url=experiment["target_url"],
            record_ids={"experiment_id": experiment_id},
            previous_status=experiment["status"], new_status="completed",
        )
        return self._required(experiment_id)

    def cancel_experiment(self, experiment_id: int) -> None:
        self._required(experiment_id)
        self.database.update_seo_experiment(experiment_id, {
            "status": "cancelled",
            "completed_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
        })

    def _save_structured_learning(
        self, experiment: dict[str, Any], completed: dict[str, Any],
        measurement: dict[str, Any], evaluation: dict[str, Any],
    ) -> None:
        queue_items = self.database.get_work_queue((
            "implemented", "completed", "awaiting_implementation",
        ))
        queue_item = next((
            item for item in queue_items
            if item.get("experiment_id") == experiment["id"]
        ), {})
        if queue_item:
            self.database.update_work_queue_item(
                queue_item["id"], {"status": "completed"}
            )
        approved_rows = self.database.get_approved_changes(
            experiment_id=experiment["id"]
        )
        implementation = approved_rows[0] if approved_rows else {}
        if approved_rows:
            self.database.update_approved_change_status(
                approved_rows[0]["id"], "completed"
            )
        count = len([
            item for item in self.database.get_seo_learning_entries()
            if item["change_type"] == experiment["experiment_type"]
        ]) + 1
        pattern = (
            "Understøttet mønster" if count >= 10
            else "Foreløbigt mønster" if count >= 3
            else "Enkelt observation"
        )
        self.database.save_seo_learning_entry({
            "experiment_id": experiment["id"],
            "website_id": experiment["website_id"],
            "target_url": experiment["target_url"],
            "page_type": "ukendt",
            "change_type": experiment["experiment_type"],
            "target_query": experiment.get("target_query", ""),
            "hypothesis": experiment["hypothesis"],
            "original_change": {
                "title": implementation.get("current_title", ""),
                "meta": implementation.get("current_meta", ""),
            },
            "implemented_change": {
                "title": implementation.get("approved_title", ""),
                "meta": implementation.get("approved_meta", ""),
                "user_edited": bool(
                    queue_item.get("edited_title")
                    or queue_item.get("edited_meta")
                ),
            },
            "baseline": {
                "start": experiment.get("baseline_start"),
                "end": experiment.get("baseline_end"),
                "clicks": experiment.get("baseline_clicks"),
                "impressions": experiment.get("baseline_impressions"),
                "ctr": experiment.get("baseline_ctr"),
                "position": experiment.get("baseline_position"),
            },
            "result": {
                **evaluation,
                "clicks": measurement["baseline_clicks"],
                "impressions": measurement["baseline_impressions"],
                "ctr": measurement["baseline_ctr"],
                "position": measurement["baseline_position"],
            },
            "effect_size": evaluation["ctr_change_pct"],
            "data_quality": evaluation["data_quality"],
            "classification": evaluation["classification"],
            "conclusion": (
                f"På denne URL gav hypotesen resultatet "
                f"{evaluation['classification'].lower()}. Det er "
                f"{pattern.lower()} og ikke en generel SEO-regel."
            ),
            "pattern_level": pattern,
        })
        failed = len([
            item for item in self.database.get_seo_learning_entries()
            if item["target_url"] == experiment["target_url"]
            and item["change_type"] == experiment["experiment_type"]
            and item["classification"] in {"Uændret", "Forværret"}
        ])
        if failed >= 2:
            url_status = "Kræver ny strategi"
        elif evaluation["classification"] in {
            "Tydeligt forbedret", "Forbedret", "Delvist forbedret"
        }:
            url_status = "Har fortsat potentiale"
        elif evaluation["classification"] == "Utilstrækkelige data":
            url_status = "Observeres"
        else:
            url_status = "Optimeringskandidat"
        self.database.upsert_seo_url_status(
            target_url=experiment["target_url"],
            website_id=experiment["website_id"], status=url_status,
            observation_until=(date.today() + timedelta(days=28)).isoformat(),
            failed_same_type_count=failed,
        )

    def get_experiment_learning(
        self, experiment_id: int
    ) -> dict[str, Any] | None:
        return next((
            item for item in self.database.get_experiment_learnings()
            if item["experiment_id"] == experiment_id
        ), None)

    def _required(self, experiment_id: int) -> dict[str, Any]:
        value = self.database.get_seo_experiment(experiment_id)
        if not value:
            raise ValueError(f"Eksperiment {experiment_id} findes ikke.")
        return value

    @staticmethod
    def _pct(current: float, previous: float) -> float:
        if not previous:
            return 0.0
        return (current - previous) / previous * 100
