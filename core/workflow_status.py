"""Canonical lifecycle states and transition validation for SEO work."""

from __future__ import annotations


WORK_QUEUE_TRANSITIONS = {
    "queued": {"skipped", "awaiting_implementation", "cancelled"},
    "skipped": {"queued", "awaiting_implementation", "cancelled"},
    "awaiting_implementation": {"implemented", "queued", "cancelled"},
    "implemented": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

DRAFT_TRANSITIONS = {
    "awaiting_approval": {"converted_to_experiment", "rejected"},
    "converted_to_experiment": {"approved", "rejected"},
    "approved": {"completed"},
    "rejected": set(),
    "completed": set(),
}

APPROVED_CHANGE_TRANSITIONS = {
    "awaiting_implementation": {"measurement_period", "needs_review"},
    "measurement_period": {"ready_for_evaluation", "completed", "needs_review"},
    "ready_for_evaluation": {"completed", "needs_review"},
    "completed": set(),
    "needs_review": {"awaiting_implementation"},
}

EXPERIMENT_TRANSITIONS = {
    "planned": {"approved", "cancelled"},
    "approved": {"waiting_for_data", "cancelled"},
    "running": {"waiting_for_data", "cancelled"},
    "waiting_for_data": {"ready_for_evaluation", "completed", "cancelled"},
    "ready_for_evaluation": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def validate_transition(
    machine: dict[str, set[str]], previous: str, new: str, entity: str
) -> None:
    """Allow a no-op retry and reject every undocumented state change."""
    if previous == new:
        return
    if previous not in machine or new not in machine[previous]:
        raise ValueError(
            f"Ulovlig statusovergang for {entity}: {previous} → {new}."
        )
