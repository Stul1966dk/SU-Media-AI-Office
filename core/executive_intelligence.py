"""Deterministic, evidence-based executive action enrichment."""

import ast
from typing import Any


GENERIC_ACTIONS = {
    "undersøg området", "se nærmere på problemet",
    "overvåg udviklingen", "optimér websitet",
}


class ExecutiveIntelligence:
    """Turn persisted evidence into concrete, measurable executive actions."""

    def __init__(self, database: Any, company_playbook: str = "") -> None:
        self.database = database
        self.company_playbook = company_playbook

    def build_company_context(self) -> dict[str, Any]:
        return self.database.get_executive_context()

    def build_website_context(self, website_id: str) -> dict[str, Any]:
        source = self.database.get_website_intelligence_source(website_id) or {}
        metrics = self.database.get_search_console_daily_metrics(
            website_id=website_id
        )
        pages = self.database.get_search_console_dimensions(
            "page", website_id=website_id
        )
        queries = self.database.get_search_console_dimensions(
            "query", website_id=website_id
        )
        page_queries = self.database.get_search_console_dimensions(
            "page_query", website_id=website_id
        )
        return {
            "website": self.database.get_website(website_id),
            "profile": self.database.get_website_profile_detail(website_id),
            "search_console": metrics,
            "seo_health": source.get("seo_health"),
            "partner_ads": source.get("partner_ads", {}),
            "discovery": self.database.get_website_discovery_profile(website_id),
            "projects": source.get("active_projects", []),
            "tasks": source.get("active_tasks", []),
            "analysis": self.database.get_latest_analysis(
                website_id=website_id
            ),
            "pages": pages,
            "queries": queries,
            "page_queries": page_queries,
            "url_data": bool(pages),
            "query_data": bool(queries),
            "company_playbook": self.company_playbook,
        }

    def identify_issues(self, context: dict[str, Any]) -> list[str]:
        issues = []
        if not context["url_data"]:
            issues.append("URL-data er ikke importeret.")
        if not context["query_data"]:
            issues.append("Søgeordsdata er ikke importeret.")
        if not context["seo_health"]:
            issues.append("SEO Health mangler.")
        return issues

    def identify_opportunities(self, context: dict[str, Any]) -> list[str]:
        opportunities = []
        if context["search_console"] and not context["url_data"]:
            opportunities.append(
                "Udvid Search Console-importen med URL- og søgeordsniveau."
            )
        if context.get("partner_ads", {}).get("sales"):
            opportunities.append("Knyt trafikændringer til dokumenteret provision.")
        return opportunities

    def rank_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            actions,
            key=lambda item: (
                -int(item.get("priority_score", 0)),
                int(item.get("estimated_minutes", 120)),
            ),
        )

    def create_actionable_focus_area(
        self, focus: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        website = focus["website"]
        evidence = list(focus.get("evidence") or [])
        metrics = context["search_console"]
        days = len(metrics)
        if days:
            evidence.append(f"Search Console indeholder {days} gemte dage.")
        website_record = context.get("website") or {}
        if website_record.get("monetized"):
            evidence.append("Websitet er monetized.")
        sales_count = len(context.get("partner_ads", {}).get("sales", []))
        if sales_count:
            evidence.append(f"Partner Ads har {sales_count} dokumenterede salg.")

        action = str(focus.get("recommended_action", "")).strip()
        generic = not action or any(
            phrase in action.lower() for phrase in GENERIC_ACTIONS
        )
        target = self._select_target(context)
        if target:
            action = (
                f"Opdater title og metabeskrivelse på {target['page_url']}"
                + (f" for søgeordet “{target['query']}”"
                   if target.get("query") else "")
                + "."
            )
        elif generic or (not context["url_data"] or not context["query_data"]):
            action = (
                "Importér Search Console-data på URL- og søgeordsniveau for "
                f"{website} for at identificere de fem største klikfald."
            )
        target_url = target.get("page_url", "") if target else ""
        target_query = target.get("query", "") if target else ""
        focus.update({
            "problem_or_opportunity": focus.get(
                "problem_or_opportunity",
                "Manglende side- og søgeordsdata begrænser prioriteringen.",
            ),
            "why_it_matters": focus.get(
                "why_it_matters",
                "Uden detaljerede dimensioner kan trafikfald ikke afgrænses.",
            ),
            "evidence": evidence,
            "likely_cause": focus.get(
                "likely_cause", "Årsagen kan ikke fastslås på website-niveau."
            ),
            "recommended_action": action,
            "task_title": (
                f"Opdater søgeresultat for {target_url}"
                if target_url else f"Importér detaljerede søgedata for {website}"
            ),
            "task_description": action,
            "target_url": target_url,
            "target_query": target_query,
            "exact_steps": ([
                f"Åbn {target_url}.",
                "Sammenlign title og metabeskrivelse med søgeintentionen.",
                "Skriv tre nye title-forslag.",
                "Skriv én ny metabeskrivelse.",
                "Gem forslagene som kladde til godkendelse.",
            ] if target_url else [
                f"Åbn Search Console for {website}.",
                "Hent side- og søgeordsdata for begge 28-dages perioder.",
            ]),
            "completion_criteria": (
                "Opgaven er færdig, når der ligger tre title-forslag og én "
                "metabeskrivelse klar til godkendelse."
                if target_url else
                "Opgaven er færdig, når begge perioder findes i databasen."
            ),
            "assigned_agent": focus.get("assigned_agent") or "SEO Manager",
            "estimated_minutes": min(
                120, max(15, int(focus.get("estimated_minutes", 45) or 45))
            ),
            "measurement_method": focus.get("measurement_method") or (
                "Registrér antal importerede URL'er og søgeord og opret en "
                "baseline for klik, CTR og placering."
            ),
            "limitations": list(focus.get("limitations") or []) + (
                [] if target else [
                    "URL-data er ikke tilgængelig.",
                    "Søgeordsdata er ikke tilgængelig.",
                ]
            ),
        })
        focus["priority_label"] = self._priority_label(
            int(focus["priority_score"])
        )
        focus["priority_reason"] = self.explain_priority(focus, context)
        effect, reason = self.estimate_expected_effect(focus, context)
        focus["expected_effect"] = effect
        focus["expected_effect_reason"] = reason
        focus["data_sources"] = self._data_sources(context)
        return focus

    @staticmethod
    def _select_target(context: dict[str, Any]) -> dict[str, str] | None:
        """Choose one important concrete page/query from the latest period."""
        rows = context.get("page_queries", [])
        if rows:
            latest_end = max(item["period_end"] for item in rows)
            candidate = max(
                (item for item in rows if item["period_end"] == latest_end),
                key=lambda item: (item["impressions"], item["clicks"]),
            )
            return {
                "page_url": candidate["page_url"],
                "query": candidate["query"],
            }
        rows = context.get("pages", [])
        if rows:
            latest_end = max(item["period_end"] for item in rows)
            candidate = max(
                (item for item in rows if item["period_end"] == latest_end),
                key=lambda item: (item["impressions"], item["clicks"]),
            )
            return {"page_url": candidate["page_url"], "query": ""}
        return None

    def explain_priority(
        self, focus: dict[str, Any], context: dict[str, Any]
    ) -> str:
        reasons = []
        if (context.get("website") or {}).get("monetized"):
            reasons.append("websitet er monetized")
        if context["search_console"]:
            reasons.append(
                f"der findes {len(context['search_console'])} dages trafikdata"
            )
        reasons.append(
            f"første handling tager cirka {focus['estimated_minutes']} minutter"
        )
        return (
            f"{self._priority_label(int(focus['priority_score']))} prioritet, "
            "fordi " + ", ".join(reasons) + "."
        )

    def estimate_expected_effect(
        self, focus: dict[str, Any], context: dict[str, Any]
    ) -> tuple[str, str]:
        if not context["url_data"]:
            return (
                "Mellem",
                "Bedre datagrundlag kan afgrænse de vigtigste tabere, men "
                "trafik- og indtjeningseffekten er endnu ukendt.",
            )
        return ("Høj", "Handlingen kan målrettes dokumenterede trafikfald.")

    def enrich_briefing(
        self, briefing: dict[str, Any], website_id: str | None = None
    ) -> dict[str, Any]:
        enriched = []
        for focus in briefing.get("focus_areas", []):
            site = focus.get("website") or website_id
            if not site:
                continue
            focus["website"] = site
            enriched.append(self.create_actionable_focus_area(
                focus, self.build_website_context(site)
            ))
        briefing["focus_areas"] = self.rank_actions(enriched)
        briefing["risks"] = self._risk_cards(
            briefing.get("risks", []), website_id
        )
        briefing["opportunities"] = self._opportunity_cards(
            briefing.get("opportunities", []), enriched
        )
        return briefing

    @staticmethod
    def _priority_label(score: int) -> str:
        return "Kritisk" if score >= 85 else "Høj" if score >= 70 else (
            "Mellem" if score >= 45 else "Lav"
        )

    @staticmethod
    def _data_sources(context: dict[str, Any]) -> list[dict[str, str]]:
        sales = len(context.get("partner_ads", {}).get("sales", []))
        return [
            {"source": "Search Console", "status": (
                f"Tilgængelig, {len(context['search_console'])} dage"
                if context["search_console"] else "Ikke tilgængelig"
            )},
            {"source": "Partner Ads", "status": (
                f"Tilgængelig, {sales} dokumenterede salg"
                if sales else "Ikke tilgængelig"
            )},
            {"source": "SEO Health", "status": (
                "Tilgængelig" if context["seo_health"] else "Ikke tilgængelig"
            )},
            {"source": "Website Discovery", "status": (
                "Tilgængelig" if context["discovery"] else "Ikke tilgængelig"
            )},
            {"source": "URL-data", "status": (
                "Tilgængelig" if context["url_data"] else "Ikke tilgængelig"
            )},
            {"source": "Søgeordsdata", "status": (
                "Tilgængelig" if context["query_data"] else "Ikke tilgængelig"
            )},
        ]

    @staticmethod
    def _risk_cards(values: list[Any], website_id: str | None) -> list[dict]:
        cards = []
        for item in values:
            if isinstance(item, str):
                try:
                    parsed = ast.literal_eval(item)
                    if isinstance(parsed, dict):
                        item = parsed
                except (ValueError, SyntaxError):
                    pass
            if isinstance(item, dict):
                cards.append({
                    "title": item.get("title") or item.get("risk") or (
                        "Begrænset datagrundlag"
                    ),
                    "description": item.get("description") or item.get(
                        "reason", "Datagrundlaget er ufuldstændigt."
                    ),
                    "consequence": item.get("consequence") or item.get(
                        "impact", "Effekten kan ikke beregnes sikkert."
                    ),
                    "mitigation": item.get("mitigation") or item.get(
                        "proposed_follow_up",
                        "Brug resultaterne med forsigtighed og indlæs flere data.",
                    ),
                })
            else:
                cards.append({
                    "title": "Databegrænsning",
                    "description": str(item),
                    "consequence": "Prioriteringen er mindre sikker.",
                    "mitigation": "Indlæs de manglende datakilder.",
                })
        return cards

    @staticmethod
    def _opportunity_cards(
        values: list[Any], focuses: list[dict[str, Any]]
    ) -> list[dict]:
        if focuses:
            focus = focuses[0]
            return [{
                "title": focus["title"], "website": focus["website"],
                "reason": focus["why_it_matters"],
                "evidence": focus["evidence"],
                "recommended_action": focus["recommended_action"],
                "assigned_agent": focus["assigned_agent"],
                "estimated_minutes": focus["estimated_minutes"],
                "expected_effect": focus["expected_effect"],
                "priority_score": focus["priority_score"],
                "confidence": focus["confidence"],
                "measurement_method": focus["measurement_method"],
            }]
        return []
