"""Explicit background orchestration for SEO experiment writes."""

from datetime import date
from typing import Any

from core.experiment_evaluation import ExperimentEvaluationService
from core.experiment_monitoring import ExperimentMonitoringService


class ExperimentAutomationService:
    """Run monitoring and due evaluations outside dashboard rendering."""

    def __init__(
        self, database: Any, *, monitoring: Any | None = None,
        evaluation: Any | None = None,
    ) -> None:
        self.monitoring = monitoring or ExperimentMonitoringService(database)
        self.evaluation = evaluation or ExperimentEvaluationService(database)

    def run_after_search_console_sync(
        self, reference_date: date | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Persist fresh pulses, then evaluate experiments that are due."""
        monitored = self.monitoring.update_active_experiments(reference_date)
        evaluated = self.evaluation.evaluate_due_experiments(reference_date)
        return {"monitored": monitored, "evaluated": evaluated}
