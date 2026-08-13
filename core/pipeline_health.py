"""Health summary for the daily data-refresh pipeline.

Turns the latest persisted feature runs into user-facing warnings so a
failing or stalled daily refresh is visible immediately — for any step and
any integration, not just Search Console. Pure and side-effect free, so it
is safe to call on every page render.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

STALE_AFTER = timedelta(days=2)
REFRESH_FEATURE = "data_refresh_all"
STEP_PREFIX = "data_refresh:"


def pipeline_health(
    feature_runs: dict[str, dict[str, Any]] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Summarize daily-refresh health from the latest feature runs.

    Returns ``{"ok": bool, "warnings": [str, ...]}``. A warning is added when
    the whole refresh has not completed recently (the scheduled task may be
    broken or not running) and when individual steps failed in their latest
    run (the data grounding those steps may be stale).
    """
    runs = feature_runs or {}
    reference = now or datetime.now().astimezone()
    warnings: list[str] = []

    overall = runs.get(REFRESH_FEATURE)
    last_completed = _parse_dt((overall or {}).get("completed_at"))
    if last_completed is None:
        warnings.append(
            "Den daglige opdatering er aldrig kørt helt igennem. Kør den, "
            "eller kontrollér den planlagte opgave i Windows Opgavestyring."
        )
    elif reference - last_completed >= STALE_AFTER:
        days = (reference - last_completed).days
        warnings.append(
            f"Den daglige opdatering er ikke kørt siden "
            f"{last_completed.date().isoformat()} ({days} dage). "
            "Datagrundlaget er forældet — kontrollér den planlagte opgave."
        )

    failed = sorted(
        name[len(STEP_PREFIX):]
        for name, run in runs.items()
        if name.startswith(STEP_PREFIX)
        and str((run or {}).get("status")) == "error"
    )
    if failed:
        warnings.append(
            "Trin der fejlede i seneste opdatering: "
            + ", ".join(failed)
            + ". Datagrundlaget for disse kan være forældet."
        )

    return {"ok": not warnings, "warnings": warnings}


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()
