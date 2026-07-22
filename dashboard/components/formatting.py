"""Shared Danish presentation formatting for dashboard values."""

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo


COPENHAGEN = ZoneInfo("Europe/Copenhagen")
DATE_FIELDS = {"dato", "date", "metric_date", "history_date", "briefing_date"}
TIME_FIELDS = {"tidspunkt", "time"}
DATETIME_SUFFIXES = ("_at", "_time", "_timestamp", "_sync", "_scan")
MONEY_FIELDS = {"omsaetning", "provision", "revenue", "commission"}
STATUS_LABELS = {
    "active": "Aktiv",
    "inactive": "Inaktiv",
    "planning": "Planlagt",
    "ready": "Klar",
    "in_progress": "I gang",
    "queued": "I kø",
    "skipped": "Sprunget over",
    "awaiting_approval": "Klar til godkendelse",
    "converted_to_experiment": "Afventer implementering",
    "approved": "Implementeret",
    "awaiting_implementation": "Afventer implementering",
    "implemented": "Måleperiode",
    "running": "Måleperiode",
    "waiting_for_data": "Måleperiode",
    "ready_for_evaluation": "Klar til evaluering",
    "evaluating": "Evaluerer",
    "insufficient_data": "Utilstrækkelige data",
    "evaluation_failed": "Evaluering mislykkedes",
    "strong_improvement": "Stor forbedring",
    "improvement": "Forbedring",
    "neutral": "Ingen tydelig ændring",
    "decline": "Forværring",
    "strong_decline": "Stor forværring",
    "completed": "Afsluttet",
    "cancelled": "Annulleret",
    "rejected": "Afvist",
    "needs_review": "Kræver gennemgang",
    "phasing_out": "Udfases",
    "archived": "Arkiveret",
    "failed": "Fejl",
}


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif value:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            for pattern in ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y", "%H:%M:%S"):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
            else:
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=COPENHAGEN)
    return parsed.astimezone(COPENHAGEN)


def format_date(value: Any, fallback: str = "Ukendt") -> str:
    parsed = _datetime(value)
    return parsed.strftime("%d.%m.%Y") if parsed else fallback


def format_time(value: Any, fallback: str = "Ukendt") -> str:
    parsed = _datetime(value)
    return parsed.strftime("%H:%M") if parsed else fallback


def format_datetime(value: Any, fallback: str = "Ukendt") -> str:
    parsed = _datetime(value)
    return parsed.strftime("%d.%m.%Y kl. %H:%M") if parsed else fallback


def format_currency(value: Any, fallback: str = "0,00 kr.") -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return fallback
    return (
        f"{amount:,.2f}".translate(str.maketrans({",": ".", ".": ","}))
        + " kr."
    )


def format_status(value: Any, fallback: str = "Ikke angivet") -> str:
    if value in (None, ""):
        return fallback
    text = str(value)
    return STATUS_LABELS.get(text, text.replace("_", " ").capitalize())


def format_ai_assessment(value: Any, include_percent: bool = False) -> str:
    """Present an internal confidence value as a Danish assessment."""
    try:
        score = float(value or 0)
    except (TypeError, ValueError):
        return "Ikke vurderet"
    label = (
        "Meget høj" if score >= 90 else "Høj" if score >= 75
        else "Middel" if score >= 60 else "Lav"
    )
    return f"{label} ({score:.0f} %)" if include_percent else label


def format_dashboard_value(field: str, value: Any) -> Any:
    """Format recognized display fields while leaving other data untouched."""
    key = field.lower()
    if value in (None, ""):
        return value
    if key in MONEY_FIELDS:
        return format_currency(value)
    if key == "status" or key.endswith("_status"):
        return format_status(value)
    if key in TIME_FIELDS:
        return format_time(value, str(value))
    if key in DATE_FIELDS:
        return format_date(value, str(value))
    if key.endswith(DATETIME_SUFFIXES):
        return format_datetime(value, str(value))
    if key.startswith("seneste ") or "tidspunkt" in key:
        parsed = _datetime(value)
        return format_datetime(parsed, str(value)) if parsed else value
    return value


def format_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: format_dashboard_value(key, value) for key, value in row.items()}
        for row in rows
    ]
