"""Per-website SEO roadmap.

Combine the measured signals the app already stores — Search Console (pages and
queries), Partner-ads commission per page, and Plausible visitors — into a
strategic roadmap: a handful of concrete, goal-setting opportunities plus the
income-first experiment sequence that works toward them. The roadmap is
deterministic; an optional AI service only phrases the narrative summary.
"""

from __future__ import annotations

import json
from typing import Any

from core.decision_engine import (
    CONTENT_GAP_MIN_IMPRESSIONS, CONTENT_GAP_MIN_POSITION,
)
from core.revenue_attribution import page_key_for_url, revenue_by_page


# A page with real impressions but little commission is money left on the table.
MONEY_GAP_MIN_IMPRESSIONS = 100
MONEY_GAP_MAX_COMMISSION = 50.0
# A query ranking just off (or at the bottom of) page 1 can realistically be
# lifted toward the top — the classic "striking distance" opportunity.
STRIKING_MIN_POSITION = 5.0
STRIKING_MAX_POSITION = 20.0
STRIKING_MIN_IMPRESSIONS = 100
# A page already earning is only worth growing once it ranks below the top few.
EARNER_GROWTH_MIN_POSITION = 3.0
PLAUSIBLE_WINDOW_DAYS = 28
RECOMMENDED_SEQUENCE_LIMIT = 8
EXAMPLE_LIMIT = 10


def build_website_roadmap(
    database: Any, website_id: str, *,
    decision_engine: Any | None = None, ai_service: Any | None = None,
) -> dict[str, Any]:
    """Return one website's roadmap: summary metrics, goals, and next steps."""
    pages = _latest_period_rows(database, website_id, "page")
    queries = _latest_period_rows(database, website_id, "page_query")
    revenue = revenue_by_page(database.get_commission_records())

    def commission(url: str) -> float:
        return float(revenue.get(page_key_for_url(url), 0.0))

    summary = _summary(database, website_id, pages, commission)
    goals = _goals(pages, queries, commission)
    sequence = _recommended_sequence(database, website_id, decision_engine)
    roadmap = {
        "website_id": website_id,
        "summary": summary,
        "goals": goals,
        "recommended_sequence": sequence,
    }
    roadmap["narrative"] = _narrative(roadmap, ai_service)
    return roadmap


def _summary(
    database: Any, website_id: str, pages: list[dict[str, Any]],
    commission: Any,
) -> dict[str, Any]:
    impressions = sum(int(page["impressions"]) for page in pages)
    clicks = sum(int(page["clicks"]) for page in pages)
    total_commission = round(
        sum(commission(page["page_url"]) for page in pages), 2
    )
    weighted_position = (
        sum(
            float(page["average_position"]) * int(page["impressions"])
            for page in pages
        ) / impressions
        if impressions else 0.0
    )
    return {
        "pages": len(pages),
        "impressions": impressions,
        "clicks": clicks,
        "commission": total_commission,
        "avg_position": round(weighted_position, 1),
        "visitors_28d": _plausible_visitors(database, website_id),
    }


def _goals(
    pages: list[dict[str, Any]], queries: list[dict[str, Any]],
    commission: Any,
) -> list[dict[str, Any]]:
    """Turn the combined signals into concrete, goal-setting opportunities."""
    goals: list[dict[str, Any]] = []

    money_gaps = [
        page for page in pages
        if int(page["impressions"]) >= MONEY_GAP_MIN_IMPRESSIONS
        and commission(page["page_url"]) < MONEY_GAP_MAX_COMMISSION
    ]
    if money_gaps:
        gap_impressions = sum(int(page["impressions"]) for page in money_gaps)
        goals.append({
            "type": "monetization_gap",
            "metric": "commission",
            "title": "Tjen på trafik der ikke giver provision",
            "target": (
                f"Skab provision fra {len(money_gaps)} sider med i alt "
                f"{gap_impressions} visninger uden nævneværdig indtjening"
            ),
            "items": [
                {
                    "url": page["page_url"],
                    "impressions": int(page["impressions"]),
                    "position": round(float(page["average_position"]), 1),
                    "commission": round(commission(page["page_url"]), 0),
                }
                for page in sorted(
                    money_gaps, key=lambda row: -int(row["impressions"])
                )[:EXAMPLE_LIMIT]
            ],
        })

    striking = [
        query for query in queries
        if STRIKING_MIN_POSITION
        <= float(query["average_position"]) <= STRIKING_MAX_POSITION
        and int(query["impressions"]) >= STRIKING_MIN_IMPRESSIONS
    ]
    if striking:
        goals.append({
            "type": "striking_distance",
            "metric": "position",
            "title": "Flyt søgeord fra side 2 mod top 10",
            "target": (
                f"Løft {len(striking)} søgeord "
                f"(plads {STRIKING_MIN_POSITION:.0f}–{STRIKING_MAX_POSITION:.0f}) "
                "op på side 1"
            ),
            "items": [
                {
                    "query": query["query"],
                    "url": query["page_url"],
                    "impressions": int(query["impressions"]),
                    "position": round(float(query["average_position"]), 1),
                }
                for query in sorted(
                    striking, key=lambda row: -int(row["impressions"])
                )[:EXAMPLE_LIMIT]
            ],
        })

    earners = [page for page in pages if commission(page["page_url"]) > 0]
    if earners:
        earned = round(
            sum(commission(page["page_url"]) for page in earners), 2
        )
        goals.append({
            "type": "earner_growth",
            "metric": "commission",
            "title": "Voks de sider der allerede tjener",
            "target": (
                f"Øg trafikken til {len(earners)} indtjenende sider "
                f"({earned:.0f} kr i registreret provision)"
            ),
            "items": [
                {
                    "url": page["page_url"],
                    "commission": round(commission(page["page_url"]), 0),
                    "position": round(float(page["average_position"]), 1),
                    "impressions": int(page["impressions"]),
                }
                for page in sorted(
                    earners, key=lambda row: -commission(row["page_url"])
                )[:EXAMPLE_LIMIT]
            ],
        })

    gap = _content_gap_goal(queries)
    if gap:
        goals.append(gap)
    return goals


