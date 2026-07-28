"""Evidence-based task candidates from persisted traffic diagnoses."""

from __future__ import annotations

from typing import Any


def build_traffic_recommendations(
    search_diagnoses: list[dict[str, Any]],
    plausible_diagnoses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Combine comparable diagnoses into specific, explainable candidates."""
    search_by_site = {
        str(item.get("website_id", "")): item for item in search_diagnoses
    }
    plausible_by_site = {
        str(item.get("website_id", "")): item for item in plausible_diagnoses
    }
    recommendations = []
    for website in sorted(set(search_by_site) | set(plausible_by_site)):
        search = search_by_site.get(website)
        plausible = plausible_by_site.get(website)
        if not _comparable(search, plausible):
            continue
        search_decline = search.get("status") == "ready"
        plausible_decline = plausible.get("status") == "significant_decline"
        if search_decline and plausible_decline:
            recommendations.append(_combined(website, search, plausible))
        elif search_decline:
            recommendations.append(_search_only(website, search, plausible))
        elif plausible_decline:
            recommendations.append(_plausible_only(website, search, plausible))
    return recommendations


def _combined(
    website: str, search: dict[str, Any], plausible: dict[str, Any]
) -> dict[str, Any]:
    item = _search_fields(website, search)
    item.update({
        "task_type": "combined_traffic_decline",
        "plausible_change": float(
            plausible.get("visitor_change_percent") or 0
        ),
        "explanation": (
            "Search Console dokumenterer et organisk klikfald, og Plausible "
            "bekræfter samtidig et væsentligt fald i besøgende."
        ),
        "confidence": "høj",
    })
    return item


def _search_only(
    website: str, search: dict[str, Any], plausible: dict[str, Any]
) -> dict[str, Any]:
    item = _search_fields(website, search)
    item.update({
        "task_type": "search_only_decline",
        "plausible_change": float(
            plausible.get("visitor_change_percent") or 0
        ),
        "explanation": (
            "Search Console dokumenterer et klikfald, men Plausible viser "
            "ikke et væsentligt samlet trafikfald. Indsatsen afgrænses "
            "derfor til den organiske kanal."
        ),
        "confidence": "middel",
    })
    return item


def _plausible_only(
    website: str, search: dict[str, Any], plausible: dict[str, Any]
) -> dict[str, Any]:
    action = "Undersøg faldet i ikke-organisk trafik."
    return {
        "task_type": "plausible_only_decline",
        "website": website,
        "description": action,
        "recommended_action": (
            "Undersøg henvisninger, direkte trafik og øvrige kanaler i "
            "Plausible; Search Console forklarer ikke faldet."
        ),
        "target_url": "",
        "measured_cause": "Faldet er ikke organisk",
        "click_change": _percent_change(
            search.get("previous_clicks"), search.get("current_clicks")
        ),
        "plausible_change": float(
            plausible.get("visitor_change_percent") or 0
        ),
        "search_console_change": "ingen væsentlig organisk tilbagegang",
        "explanation": (
            "Plausible dokumenterer et væsentligt trafikfald, mens Search "
            "Console ikke viser et tilsvarende organisk klikfald."
        ),
        "confidence": "middel",
    }


def _search_fields(
    website: str, search: dict[str, Any]
) -> dict[str, Any]:
    page = (search.get("loss_pages") or [{}])[0]
    action = _page_action(page)
    click_change = _percent_change(
        search.get("previous_clicks"), search.get("current_clicks")
    )
    return {
        "website": website,
        "description": action,
        "recommended_action": action,
        "target_url": page.get("page_url", ""),
        "measured_cause": page.get("cause", ""),
        "click_change": click_change,
        "ctr_change": _point_change(
            page.get("previous_ctr"), page.get("current_ctr")
        ),
        "position_change": _difference(
            page.get("previous_position"), page.get("current_position")
        ),
        "seo_health_trend": "declining",
        "search_console_change": (
            f"klik {click_change:+.1f} %".replace(".", ",")
        ),
    }


def _comparable(
    search: dict[str, Any] | None,
    plausible: dict[str, Any] | None,
) -> bool:
    unusable = {"missing_periods", "insufficient_data"}
    return bool(
        search and plausible
        and search.get("status") not in unusable
        and plausible.get("status") not in unusable
    )


def _page_action(page: dict[str, Any]) -> str:
    cause = str(page.get("cause", ""))
    url = str(page.get("page_url", "den vigtigste tabsside"))
    if cause == "CTR-fald":
        return f"Gennemgå title og meta på {url}."
    if cause == "Placeringsfald":
        return f"Undersøg placeringsfaldet på {url}."
    if cause == "Lavere søgeefterspørgsel":
        return f"Vurdér søgebehov og relaterede emner for {url}."
    return f"Afgræns det organiske klikfald på {url}."


def _percent_change(previous: Any, current: Any) -> float:
    before = float(previous or 0)
    if not before:
        return 0
    return round((float(current or 0) - before) / before * 100, 1)


def _point_change(previous: Any, current: Any) -> float:
    return round((float(current or 0) - float(previous or 0)) * 100, 2)


def _difference(previous: Any, current: Any) -> float:
    return round(float(current or 0) - float(previous or 0), 2)
