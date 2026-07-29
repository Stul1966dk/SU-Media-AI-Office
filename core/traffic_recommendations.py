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


def apply_measured_learning(
    recommendations: list[dict[str, Any]],
    learning_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enrich candidates with relevant measured outcomes from earlier work."""
    enriched = []
    improved = {"Tydeligt forbedret", "Forbedret", "Delvist forbedret"}
    unsuccessful = {"Uændret", "Forværret"}
    for recommendation in recommendations:
        item = dict(recommendation)
        change_type = _recommended_change_type(item)
        relevant = [
            entry for entry in learning_entries
            if entry.get("change_type") == change_type
        ]
        same_url = [
            entry for entry in relevant
            if entry.get("target_url") == item.get("target_url")
        ]
        wins = sum(
            entry.get("classification") in improved for entry in relevant
        )
        repeated_failures = sum(
            entry.get("classification") in unsuccessful for entry in same_url
        )
        if relevant:
            item["learning_evidence"] = {
                "change_type": change_type,
                "observations": len(relevant),
                "improved": wins,
                "same_url_failures": repeated_failures,
            }
            item["learning_summary"] = (
                f"{len(relevant)} tidligere måling(er) af denne ændringstype; "
                f"{wins} gav en forbedring."
            )
        if repeated_failures >= 2:
            item["recommended_action"] = (
                "Tidligere målinger på samme URL gav ikke effekt. Vælg en "
                "anden ændringstype end den tidligere afprøvede, og brug "
                "datagrundlaget nedenfor til at afgrænse den."
            )
            item["learning_summary"] = (
                f"{repeated_failures} tidligere målinger af samme type på "
                "denne URL var uændrede eller forværrede. Gentag derfor ikke "
                "samme løsning."
            )
        enriched.append(item)
    return enriched


def _recommended_change_type(recommendation: dict[str, Any]) -> str:
    cause = str(recommendation.get("measured_cause") or "")
    if cause == "CTR-fald":
        return "title_meta"
    if cause == "Placeringsfald":
        return "content_update"
    return "content_update"


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
    action = "Find den kanal i Plausible, der har mistet flest besøgende."
    return {
        "task_type": "plausible_only_decline",
        "website": website,
        "description": action,
        "recommended_action": (
            "Sammenlign henvisninger, direkte trafik og øvrige kanaler for "
            "de samme to 28-dages perioder, og vælg kanalen med størst "
            "dokumenteret tab til den næste indsats."
        ),
        "action_steps": [
            "Åbn Plausibles kanalrapport for de to gemte 28-dages perioder.",
            "Rangér kanalerne efter tabte besøgende.",
            "Notér den største faldende kanal og dens vigtigste landingsside.",
        ],
        "completion_criterion": (
            "Én faldende kanal og én berørt landingsside er dokumenteret."
        ),
        "measurement_method": (
            "Sammenlign kanalens besøgende med den foregående 28-dages periode."
        ),
        "estimated_minutes": 30,
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
    plan = _page_plan(page)
    click_change = _percent_change(
        search.get("previous_clicks"), search.get("current_clicks")
    )
    return {
        "website": website,
        "description": plan["title"],
        "recommended_action": plan["recommended_action"],
        "action_steps": plan["action_steps"],
        "completion_criterion": plan["completion_criterion"],
        "measurement_method": plan["measurement_method"],
        "estimated_minutes": plan["estimated_minutes"],
        "target_url": page.get("page_url", ""),
        "target_query": plan["target_query"],
        "search_queries": [
            {
                "query": str(row.get("query") or ""),
                "click_loss": int(row.get("click_loss") or 0),
            }
            for row in (page.get("queries") or [])[:10]
            if row.get("query")
        ],
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


def _page_plan(page: dict[str, Any]) -> dict[str, Any]:
    """Translate measured signals into a bounded proposed work plan."""
    cause = str(page.get("cause", ""))
    url = str(page.get("page_url", "den vigtigste tabsside"))
    queries = page.get("queries") or []
    query = str(queries[0].get("query", "")) if queries else ""
    query_label = f"“{query}”" if query else "det største faldende søgeord"
    if cause == "CTR-fald":
        return {
            "title": f"Forbered en title/meta-test på {url}.",
            "recommended_action": (
                f"Udarbejd tre title- og metabeskrivelser med fokus på "
                f"{query_label}, og send den bedste variant til manuel "
                "godkendelse som ét SEO-eksperiment."
            ),
            "action_steps": [
                f"Kontrollér den nuværende title og meta for {query_label}.",
                "Skriv tre varianter uden at ændre sidens søgeintention.",
                "Vælg én variant og gem den som kladde til manuel godkendelse.",
            ],
            "completion_criterion": (
                "Én godkendelsesklar title/meta-kladde er gemt; intet er "
                "publiceret automatisk."
            ),
            "measurement_method": (
                f"Mål CTR og klik for {query_label} efter 28 hele dage."
            ),
            "estimated_minutes": 45,
            "target_query": query,
        }
    if cause == "Placeringsfald":
        return {
            "title": f"Styrk siden til søgeordet {query_label}.",
            "recommended_action": (
                f"Opdatér {url} med fokus på {query_label}: kontrollér at "
                "søgeintentionen besvares tydeligt, styrk den mest relevante "
                "sektion, og tilføj interne links fra relevante sider."
            ),
            "action_steps": [
                f"Sammenhold sidens indhold med søgeintentionen bag {query_label}.",
                "Opdatér eller tilføj den sektion, der mangler et klart svar.",
                "Tilføj 2–3 relevante interne links til siden.",
                "Registrér ændringen som ét målbart 28-dages SEO-eksperiment.",
            ],
            "completion_criterion": (
                "Indholdet er opdateret, 2–3 interne links er dokumenteret, "
                "og ændringen er klar til manuel godkendelse."
            ),
            "measurement_method": (
                f"Mål placering og klik for {query_label} efter 28 hele dage."
            ),
            "estimated_minutes": 90,
            "target_query": query,
        }
    if cause == "Lavere søgeefterspørgsel":
        return {
            "title": f"Find et beslægtet emne med stabil efterspørgsel til {url}.",
            "recommended_action": (
                f"Bevar siden uændret, og brug de faldende søgeord til at "
                "finde ét beslægtet emne med stabile visninger, før der "
                "foreslås nyt indhold."
            ),
            "action_steps": [
                "Rangér sidens beslægtede søgeord efter stabile visninger.",
                "Vælg ét emne, som matcher sidens formål.",
                "Gem emnet som indholdskladde; publicér ikke automatisk.",
            ],
            "completion_criterion": "Ét dokumenteret emne er valgt som kladde.",
            "measurement_method": (
                "Mål visninger og klik for det valgte emne efter 28 hele dage."
            ),
            "estimated_minutes": 45,
            "target_query": query,
        }
    return {
        "title": f"Afgræns klikfaldet på {url}.",
        "recommended_action": (
            f"Gennemgå de tre største faldende søgeord for {url}, og vælg "
            "kun en ændring, hvis ét fælles målt problem kan dokumenteres."
        ),
        "action_steps": [
            "Sammenlign placering, CTR og visninger for de tre søgeord.",
            "Dokumentér det signal, der forklarer flest tabte klik.",
            "Gem højst én foreslået ændring som kladde.",
        ],
        "completion_criterion": (
            "Én dokumenteret årsag eller en begrundet beslutning om ingen "
            "ændring er gemt."
        ),
        "measurement_method": "Genmål de samme søgeord efter 28 hele dage.",
        "estimated_minutes": 45,
        "target_query": query,
    }


def _percent_change(previous: Any, current: Any) -> float:
    before = float(previous or 0)
    if not before:
        return 0
    return round((float(current or 0) - before) / before * 100, 1)


def _point_change(previous: Any, current: Any) -> float:
    return round((float(current or 0) - float(previous or 0)) * 100, 2)


def _difference(previous: Any, current: Any) -> float:
    return round(float(current or 0) - float(previous or 0), 2)
