"""Deterministic root-cause analysis of Search Console traffic losses."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


MINIMUM_PREVIOUS_CLICKS = 20
MINIMUM_SITE_CLICK_LOSS = 5
MINIMUM_SITE_DECLINE_PERCENT = 5.0
MINIMUM_PAGE_PREVIOUS_CLICKS = 3
MINIMUM_PAGE_CLICK_LOSS = 2
MAX_LOSS_PAGES = 5
MAX_QUERIES_PER_PAGE = 3


class SearchConsoleDiagnosisService:
    """Explain documented click losses without AI inference."""

    def __init__(self, database: Any, comparison_service: Any) -> None:
        self.database = database
        self.comparison_service = comparison_service

    def analyze_site(self, website_id: str) -> dict[str, Any]:
        """Analyze and persist the latest two comparable 28-day periods."""
        pages = self.comparison_service.get_dimension_comparisons(
            website_id, "page"
        )
        page_queries = self.comparison_service.get_dimension_comparisons(
            website_id, "page_query"
        )
        diagnosis = build_search_console_diagnosis(
            website_id, pages, page_queries
        )
        if diagnosis["status"] != "missing_periods":
            diagnosis["write_action"] = (
                self.database.upsert_search_console_diagnosis(diagnosis)
            )
        else:
            diagnosis["write_action"] = "skipped"
        return diagnosis

    def analyze_sites(self, website_ids: list[str]) -> dict[str, Any]:
        """Analyze websites independently and summarize persistence."""
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


def build_search_console_diagnosis(
    website_id: str,
    page_comparisons: list[dict[str, Any]],
    page_query_comparisons: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one evidence-only diagnosis from stored period comparisons."""
    if not isinstance(page_comparisons, list) or not page_comparisons:
        return {
            "website_id": website_id,
            "status": "missing_periods",
            "data_quality": "insufficient",
            "reason": "Der mangler to sammenlignelige 28-dages perioder.",
            "previous_clicks": 0,
            "current_clicks": 0,
            "click_loss": 0,
            "loss_pages": [],
        }
    sample = page_comparisons[0]
    period_fields = {
        key: str(sample[key])
        for key in (
            "period_start", "period_end",
            "previous_period_start", "previous_period_end",
        )
    }
    owned_pages = [
        item for item in page_comparisons
        if _belongs_to_website(item.get("page_url"), website_id)
    ]
    previous_clicks = sum(
        int(item.get("previous_clicks", 0)) for item in owned_pages
    )
    current_clicks = sum(
        int(item.get("current_clicks", 0)) for item in owned_pages
    )
    click_loss = max(0, previous_clicks - current_clicks)
    base = {
        "website_id": website_id,
        **period_fields,
        "previous_clicks": previous_clicks,
        "current_clicks": current_clicks,
        "click_loss": click_loss,
    }
    if previous_clicks < MINIMUM_PREVIOUS_CLICKS:
        return {
            **base,
            "status": "insufficient_data",
            "data_quality": "insufficient",
            "reason": (
                f"Forrige periode har kun {previous_clicks} klik; "
                f"minimum er {MINIMUM_PREVIOUS_CLICKS}."
            ),
            "loss_pages": [],
        }
    if current_clicks >= previous_clicks:
        return {
            **base,
            "status": "no_decline",
            "data_quality": "good",
            "reason": "Det samlede antal klik er ikke faldet.",
            "loss_pages": [],
        }
    decline_percent = click_loss / previous_clicks * 100
    if (
        click_loss < MINIMUM_SITE_CLICK_LOSS
        or decline_percent < MINIMUM_SITE_DECLINE_PERCENT
    ):
        return {
            **base,
            "status": "minor_decline",
            "data_quality": "good",
            "decline_percent": round(decline_percent, 1),
            "reason": (
                "Faldet er mindre end støjgrænsen på "
                f"{MINIMUM_SITE_CLICK_LOSS} klik og "
                f"{MINIMUM_SITE_DECLINE_PERCENT:.0f} %."
            ),
            "loss_pages": [],
        }

    queries_by_page: dict[str, list[dict[str, Any]]] = {}
    for item in page_query_comparisons:
        page_url = str(item.get("page_url", ""))
        if not _belongs_to_website(page_url, website_id):
            continue
        query_loss = int(item.get("previous_clicks", 0)) - int(
            item.get("current_clicks", 0)
        )
        if page_url and query_loss > 0:
            queries_by_page.setdefault(page_url, []).append({
                "query": str(item.get("query", "")),
                "previous_clicks": int(item.get("previous_clicks", 0)),
                "current_clicks": int(item.get("current_clicks", 0)),
                "click_loss": query_loss,
            })

    loss_pages = []
    for item in owned_pages:
        previous = int(item.get("previous_clicks", 0))
        current = int(item.get("current_clicks", 0))
        loss = previous - current
        if (
            previous < MINIMUM_PAGE_PREVIOUS_CLICKS
            or loss < MINIMUM_PAGE_CLICK_LOSS
        ):
            continue
        page_url = str(item.get("page_url", ""))
        queries = sorted(
            queries_by_page.get(page_url, []),
            key=lambda row: (-row["click_loss"], row["query"]),
        )[:MAX_QUERIES_PER_PAGE]
        loss_pages.append({
            "page_url": page_url,
            "previous_clicks": previous,
            "current_clicks": current,
            "click_loss": loss,
            "previous_impressions": int(item.get("previous_impressions", 0)),
            "current_impressions": int(item.get("current_impressions", 0)),
            "previous_ctr": float(item.get("previous_ctr", 0)),
            "current_ctr": float(item.get("current_ctr", 0)),
            "previous_position": float(item.get("previous_position", 0)),
            "current_position": float(item.get("current_position", 0)),
            "cause": _classify_page_loss(item),
            "queries": queries,
        })
    loss_pages.sort(key=lambda row: (-row["click_loss"], row["page_url"]))
    loss_pages = loss_pages[:MAX_LOSS_PAGES]
    explained_loss = min(
        click_loss, sum(item["click_loss"] for item in loss_pages)
    )
    return {
        **base,
        "status": "ready",
        "data_quality": "good" if loss_pages else "limited",
        "reason": (
            "Klikfaldet er fordelt på de største dokumenterede sidetab."
            if loss_pages else
            "Det samlede fald er for spredt eller for lille pr. side."
        ),
        "explained_click_loss": explained_loss,
        "explained_loss_share": (
            round(explained_loss / click_loss * 100, 1) if click_loss else 0
        ),
        "loss_pages": loss_pages,
    }


