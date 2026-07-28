"""Deterministic comparison of two complete Plausible traffic periods."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


PERIOD_DAYS = 28
MINIMUM_PREVIOUS_VISITORS = 100
MINIMUM_VISITOR_LOSS = 20
MINIMUM_DECLINE_PERCENT = 10.0


class PlausibleDiagnosisService:
    """Classify stored visitor development without external or AI calls."""

    def __init__(self, database: Any) -> None:
        self.database = database

    def analyze_site(self, website_id: str) -> dict[str, Any]:
        rows = self.database.get_plausible_daily_metrics(
            website_id=website_id
        )
        diagnosis = build_plausible_diagnosis(website_id, rows)
        if diagnosis["status"] != "missing_periods":
            diagnosis["write_action"] = (
                self.database.upsert_plausible_diagnosis(diagnosis)
            )
        else:
            diagnosis["write_action"] = "skipped"
        return diagnosis

    def analyze_sites(self, website_ids: list[str]) -> dict[str, Any]:
        results = [self.analyze_site(item) for item in sorted(set(website_ids))]
        return {
            "websites_processed": len(results),
            "rows_created": sum(
                item["write_action"] == "created" for item in results
            ),
            "rows_updated": sum(
                item["write_action"] == "updated" for item in results
            ),
            "rows_unchanged": sum(
                item["write_action"] == "unchanged" for item in results
            ),
            "results": results,
        }


def build_plausible_diagnosis(
    website_id: str, metrics: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compare the latest 28 stored calendar days with the preceding 28."""
    if not isinstance(metrics, list):
        return _missing(website_id)
    by_date = {
        date.fromisoformat(str(item["metric_date"])): int(item["visitors"])
        for item in metrics
    }
    if not by_date:
        return _missing(website_id)
    current_end = max(by_date)
    current_start = current_end - timedelta(days=PERIOD_DAYS - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=PERIOD_DAYS - 1)
    current_dates = [
        current_start + timedelta(days=offset)
        for offset in range(PERIOD_DAYS)
    ]
    previous_dates = [
        previous_start + timedelta(days=offset)
        for offset in range(PERIOD_DAYS)
    ]
    if (
        any(item not in by_date for item in current_dates)
        or any(item not in by_date for item in previous_dates)
    ):
        return _missing(
            website_id,
            reason=(
                "Der mangler dagstal til to komplette, sammenhængende "
                "28-dages perioder."
            ),
        )
    current_visitors = sum(by_date[item] for item in current_dates)
    previous_visitors = sum(by_date[item] for item in previous_dates)
    visitor_change = current_visitors - previous_visitors
    visitor_change_percent = (
        visitor_change / previous_visitors * 100
        if previous_visitors else None
    )
    base = {
        "website_id": website_id,
        "period_start": current_start.isoformat(),
        "period_end": current_end.isoformat(),
        "previous_period_start": previous_start.isoformat(),
        "previous_period_end": previous_end.isoformat(),
        "previous_visitors": previous_visitors,
        "current_visitors": current_visitors,
        "visitor_change": visitor_change,
        "visitor_change_percent": (
            round(visitor_change_percent, 1)
            if visitor_change_percent is not None else None
        ),
    }
    if previous_visitors < MINIMUM_PREVIOUS_VISITORS:
        return {
            **base,
            "status": "insufficient_data",
            "data_quality": "insufficient",
            "reason": (
                f"Forrige periode har kun {previous_visitors} besøgende; "
                f"minimum er {MINIMUM_PREVIOUS_VISITORS}."
            ),
        }
    if visitor_change >= 0:
        return {
            **base,
            "status": "growth" if visitor_change > 0 else "stable",
            "data_quality": "good",
            "reason": (
                "Besøgstallet er steget."
                if visitor_change > 0 else "Besøgstallet er uændret."
            ),
        }
    visitor_loss = abs(visitor_change)
    decline_percent = abs(float(visitor_change_percent or 0))
    if (
        visitor_loss < MINIMUM_VISITOR_LOSS
        or decline_percent < MINIMUM_DECLINE_PERCENT
    ):
        return {
            **base,
            "status": "minor_decline",
            "data_quality": "good",
            "reason": (
                "Faldet er mindre end støjgrænsen på "
                f"{MINIMUM_VISITOR_LOSS} besøgende og "
                f"{MINIMUM_DECLINE_PERCENT:.0f} %."
            ),
        }
    return {
        **base,
        "status": "significant_decline",
        "data_quality": "good",
        "reason": "Plausible dokumenterer et væsentligt fald i besøgende.",
    }


def _missing(
    website_id: str,
    *,
    reason: str = "Der er endnu ingen gemte Plausible-data.",
) -> dict[str, Any]:
    return {
        "website_id": website_id,
        "status": "missing_periods",
        "data_quality": "insufficient",
        "reason": reason,
        "previous_visitors": 0,
        "current_visitors": 0,
        "visitor_change": 0,
        "visitor_change_percent": None,
    }
