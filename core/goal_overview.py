"""Deterministic revenue-versus-goal overview from Partner Ads commission.

Pure functions over commission records so the whole overview is testable without
a database. Mirrors the storage rules used elsewhere: dates are ``D-M-YYYY``,
only DKK sales count, and the source website is the ``url`` domain without
``www.``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib.parse import urlsplit


DEFAULT_TARGET_LOW = Decimal("20000")
DEFAULT_TARGET_HIGH = Decimal("25000")
DEFAULT_WINDOW_MONTHS = 6
DEFAULT_HISTORY_MONTHS = 12


@dataclass(frozen=True)
class MonthlyCommission:
    year: int
    month: int
    total: Decimal
    sales: int


@dataclass(frozen=True)
class WebsiteCommission:
    website: str
    total: Decimal
    sales: int
    share: float


@dataclass(frozen=True)
class GoalOverview:
    today: date
    current_month: MonthlyCommission
    history: list[MonthlyCommission]
    rolling_average: Decimal
    window_months: int
    months_with_data: int
    target_low: Decimal
    target_high: Decimal
    status: str
    status_label: str
    progress_to_low: float
    by_website: list[WebsiteCommission]
    website_period_months: int


def build_goal_overview(
    records: Iterable[dict[str, Any]],
    *,
    today: date,
    target_low: Decimal = DEFAULT_TARGET_LOW,
    target_high: Decimal = DEFAULT_TARGET_HIGH,
    window_months: int = DEFAULT_WINDOW_MONTHS,
    history_months: int = DEFAULT_HISTORY_MONTHS,
) -> GoalOverview:
    """Aggregate commission into a goal- and website-oriented overview."""
    monthly: dict[tuple[int, int], list] = {}
    website_totals: dict[str, list] = {}

    history_keys = _month_sequence(today.year, today.month, history_months)
    history_set = set(history_keys)

    for record in records:
        parsed = _parse_record(record)
        if parsed is None:
            continue
        year, month, provision, url = parsed
        bucket = monthly.setdefault((year, month), [Decimal("0"), 0])
        bucket[0] += provision
        bucket[1] += 1
        if (year, month) in history_set:
            site = website_totals.setdefault(_domain(url), [Decimal("0"), 0])
            site[0] += provision
            site[1] += 1

    current_key = (today.year, today.month)
    current_month = MonthlyCommission(
        today.year, today.month, *_bucket(monthly, current_key)
    )

    history = [
        MonthlyCommission(year, month, *_bucket(monthly, (year, month)))
        for year, month in history_keys
    ]

    rolling_average, months_with_data = _rolling_average(
        monthly, today=today, window_months=window_months
    )
    status, status_label = _classify(
        rolling_average, months_with_data, target_low, target_high
    )
    progress_to_low = (
        float(rolling_average / target_low) if target_low else 0.0
    )

    window_total = sum((total for total, _ in website_totals.values()), Decimal("0"))
    by_website = [
        WebsiteCommission(
            website=name,
            total=total,
            sales=sales,
            share=float(total / window_total) if window_total else 0.0,
        )
        for name, (total, sales) in website_totals.items()
    ]
    by_website.sort(key=lambda item: (item.total, item.sales), reverse=True)

    return GoalOverview(
        today=today,
        current_month=current_month,
        history=history,
        rolling_average=rolling_average,
        window_months=window_months,
        months_with_data=months_with_data,
        target_low=target_low,
        target_high=target_high,
        status=status,
        status_label=status_label,
        progress_to_low=progress_to_low,
        by_website=by_website,
        website_period_months=history_months,
    )


def _parse_record(
    record: dict[str, Any],
) -> tuple[int, int, Decimal, str] | None:
    """Return (year, month, provision, url) for a valid DKK sale."""
    if str(record.get("valuta", "DKK")).upper() != "DKK":
        return None
    try:
        day, month, year = (
            int(part) for part in str(record["dato"]).split("-")
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    try:
        provision = Decimal(str(record["provision"]))
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return None
    return year, month, provision, str(record.get("url", "") or "")


def _domain(url: str) -> str:
    """Return the source website domain without a scheme or ``www.``."""
    netloc = urlsplit(url).netloc.lower()
    if not netloc:
        netloc = urlsplit(f"//{url}").netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or "Ukendt"


def _bucket(monthly: dict, key: tuple[int, int]) -> tuple[Decimal, int]:
    total, sales = monthly.get(key, [Decimal("0"), 0])
    return total, sales


def _rolling_average(
    monthly: dict, *, today: date, window_months: int
) -> tuple[Decimal, int]:
    """Average over completed months in the window, from the first data month."""
    if not monthly:
        return Decimal("0"), 0
    earliest = min(monthly)
    previous = _shift_month(today.year, today.month, -1)
    window = _month_sequence(previous[0], previous[1], window_months)
    considered = [key for key in window if key >= earliest]
    if not considered:
        return Decimal("0"), 0
    total = sum(
        (monthly.get(key, [Decimal("0"), 0])[0] for key in considered),
        Decimal("0"),
    )
    return (total / len(considered)), len(considered)


def _classify(
    rolling_average: Decimal,
    months_with_data: int,
    target_low: Decimal,
    target_high: Decimal,
) -> tuple[str, str]:
    if months_with_data == 0:
        return "no_data", "Ikke nok historik endnu"
    if rolling_average < target_low:
        return "under", "Under målet"
    if rolling_average <= target_high:
        return "in_band", "I målbåndet"
    return "over", "Over målet"


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


def _month_sequence(
    end_year: int, end_month: int, count: int
) -> list[tuple[int, int]]:
    """Return ``count`` months ending at (end_year, end_month), chronological."""
    if count < 1:
        return []
    keys = [_shift_month(end_year, end_month, -offset) for offset in range(count)]
    return list(reversed(keys))
