"""Deterministic page-level revenue effect for an SEO change.

Attributes Partner Ads commission to a specific page — via the sale's ``uid``
page path — and compares the window before a change to the window after. The
comparison is only as trustworthy as the number of sales behind it, so a
confidence signal is returned alongside the figures.

By design this measures forward from the change date, where uid coverage is
best; it never claims a conclusion the sale volume cannot support.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib.parse import urlsplit


DEFAULT_WINDOW_DAYS = 28
DEFAULT_MIN_SALES = 3


@dataclass(frozen=True)
class PageRevenueEffect:
    matched: bool
    baseline_total: Decimal
    baseline_sales: int
    after_total: Decimal
    after_sales: int
    delta: Decimal
    delta_pct: float | None
    window_days: int
    after_complete: bool
    confidence: str
    confidence_label: str


def compute_page_revenue_effect(
    records: Iterable[dict[str, Any]],
    *,
    target_url: str,
    change_date: date,
    today: date | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_sales: int = DEFAULT_MIN_SALES,
) -> PageRevenueEffect:
    """Compare page commission in the window before and after a change."""
    today = today or date.today()
    target_domain = _domain(target_url)
    target_path = _norm_path(_path(target_url))

    baseline_start = change_date - timedelta(days=window_days)
    after_end = change_date + timedelta(days=window_days)

    baseline_total = Decimal("0")
    baseline_sales = 0
    after_total = Decimal("0")
    after_sales = 0
    matched = False

    for record in records:
        parsed = _parse(record)
        if parsed is None:
            continue
        sale_date, provision, url, uid = parsed
        if _domain(url) != target_domain:
            continue
        if _norm_path(uid) != target_path:
            continue
        matched = True
        if baseline_start <= sale_date < change_date:
            baseline_total += provision
            baseline_sales += 1
        elif change_date <= sale_date < after_end:
            after_total += provision
            after_sales += 1

    after_complete = today >= after_end
    delta = after_total - baseline_total
    delta_pct = float(delta / baseline_total * 100) if baseline_total else None
    confidence, label = _confidence(
        baseline_sales, after_sales, min_sales, after_complete
    )
    return PageRevenueEffect(
        matched=matched,
        baseline_total=baseline_total,
        baseline_sales=baseline_sales,
        after_total=after_total,
        after_sales=after_sales,
        delta=delta,
        delta_pct=delta_pct,
        window_days=window_days,
        after_complete=after_complete,
        confidence=confidence,
        confidence_label=label,
    )


def _confidence(
    baseline_sales: int, after_sales: int, min_sales: int, after_complete: bool
) -> tuple[str, str]:
    if not after_complete:
        return "pending", "Måleperioden er ikke slut endnu."
    if baseline_sales < min_sales and after_sales < min_sales:
        return "insufficient", "For få salg til en sikker konklusion."
    if baseline_sales < min_sales or after_sales < min_sales:
        return "low", "Svagt datagrundlag – tolk med forbehold."
    return "ok", "Tilstrækkeligt datagrundlag til en forsigtig konklusion."


def _parse(record: dict[str, Any]) -> tuple[date, Decimal, str, str] | None:
    if str(record.get("valuta", "DKK")).upper() != "DKK":
        return None
    try:
        day, month, year = (
            int(part) for part in str(record["dato"]).split("-")
        )
        sale_date = date(year, month, day)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    try:
        provision = Decimal(str(record["provision"]))
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return None
    return (
        sale_date,
        provision,
        str(record.get("url", "") or ""),
        str(record.get("uid", "") or ""),
    )


def _domain(url: str) -> str:
    netloc = urlsplit(url).netloc.lower()
    if not netloc:
        netloc = urlsplit(f"//{url}").netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _path(url: str) -> str:
    path = urlsplit(url).path
    if not path and "/" not in url:
        return ""
    return path


def _norm_path(path: str) -> str:
    """Normalize a page path so trailing-slash and case differences match."""
    cleaned = (path or "").strip().lower()
    if "[" in cleaned or "]" in cleaned:
        return ""
    cleaned = cleaned.rstrip("/")
    return cleaned