def _classify_page_loss(item: dict[str, Any]) -> str:
    """Classify only strong, observable signals in one page comparison."""
    previous_impressions = int(item.get("previous_impressions", 0))
    current_impressions = int(item.get("current_impressions", 0))
    previous_ctr = float(item.get("previous_ctr", 0))
    current_ctr = float(item.get("current_ctr", 0))
    previous_position = float(item.get("previous_position", 0))
    current_position = float(item.get("current_position", 0))
    position_change = current_position - previous_position
    ctr_change = current_ctr - previous_ctr
    impression_change = (
        (current_impressions - previous_impressions) / previous_impressions
        if previous_impressions else 0
    )
    if (
        previous_impressions > 0 and current_impressions > 0
        and position_change >= 1.0
    ):
        return "Placeringsfald"
    if previous_impressions > 0 and ctr_change <= -0.01:
        return "CTR-fald"
    if impression_change <= -0.20 and abs(position_change) < 1.0:
        return "Lavere søgeefterspørgsel"
    return "Blandet eller uklar årsag"


def _belongs_to_website(page_url: Any, website_id: str) -> bool:
    """Reject cross-domain URLs from canonical or redirect signals."""
    try:
        host = (urlsplit(str(page_url)).hostname or "").lower()
    except ValueError:
        return False
    if host.startswith("www."):
        host = host[4:]
    expected = str(website_id).strip().lower()
    if expected.startswith("www."):
        expected = expected[4:]
    return bool(host) and host == expected
