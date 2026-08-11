"""Historical Partner Ads import that never sends notifications.

The live monitor only imports forward from the day it first ran, so sales from
before that are missing. This backfill imports an explicit period idempotently
(by ``kombiid``) and marks every newly stored sale as ``skipped`` so the live
monitor never sends a late Telegram message for old sales.

By construction the function takes no Telegram service and cannot notify.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def backfill_sales(
    database: Any,
    partner_ads: Any,
    *,
    start_date: date,
    end_date: date,
    mark_status: str = "skipped",
) -> dict[str, int]:
    """Import all sales in [start_date, end_date] without notifying.

    Returns counts of fetched, created, updated, unchanged and duplicate rows.
    """
    _, sales = partner_ads.fetch_sales(start_date=start_date, end_date=end_date)
    result = {
        "fetched": len(sales),
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "duplicates": 0,
    }
    seen: set[str] = set()
    for sale in sales:
        kombiid = str(sale.get("kombiid", "")).strip()
        if not kombiid:
            continue
        if kombiid in seen:
            result["duplicates"] += 1
            continue
        seen.add(kombiid)
        outcome = database.upsert_partner_ads_sale(sale)
        if outcome == "created":
            result["created"] += 1
            _mark_skipped(database, kombiid, mark_status)
        elif outcome == "updated":
            result["updated"] += 1
        else:
            result["unchanged"] += 1
    return result


def _mark_skipped(database: Any, kombiid: str, status: str) -> None:
    """Record that we deliberately did not notify about this sale."""
    setter = getattr(database, "set_partner_ads_notification_status", None)
    if callable(setter):
        try:
            setter(kombiid, status)
        except Exception:
            pass
