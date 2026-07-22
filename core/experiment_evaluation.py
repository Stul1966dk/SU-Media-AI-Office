"""Automatic, deterministic evaluation of completed SEO measurements."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from core.ai_service import AIService, AIServiceError


EVALUATION_VERSION = 1
RESULT_LABELS = {
    "strong_improvement": "Stor forbedring",
    "improvement": "Forbedring",
    "neutral": "Ingen tydelig ændring",
    "decline": "Forværring",
    "strong_decline": "Stor forværring",
    "insufficient_data": "Utilstrækkelige data",
    "evaluation_failed": "Evaluering mislykkedes",
}


@dataclass(frozen=True)
class EvaluationRules:
    """Central, configurable sample and classification thresholds."""

    minimum_impressions: int = 100
    minimum_days: int = 14
    minimum_clicks: int = 5
    retry_days: int = 7
    ctr_improvement_pct: float = 10.0
    ctr_strong_pct: float = 20.0
    ctr_decline_pct: float = -10.0
    ctr_strong_decline_pct: float = -20.0

    @classmethod
    def from_environment(cls) -> "EvaluationRules":
        return cls(
            minimum_impressions=int(os.getenv("SEO_EVAL_MIN_IMPRESSIONS", "100")),
            minimum_days=int(os.getenv("SEO_EVAL_MIN_DAYS", "14")),
            minimum_clicks=int(os.getenv("SEO_EVAL_MIN_CLICKS", "5")),
            retry_days=int(os.getenv("SEO_EVAL_RETRY_DAYS", "7")),
        )


class ExperimentEvaluationService:
    """Evaluate due experiments without placing calculation logic in the UI."""

    def __init__(
        self, database: Any, *, ai_service: Any | None = None,
        rules: EvaluationRules | None = None,
    ) -> None:
        self.database = database
        self.ai_service = ai_service if ai_service is not None else AIService()
        self.rules = rules or EvaluationRules.from_environment()
        self.logger = logging.getLogger(__name__)

    def find_due_experiments(
        self, reference_date: date | None = None
    ) -> list[dict[str, Any]]:
        today = reference_date or date.today()
        return [
            item for item in self.database.get_seo_experiments(
                statuses=("waiting_for_data", "ready_for_evaluation")
            )
            if item.get("started_at")
            and item.get("planned_evaluation_date")
            and date.fromisoformat(item["planned_evaluation_date"][:10]) <= today
            and item.get("baseline_start") and item.get("baseline_end")
        ]

    def evaluate_due_experiments(
        self, reference_date: date | None = None
    ) -> list[dict[str, Any]]:
        results = []
        for experiment in self.find_due_experiments(reference_date):
            try:
                results.append(self.evaluate_experiment(
                    experiment["id"], reference_date=reference_date
                ))
            except Exception as error:  # isolate each scheduled job
                self._recover_failure(experiment, error, reference_date)
                results.append({
                    "experiment_id": experiment["id"],
                    "result_status": "evaluation_failed",
                })
        return results

    def evaluate_experiment(
        self, experiment_id: int, *, reference_date: date | None = None
    ) -> dict[str, Any]:
        experiment = self.database.get_seo_experiment(experiment_id)
        if not experiment:
            raise ValueError(f"Eksperiment {experiment_id} findes ikke.")
        if experiment["status"] == "completed":
            existing = self.database.get_experiment_evaluations(experiment_id)
            return existing[0] if existing else experiment
        if experiment["status"] not in {
            "waiting_for_data", "ready_for_evaluation", "evaluating"
        }:
            raise ValueError("Eksperimentet er ikke klar til evaluering.")

        original_status = experiment["status"]
        self.database.update_seo_experiment(experiment_id, {"status": "evaluating"})
        try:
            periods = self._periods(experiment)
            after = self._comparison_data(experiment, periods)
            metrics = self.calculate_metrics(experiment, after)
            quality, caveats = self._sample_quality(metrics, periods)
            result_status = self.classify(metrics, quality, caveats)
            conclusion = self._ai_conclusion(metrics, result_status, caveats)
            evaluated = datetime.now().astimezone().isoformat(timespec="seconds")
            previous = next((
                item for item in self.database.get_experiment_evaluations(
                    experiment_id
                )
                if item["evaluation_version"] == EVALUATION_VERSION
                and item["baseline_start"] == periods["baseline_start"]
                and item["baseline_end"] == periods["baseline_end"]
                and item["comparison_start"] == periods["comparison_start"]
                and item["comparison_end"] == periods["comparison_end"]
            ), None)
            values = {
                "experiment_id": experiment_id,
                "website_id": experiment["website_id"],
                "target_url": experiment["target_url"],
                "implemented_at": experiment["started_at"],
                # Preserve the date that caused the first evaluation attempt;
                # planned_evaluation_date subsequently becomes the retry date.
                "evaluation_due_at": (
                    previous["evaluation_due_at"] if previous
                    else experiment["planned_evaluation_date"]
                ),
                "evaluated_at": evaluated,
                **periods, **metrics,
                "sample_quality": quality,
                "result_status": result_status,
                "ai_conclusion": conclusion,
                "caveats": caveats,
                "evaluation_version": EVALUATION_VERSION,
            }
            evaluation_id = self.database.save_experiment_evaluation(values)
            values["id"] = evaluation_id
            if result_status == "insufficient_data":
                next_date = (
                    date.fromisoformat(experiment["planned_evaluation_date"][:10])
                    if previous else
                    (reference_date or date.today()) + timedelta(
                        days=self.rules.retry_days
                    )
                )
                self.database.update_seo_experiment(experiment_id, {
                    "status": "waiting_for_data",
                    "result": "insufficient_data",
                    "result_summary": conclusion,
                    "planned_evaluation_date": next_date.isoformat(),
                })
            else:
                self.database.update_seo_experiment(experiment_id, {
                    "status": "completed", "result": result_status,
                    "result_summary": conclusion,
                    "actual_evaluation_date": evaluated,
                    "completed_at": evaluated,
                    "actual_click_change_pct": metrics["clicks_relative_change"],
                    "actual_impression_change_pct": metrics[
                        "impressions_relative_change"
                    ],
                    "actual_ctr_change": metrics["ctr_percentage_point_change"],
                    "actual_position_change": metrics["position_change"],
                })
            self.logger.info(json.dumps({
                "event": "experiment_evaluated", "experiment_id": experiment_id,
                "website_id": experiment["website_id"],
                "url": experiment["target_url"], "periods": periods,
                "data_points": periods["comparison_days"],
                "result": result_status,
            }, ensure_ascii=False))
            return values
        except Exception:
            self.database.update_seo_experiment(
                experiment_id, {"status": original_status}
            )
            raise

    @staticmethod
    def calculate_metrics(
        experiment: dict[str, Any], after: dict[str, Any]
    ) -> dict[str, Any]:
        before_clicks = int(experiment.get("baseline_clicks") or 0)
        after_clicks = int(after.get("clicks") or 0)
        before_impressions = int(experiment.get("baseline_impressions") or 0)
        after_impressions = int(after.get("impressions") or 0)
        before_ctr = float(experiment.get("baseline_ctr") or 0)
        after_ctr = float(after.get("ctr") or 0)
        before_position = float(experiment.get("baseline_position") or 0)
        after_position = float(after.get("average_position") or 0)
        return {
            "clicks_before": before_clicks, "clicks_after": after_clicks,
            "clicks_absolute_change": after_clicks - before_clicks,
            "clicks_relative_change": ExperimentEvaluationService._relative(
                before_clicks, after_clicks
            ),
            "impressions_before": before_impressions,
            "impressions_after": after_impressions,
            "impressions_absolute_change": after_impressions - before_impressions,
            "impressions_relative_change": ExperimentEvaluationService._relative(
                before_impressions, after_impressions
            ),
            "ctr_before": before_ctr, "ctr_after": after_ctr,
            "ctr_percentage_point_change": (after_ctr - before_ctr) * 100,
            "ctr_relative_change": ExperimentEvaluationService._relative(
                before_ctr, after_ctr
            ),
            "position_before": before_position, "position_after": after_position,
            # Positive means improvement because a lower position is better.
            "position_change": before_position - after_position,
        }

    def classify(
        self, metrics: dict[str, Any], quality: str, caveats: list[str]
    ) -> str:
        if quality == "insufficient":
            return "insufficient_data"
        ctr = metrics["ctr_relative_change"]
        clicks = metrics["clicks_relative_change"]
        impressions = metrics["impressions_relative_change"]
        position = metrics["position_change"]
        ctr_value = ctr if ctr is not None else 0
        click_value = clicks if clicks is not None else 0
        impression_value = impressions if impressions is not None else 0
        if ctr_value <= self.rules.ctr_strong_decline_pct and click_value <= -10:
            return "strong_decline"
        if ctr_value <= self.rules.ctr_decline_pct or click_value <= -10:
            return "decline"
        strong = (
            ctr_value >= self.rules.ctr_strong_pct and click_value >= 10
            and impression_value > -20 and position >= -1
        )
        # A large ranking gain is a confounder: do not claim a strong copy effect.
        if strong and position < 1:
            return "strong_improvement"
        if (
            ctr_value >= self.rules.ctr_improvement_pct or click_value >= 10
        ) and impression_value > -20 and position >= -1.5:
            return "improvement"
        return "neutral"

    def _periods(self, experiment: dict[str, Any]) -> dict[str, Any]:
        baseline_start = date.fromisoformat(experiment["baseline_start"][:10])
        baseline_end = date.fromisoformat(experiment["baseline_end"][:10])
        days = (baseline_end - baseline_start).days + 1
        comparison_start = date.fromisoformat(experiment["started_at"][:10]) + timedelta(days=1)
        comparison_end = comparison_start + timedelta(days=days - 1)
        return {
            "baseline_start": baseline_start.isoformat(),
            "baseline_end": baseline_end.isoformat(),
            "comparison_start": comparison_start.isoformat(),
            "comparison_end": comparison_end.isoformat(),
            "comparison_days": days,
        }

    def _comparison_data(
        self, experiment: dict[str, Any], periods: dict[str, Any]
    ) -> dict[str, Any]:
        dimension = "page_query" if experiment.get("target_query") else "page"
        rows = self.database.get_search_console_dimensions(
            dimension, website_id=experiment["website_id"],
            page_url=experiment["target_url"],
            period_start=periods["comparison_start"],
            period_end=periods["comparison_end"],
        )
        if experiment.get("target_query"):
            rows = [r for r in rows if r.get("query") == experiment["target_query"]]
        if not rows:
            return {"clicks": 0, "impressions": 0, "ctr": 0,
                    "average_position": 0, "missing": True}
        return rows[0]

    def _sample_quality(
        self, metrics: dict[str, Any], periods: dict[str, Any]
    ) -> tuple[str, list[str]]:
        caveats = []
        if periods["comparison_days"] < self.rules.minimum_days:
            caveats.append("Måleperioden indeholder for få dage.")
        if metrics["impressions_after"] < self.rules.minimum_impressions:
            caveats.append("Efterperioden har for få visninger.")
        if metrics["clicks_after"] < self.rules.minimum_clicks:
            caveats.append("Efterperioden har for få klik.")
        if metrics["position_change"] >= 1:
            caveats.append(
                "Placeringen blev også forbedret mærkbart, så effekten kan ikke "
                "tilskrives title eller meta alene."
            )
        return ("insufficient" if caveats[:3] else "sufficient", caveats)

    def _ai_conclusion(
        self, metrics: dict[str, Any], result: str, caveats: list[str]
    ) -> str:
        fallback = self._fallback_conclusion(metrics, result, caveats)
        if self.ai_service is None:
            return fallback
        prompt = (
            "Skriv 2-4 korte danske sætninger. Fortolk kun de givne tal, "
            "undgå sikker kausalitet, og ændr ikke status.\n"
            + json.dumps({
                "status": result, "status_label": RESULT_LABELS[result],
                "metrics": metrics, "forbehold": caveats,
            }, ensure_ascii=False)
        )
        try:
            text = self.ai_service.generate_response(prompt).text.strip()
            return text or fallback
        except (AIServiceError, Exception):
            return fallback

    @staticmethod
    def _fallback_conclusion(
        metrics: dict[str, Any], result: str, caveats: list[str]
    ) -> str:
        if result == "insufficient_data":
            return (
                "Der er endnu ikke data nok til at vurdere effekten af "
                "ændringen. Eksperimentet fortsætter, og systemet forsøger "
                "automatisk igen, når der er indsamlet mere data."
            )
        position = float(metrics.get("position_change") or 0)
        position_text = (
            "Den gennemsnitlige placering var stort set uændret, hvilket "
            "gør det mindre sandsynligt, at udviklingen alene skyldes bedre "
            "placeringer."
            if abs(position) < .5 else
            "Placeringen ændrede sig også mærkbart, så effekten kan ikke "
            "tilskrives title og metabeskrivelse alene."
        )
        if result in {"strong_improvement", "improvement"}:
            opening = (
                "Klikraten steg markant samtidig med, at antallet af klik "
                "voksede."
                if result == "strong_improvement" else
                "Klikraten og antallet af klik udviklede sig positivt."
            )
            ending = (
                f"Resultatet vurderes som {RESULT_LABELS[result].lower()}, "
                "men bør fortsat følges over tid."
            )
        elif result in {"strong_decline", "decline"}:
            opening = (
                "Klikraten eller antallet af klik udviklede sig negativt i "
                "måleperioden."
            )
            ending = (
                f"Resultatet vurderes som {RESULT_LABELS[result].lower()}, "
                "men datagrundlaget bør følges, før ændringen tilbageføres."
            )
        else:
            opening = "Udviklingen viser ingen tydelig samlet effekt."
            ending = (
                "Resultatet vurderes som ingen tydelig ændring, og en ny "
                "variant kan overvejes senere."
            )
        return " ".join((opening, position_text, ending))

    def _recover_failure(
        self, experiment: dict[str, Any], error: Exception,
        reference_date: date | None,
    ) -> None:
        next_date = (reference_date or date.today()) + timedelta(
            days=self.rules.retry_days
        )
        self.database.update_seo_experiment(experiment["id"], {
            "status": "waiting_for_data", "result": "evaluation_failed",
            "result_summary": "Evalueringen mislykkedes og forsøges igen.",
            "planned_evaluation_date": next_date.isoformat(),
        })
        self.logger.exception(json.dumps({
            "event": "experiment_evaluation_failed",
            "experiment_id": experiment["id"],
            "website_id": experiment["website_id"],
            "url": experiment["target_url"], "error_type": type(error).__name__,
        }, ensure_ascii=False))

    @staticmethod
    def _relative(before: float, after: float) -> float | None:
        return ((after - before) / before * 100) if before else None