def _content_gap_goal(
    queries: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """A keyword with demand that a page shows up for but does not focus on —
    ranking poorly because no page is dedicated to it: an opportunity for new
    content targeting the keyword."""
    top_by_page: dict[str, dict[str, Any]] = {}
    best_by_query: dict[str, dict[str, Any]] = {}
    for query in queries:
        page = query["page_url"]
        if top_by_page.get(page) is None or int(query["impressions"]) > int(
            top_by_page[page]["impressions"]
        ):
            top_by_page[page] = query
        word = query["query"]
        if best_by_query.get(word) is None or int(query["impressions"]) > int(
            best_by_query[word]["impressions"]
        ):
            best_by_query[word] = query
    gaps = [
        query for word, query in best_by_query.items()
        if str(word).strip()
        and top_by_page[query["page_url"]]["query"] != word
        and int(query["impressions"]) >= CONTENT_GAP_MIN_IMPRESSIONS
        and float(query["average_position"]) >= CONTENT_GAP_MIN_POSITION
    ]
    if not gaps:
        return None
    return {
        "type": "content_gap",
        "metric": "position",
        "title": "Nye søgeord uden dedikeret indhold",
        "target": (
            f"Skab dedikeret indhold for {len(gaps)} søgeord med efterspørgsel "
            f"(plads {CONTENT_GAP_MIN_POSITION:.0f}+)"
        ),
        "items": [
            {
                "query": query["query"],
                "url": query["page_url"],
                "impressions": int(query["impressions"]),
                "position": round(float(query["average_position"]), 1),
            }
            for query in sorted(
                gaps, key=lambda row: -int(row["impressions"])
            )[:EXAMPLE_LIMIT]
        ],
    }


def _recommended_sequence(
    database: Any, website_id: str, decision_engine: Any | None,
) -> list[dict[str, Any]]:
    """Reuse the income-first DecisionEngine so the roadmap and the daily queue
    always propose the same next experiments."""
    engine = decision_engine or _default_engine(database)
    ranked = engine.rank_candidates(engine.collect_candidates(website_id))
    return [
        {
            "experiment_type": candidate["experiment_type"],
            "goal_metric": candidate.get("goal_metric"),
            "target_url": candidate["target_url"],
            "priority_score": candidate.get("priority_score"),
            "title": candidate.get("task_title"),
            "impressions": candidate.get("current_impressions"),
            "position": round(float(candidate.get("current_position") or 0), 1),
            "commission": round(
                float(candidate.get("affiliate_commission") or 0), 0
            ),
        }
        for candidate in ranked[:RECOMMENDED_SEQUENCE_LIMIT]
    ]


def _default_engine(database: Any) -> Any:
    from core.decision_engine import DecisionEngine
    from core.website_registry import WebsiteRegistry
    return DecisionEngine(database, WebsiteRegistry(database))


def _latest_period_rows(
    database: Any, website_id: str, dimension: str,
) -> list[dict[str, Any]]:
    """Return the stored rows for a website's most recent 28-day period."""
    rows = database.get_search_console_dimensions(
        dimension, website_id=website_id
    )
    if not rows:
        return []
    latest = max(
        (row["period_end"], row["period_start"]) for row in rows
    )
    return [
        row for row in rows
        if (row["period_end"], row["period_start"]) == latest
    ]


def _plausible_visitors(database: Any, website_id: str) -> int:
    """Sum Plausible visitors over the most recent stored days."""
    metrics = database.get_plausible_daily_metrics(website_id=website_id)
    return sum(
        int(row.get("visitors") or 0)
        for row in metrics[:PLAUSIBLE_WINDOW_DAYS]
    )


def _narrative(roadmap: dict[str, Any], ai_service: Any | None) -> str:
    """Phrase the roadmap; deterministic fallback keeps it usable without AI."""
    fallback = _fallback_narrative(roadmap)
    if ai_service is None:
        return fallback
    prompt = (
        "Skriv 2-4 korte danske sætninger, der opsummerer denne SEO-køreplan "
        "som en rådgiver. Brug kun tallene; foreslå ingen nye tal.\n"
        + json.dumps(
            {"summary": roadmap["summary"],
             "goals": [
                 {"title": goal["title"], "target": goal["target"]}
                 for goal in roadmap["goals"]
             ]},
            ensure_ascii=False,
        )
    )
    try:
        text = ai_service.generate_response(prompt).text.strip()
        return text or fallback
    except Exception:
        return fallback


def _fallback_narrative(roadmap: dict[str, Any]) -> str:
    summary = roadmap["summary"]
    if not roadmap["goals"]:
        return (
            "Der er endnu ikke nok målte signaler til at sætte konkrete mål for "
            "dette website. Indsaml mere Search Console- og salgsdata først."
        )
    headline = (
        f"Sitet har {summary['impressions']} visninger og "
        f"{summary['clicks']} klik med en gennemsnitlig placering på "
        f"{summary['avg_position']}, og har indtil videre tjent "
        f"{summary['commission']:.0f} kr."
    )
    goal_text = " ".join(
        f"{goal['target']}." for goal in roadmap["goals"]
    )
    return headline + " Vigtigste mål: " + goal_text


__all__ = ["build_website_roadmap"]
