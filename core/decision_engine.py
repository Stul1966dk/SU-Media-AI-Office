"""Single-decision engine for measurable SEO work."""

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from core.revenue_attribution import (
    domain as _domain,
    page_key_for_url,
    revenue_by_page,
)
from core.seo_experiment_engine import SEOExperimentEngine


GENERIC_TASKS = (
    "undersøg området", "optimér siden", "analyser mere",
    "overvåg udviklingen", "gennemgå websitet",
)

# A monetised page that draws real traffic but earns little or nothing is a
# monetisation opportunity: worth surfacing even without a click problem. The
# boost is bounded so it lifts such pages into contention without ever
# outweighing a page with proven, measured earnings.
MONETIZATION_GAP_MIN_IMPRESSIONS = 100
MONETIZATION_GAP_MAX_COMMISSION = 50.0
MONETIZATION_GAP_CAP = 6.0

# A page ranking beyond this average position sits on Google's page 2+, where a
# title/meta rewrite cannot win clicks — the lever is ranking, so such pages get
# a content/ranking experiment (measured on position) instead of a CTR test.
CLICKABLE_POSITION_MAX = 10.0

# Learning from measured outcomes. A change type that has failed twice on a URL
# is avoided in favour of an alternative; documented site-level wins/losses give
# a bounded ranking nudge so proven choices are favoured and poor ones are not
# repeated. Bounds keep learning from ever overturning the money invariants.
LEARNING_FAILURE_THRESHOLD = 2
LEARNING_SITE_BIAS_CAP = 5.0
LEARNING_REPEAT_PENALTY = 8.0
LEARNING_ALTERNATIVES = {
    "title_meta": ("content_update",),
    "content_update": ("title_meta",),
}
POSITIVE_CLASSIFICATIONS = {"Tydeligt forbedret", "Forbedret", "Delvist forbedret"}
NEGATIVE_CLASSIFICATIONS = {"Uændret", "Forværret"}

# A content gap: a query with real demand that the site half-serves because no
# page focuses on it. It must rank *beyond* striking distance (page 3+), so the
# fix is dedicated content — not the striking-distance "just push it up" case.
CONTENT_GAP_MIN_IMPRESSIONS = 100
CONTENT_GAP_MIN_POSITION = 20.0


class DecisionEngine:
    """Rank evidence-backed candidates and persist at most one decision."""

    def __init__(
        self, database: Any, website_registry: Any,
        *, project_manager: Any | None = None,
        experiment_engine: SEOExperimentEngine | None = None,
        knowledge_engine: Any | None = None, ai_analyst: Any | None = None,
        ai_executive: Any | None = None,
    ) -> None:
        self.database = database
        self.website_registry = website_registry
        self.project_manager = project_manager
        self.experiments = experiment_engine or SEOExperimentEngine(database)
        self.knowledge_engine = knowledge_engine
        self.ai_analyst = ai_analyst
        self.ai_executive = ai_executive

    def collect_candidates(
        self, website_id: str | None = None, *, include_locked: bool = False,
    ) -> list[dict[str, Any]]:
        """Build concrete candidates from stored page and query evidence."""
        websites = [
            item for item in self.website_registry.get_all()
            if item["active"] and item["status"] not in
            {"phasing_out", "archived", "cancelled"}
            and (website_id is None or item["website"] == website_id)
        ]
        page_revenue = self.page_revenue_map()
        site_revenue: dict[str, float] = defaultdict(float)
        for key, amount in page_revenue.items():
            site_revenue[key.split("/", 1)[0]] += amount
        url_type_failures, site_type_net = self._learning_signals()
        candidates = []
        for website in websites:
            site = website["website"]
            pages = self._comparisons(site, "page", "page_url")
            page_queries = self._comparisons(
                site, "page_query", ("page_url", "query")
            )
            queries_by_page: dict[str, list[dict[str, Any]]] = {}
            for item in page_queries:
                queries_by_page.setdefault(item["page_url"], []).append(item)
            for page in pages:
                target_url = page["page_url"]
                if (
                    not include_locked
                    and self.experiments.is_url_locked(target_url)
                ):
                    continue
                query_rows = queries_by_page.get(target_url, [])
                target_query = (
                    max(query_rows, key=lambda item: item["current_impressions"])
                    ["query"] if query_rows else ""
                )
                click_drop = page["previous_clicks"] - page["current_clicks"]
                low_ctr = (
                    page["current_impressions"] >= 50
                    and page["current_ctr"] < .03
                )
                commission = page_revenue.get(
                    page_key_for_url(target_url), 0.0
                )
                site_has_revenue = (
                    site_revenue.get(_domain(target_url), 0.0) > 0
                )
                # A pure monetisation gap: real traffic on a monetised page,
                # on a site that has proven it can earn, with little/no
                # commission — surfaced even without a separate SEO problem.
                monetization_gap = (
                    bool(website.get("monetized"))
                    and site_has_revenue
                    and commission < MONETIZATION_GAP_MAX_COMMISSION
                    and page["current_impressions"]
                    >= MONETIZATION_GAP_MIN_IMPRESSIONS
                )
                if click_drop <= 0 and not low_ctr and not monetization_gap:
                    continue
                candidate = {
                    "website": site, "target_url": target_url,
                    "target_query": target_query,
                    "current_clicks": page["current_clicks"],
                    "previous_clicks": page["previous_clicks"],
                    "current_impressions": page["current_impressions"],
                    "previous_impressions": page["previous_impressions"],
                    "current_ctr": page["current_ctr"],
                    "previous_ctr": page["previous_ctr"],
                    "current_position": page["current_position"],
                    "previous_position": page["previous_position"],
                    "monetized": bool(website.get("monetized")),
                    "manual_priority": website.get("priority", "medium"),
                    "experiment_type": "title_meta",
                    "task_title": (
                        f"Opdater title og metabeskrivelse på {target_url}"
                    ),
                    "task_description": (
                        f"Opdater title og metabeskrivelse på {target_url}"
                        + (f" med fokus på “{target_query}”." if target_query
                           else ".")
                    ),
                    "exact_steps": [
                        "Gennemgå nuværende title og metabeskrivelse.",
                        "Sammenlign dem med sidens vigtigste søgeord.",
                        "Skriv tre title-forslag.",
                        "Skriv én ny metabeskrivelse.",
                        "Gem ændringsforslaget til godkendelse.",
                    ],
                    "completion_criteria": (
                        "Tre title-forslag og én metabeskrivelse ligger klar "
                        "til godkendelse."
                    ),
                    "assigned_agent": "SEO Manager",
                    "estimated_minutes": 60,
                    "expected_effect": "Højere organisk CTR og flere klik.",
                    "expected_effect_reason": (
                        f"Siden havde {page['current_impressions']} visninger "
                        f"og {page['current_ctr']*100:.2f}% CTR."
                    ),
                    "confidence": self._confidence(page),
                    "measurement_method": (
                        "Sammenlign klik, visninger, CTR og placering med den "
                        "gemte 28-dages baseline."
                    ),
                    "experiment_goal": "Øg CTR mindst 15 procent uden placeringsfald.",
                    "goal_metric": "ctr", "goal_direction": "increase",
                    "target_change_pct": 15, "waiting_period_days": 28,
                    "risk": "Mellem", "data_quality": self._data_quality(page),
                }
                candidate.update(self._website_signals(site))
                # Per-page commission (Fase 1 uid attribution) replaces the
                # coarse website-level figure so proven earners rank higher.
                candidate["affiliate_commission"] = commission
                candidate["site_has_revenue"] = site_has_revenue
                # Prescribe the change that fits the measured problem, income
                # first. A monetised page with real traffic that under-earns
                # becomes a commission experiment even when its CTR is low; a
                # page ranking on page 2+ gets a ranking change; only a clickable
                # page keeps the CTR-focused title/meta default.
                position = float(page.get("current_position") or 0)
                if monetization_gap:
                    intent = "monetization"
                elif position > CLICKABLE_POSITION_MAX:
                    intent = "content_update"
                else:
                    intent = "title_meta"
                # Avoid repeating a change type that already failed on this URL.
                intent = self._steer_by_learning(
                    target_url, intent, url_type_failures
                )
                if intent == "monetization":
                    self._to_monetization_candidate(candidate, page)
                elif intent == "content_update":
                    self._to_content_candidate(candidate, page)
                # title_meta keeps the base candidate as built.
                candidate["learning_adjustment"] = self._learning_adjustment(
                    site, target_url, intent, url_type_failures, site_type_net
                )
                if not include_locked and self.has_conflict(candidate):
                    continue
                candidates.append(candidate)
            candidates.extend(self._content_gap_candidates(
                site, website, page_queries, page_revenue, site_revenue,
                url_type_failures, site_type_net,
                include_locked=include_locked,
            ))
        return candidates

    def _content_gap_candidates(
        self, site: str, website: dict[str, Any],
        page_queries: list[dict[str, Any]], page_revenue: dict[str, float],
        site_revenue: dict[str, float],
        url_type_failures: dict[tuple[str, str], int],
        site_type_net: dict[tuple[str, str], int], *,
        include_locked: bool = False,
    ) -> list[dict[str, Any]]:
        """Find keywords with demand that no page focuses on, and propose
        dedicated content for them (measured on the query's page ranking)."""
        if not page_queries:
            return []
        top_query_by_page: dict[str, dict[str, Any]] = {}
        best_page_by_query: dict[str, dict[str, Any]] = {}
        for row in page_queries:
            page_best = top_query_by_page.get(row["page_url"])
            if page_best is None or int(row["current_impressions"]) > int(
                page_best["current_impressions"]
            ):
                top_query_by_page[row["page_url"]] = row
            query_best = best_page_by_query.get(row["query"])
            if query_best is None or int(row["current_impressions"]) > int(
                query_best["current_impressions"]
            ):
                best_page_by_query[row["query"]] = row
        candidates = []
        for query, row in best_page_by_query.items():
            if not str(query).strip():
                continue
            if top_query_by_page[row["page_url"]]["query"] == query:
                continue  # the page already focuses on this query
            if int(row["current_impressions"]) < CONTENT_GAP_MIN_IMPRESSIONS:
                continue
            if float(row["current_position"]) < CONTENT_GAP_MIN_POSITION:
                continue
            candidate = self._content_gap_candidate(
                site, website, row, page_revenue, site_revenue
            )
            candidate["learning_adjustment"] = self._learning_adjustment(
                site, row["page_url"], "content_gap",
                url_type_failures, site_type_net,
            )
            if not include_locked and self.has_conflict(candidate):
                continue
            candidates.append(candidate)
        return candidates

    def _content_gap_candidate(
        self, site: str, website: dict[str, Any], row: dict[str, Any],
        page_revenue: dict[str, float], site_revenue: dict[str, float],
    ) -> dict[str, Any]:
        page_url = row["page_url"]
        query = row["query"]
        impressions = int(row["current_impressions"])
        position = float(row["current_position"])
        candidate = {
            "website": site, "target_url": page_url, "target_query": query,
            "current_clicks": row["current_clicks"],
            "previous_clicks": row["previous_clicks"],
            "current_impressions": impressions,
            "previous_impressions": row["previous_impressions"],
            "current_ctr": row["current_ctr"],
            "previous_ctr": row["previous_ctr"],
            "current_position": position,
            "previous_position": row["previous_position"],
            "monetized": bool(website.get("monetized")),
            "manual_priority": website.get("priority", "medium"),
            "experiment_type": "content_gap",
            "forced_content_mode": "content_gap",
            "search_queries": [{"query": query, "click_loss": 0}],
            "task_title": f"Skab dedikeret indhold for søgeordet “{query}”",
            "task_description": (
                f"Søgeordet “{query}” har {impressions} visninger, men "
                f"{page_url} rangerer kun på plads {position:.0f}, fordi ingen "
                "side er dedikeret til det. Skab en ny artikel eller sektion, "
                "der direkte besvarer søgeintentionen bag søgeordet."
            ),
            "exact_steps": [
                f"Fastlæg søgeintentionen bag “{query}”.",
                "Skriv en ny, dedikeret artikel eller sektion, der besvarer den.",
                "Tilføj interne links fra relevante sider.",
                "Gem forslaget til godkendelse.",
            ],
            "completion_criteria": (
                "Et konkret, kopiér-klart indholdsforslag ligger klar til "
                "godkendelse."
            ),
            "assigned_agent": "SEO Manager", "estimated_minutes": 90,
            "expected_effect": (
                "Bedre placering for et ubesvaret søgeord med efterspørgsel."
            ),
            "expected_effect_reason": (
                f"{impressions} visninger på plads {position:.0f} uden "
                "dedikeret indhold."
            ),
            "confidence": self._confidence(row),
            "measurement_method": (
                "Sammenlign søgeordets placering og klik på siden før og efter "
                "over 28 dage."
            ),
            "experiment_goal": f"Forbedr placeringen for “{query}”.",
            "goal_metric": "position", "goal_direction": "increase",
            "target_change_pct": 15, "waiting_period_days": 28,
            "risk": "Mellem", "data_quality": self._data_quality(row),
        }
        candidate.update(self._website_signals(site))
        candidate["affiliate_commission"] = page_revenue.get(
            page_key_for_url(page_url), 0.0
        )
        candidate["site_has_revenue"] = (
            site_revenue.get(_domain(page_url), 0.0) > 0
        )
        return candidate

    @staticmethod
    def _to_monetization_candidate(
        candidate: dict[str, Any], page: dict[str, Any]
    ) -> None:
        """Convert a base candidate into a monetization change suggestion."""
        impressions = int(page["current_impressions"])
        target_url = candidate["target_url"]
        candidate.update({
            "experiment_type": "monetization",
            # Commission is attributed per page, so measure at page level.
            "target_query": "",
            "task_title": f"Tjen på trafikken på {target_url}",
            "task_description": (
                f"Siden får {impressions} visninger, men lav eller ingen "
                "provision. Foreslå en konkret monetisering (fx en "
                "sammenligningstabel eller en købsknap) forankret i de "
                "produkter, siden allerede omtaler."
            ),
            "exact_steps": [
                "Gennemgå sidens indhold og de produkter, den omtaler.",
                "Vælg den bedste monetiseringsform (tabel, links eller knap).",
                "Udarbejd den færdige, kopiér-klare ændring.",
                "Gem ændringsforslaget til godkendelse.",
            ],
            "completion_criteria": (
                "Et konkret, kopiér-klart monetiseringsforslag ligger klar "
                "til godkendelse."
            ),
            "estimated_minutes": 45,
            "expected_effect": "Provision fra den trafik, siden allerede har.",
            "expected_effect_reason": (
                f"Siden har {impressions} visninger uden tilsvarende provision."
            ),
            "measurement_method": (
                "Sammenlign den målte provision fra siden før og efter "
                "ændringen over 28 dage."
            ),
            "experiment_goal": (
                "Skab målbar provision fra en side, der før tjente lidt."
            ),
            "goal_metric": "commission",
            "goal_direction": "increase",
            "target_change_pct": 25,
            "risk": "Lav",
        })

    @staticmethod
    def _to_content_candidate(
        candidate: dict[str, Any], page: dict[str, Any]
    ) -> None:
        """Convert a base candidate into a content/ranking change for a page that
        sits on page 2+. A title rewrite cannot win clicks there, so the change
        targets search intent and content strength and is measured on position."""
        impressions = int(page["current_impressions"])
        position = float(page.get("current_position") or 0)
        target_url = candidate["target_url"]
        query = str(candidate.get("target_query") or "").strip()
        focus = f"“{query}”" if query else "sidens vigtigste søgeord"
        candidate.update({
            "experiment_type": "content_update",
            # Measure the whole page's ranking, not a single low-volume query.
            "target_query": "",
            "task_title": f"Styrk indholdet på {target_url} for bedre placering",
            "task_description": (
                f"Siden ligger på plads {position:.0f} med {impressions} "
                f"visninger og henter derfor næsten ingen klik. Opdatér "
                f"indholdet, så det bedre besvarer søgeintentionen bag {focus}, "
                "og styrk de svageste afsnit."
            ),
            "exact_steps": [
                f"Sammenhold sidens indhold med søgeintentionen bag {focus}.",
                "Opdatér eller tilføj det afsnit, der mangler et klart svar.",
                "Tilføj 2-3 relevante interne links til siden.",
                "Gem ændringsforslaget til godkendelse.",
            ],
            "completion_criteria": (
                "Et konkret, kopiér-klart indholdsforslag ligger klar til "
                "godkendelse."
            ),
            "estimated_minutes": 90,
            "expected_effect": "Bedre placering og dermed flere klik.",
            "expected_effect_reason": (
                f"Siden ligger på plads {position:.0f} med {impressions} "
                "visninger — ranking, ikke CTR, er flaskehalsen."
            ),
            "measurement_method": (
                "Sammenlign sidens gennemsnitlige placering og klik før og "
                "efter ændringen over 28 dage."
            ),
            "experiment_goal": (
                "Forbedr sidens placering, så den henter flere klik."
            ),
            "goal_metric": "position",
            "goal_direction": "increase",
            "target_change_pct": 15,
            "risk": "Mellem",
        })

    def page_revenue_map(self) -> dict[str, float]:
        """Return DKK commission earned per page key from recorded sales."""
        return revenue_by_page(self.database.get_commission_records())

    def _learning_signals(
        self,
    ) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], int]]:
        """Summarise measured learning once: how often a change type failed on a
        URL, and each site's net win/loss per change type."""
        url_type_failures: dict[tuple[str, str], int] = defaultdict(int)
        site_type_net: dict[tuple[str, str], int] = defaultdict(int)
        for entry in self.database.get_seo_learning_entries():
            change_type = entry.get("change_type", "")
            classification = entry.get("classification", "")
            if classification in NEGATIVE_CLASSIFICATIONS:
                url_type_failures[(entry.get("target_url", ""), change_type)] += 1
                site_type_net[(entry.get("website_id", ""), change_type)] -= 1
            elif classification in POSITIVE_CLASSIFICATIONS:
                site_type_net[(entry.get("website_id", ""), change_type)] += 1
        return url_type_failures, site_type_net

    @staticmethod
    def _steer_by_learning(
        target_url: str, intent: str,
        url_type_failures: dict[tuple[str, str], int],
    ) -> str:
        """Switch away from a change type that already failed twice on this URL
        toward an alternative that has not, so bad choices are not repeated."""
        if url_type_failures.get((target_url, intent), 0) < LEARNING_FAILURE_THRESHOLD:
            return intent
        for alternative in LEARNING_ALTERNATIVES.get(intent, ()):
            if url_type_failures.get(
                (target_url, alternative), 0
            ) < LEARNING_FAILURE_THRESHOLD:
                return alternative
        return intent

    @staticmethod
    def _learning_adjustment(
        website: str, target_url: str, change_type: str,
        url_type_failures: dict[tuple[str, str], int],
        site_type_net: dict[tuple[str, str], int],
    ) -> float:
        """Bounded ranking nudge: reward a site's proven change types, penalise a
        type that keeps failing here. Bounded so learning never overturns the
        income invariants."""
        net = site_type_net.get((website, change_type), 0)
        bias = max(-LEARNING_SITE_BIAS_CAP, min(LEARNING_SITE_BIAS_CAP, net * 1.5))
        if url_type_failures.get(
            (target_url, change_type), 0
        ) >= LEARNING_FAILURE_THRESHOLD:
            bias -= LEARNING_REPEAT_PENALTY
        return round(bias, 1)

    def score_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Return a transparent bounded score where data volume matters."""
        impressions = max(0, int(candidate["current_impressions"]))
        previous_clicks = max(0, int(candidate["previous_clicks"]))
        click_loss = max(
            0, previous_clicks - int(candidate["current_clicks"])
        )
        volume_score = min(22, math.log10(impressions + 1) * 7)
        loss_score = min(18, math.log10(click_loss + 1) * 8)
        ctr_opportunity = min(
            14, max(0, .05 - float(candidate["current_ctr"])) * 280
        )
        commission = max(0.0, float(candidate.get("affiliate_commission", 0)))
        monetization = min(10, math.log10(commission + 1) * 3)
        if not commission:
            monetization = 3 if candidate["monetized"] else 0
        # Monetisation opportunity: real traffic on a monetised page that earns
        # little or nothing. Bounded so it never outweighs a proven earner.
        monetization_gap = 0.0
        if (
            candidate["monetized"]
            and candidate.get("site_has_revenue")
            and commission < MONETIZATION_GAP_MAX_COMMISSION
            and impressions >= MONETIZATION_GAP_MIN_IMPRESSIONS
        ):
            monetization_gap = min(
                MONETIZATION_GAP_CAP, math.log10(impressions + 1) * 2.2
            )
        manual = {
            "high": 4, "medium": 3, "middle": 3, "low": 1
        }.get(str(candidate["manual_priority"]).lower(), 1)
        confidence = int(candidate["confidence"]) * .08
        data_quality = {"Høj": 8, "Mellem": 5, "Lav": 1}.get(
            candidate["data_quality"], 1
        )
        seo_health = float(candidate.get("seo_health_score", 50))
        health_opportunity = min(7, max(0, 70 - seo_health) / 10)
        trend = {
            "critical": 7, "declining": 5, "stable": 2, "growing": 0,
        }.get(str(candidate.get("seo_trend", "")).lower(), 1)
        waiting = min(
            6, float(candidate.get("days_since_implementation", 0)) / 30
        )
        expected_click_gain = max(
            click_loss,
            round(impressions * max(0, .05 - float(candidate["current_ctr"]))),
        )
        expected_gain = min(8, math.log10(expected_click_gain + 1) * 3)
        # Diversitet is a small tie-breaker. Work on another URL must never
        # disqualify a more valuable, independently measurable opportunity.
        work_penalty = 3 if candidate.get("has_active_work") else 0
        experiment_penalty = 0
        risk_penalty = 5 if candidate["risk"] == "Høj" else 0
        learning_adjustment = float(candidate.get("learning_adjustment", 0))
        score = round(min(
            100, volume_score + loss_score + ctr_opportunity
            + monetization + monetization_gap + manual + confidence
            + data_quality + health_opportunity + trend + waiting
            + expected_gain + learning_adjustment
            - work_penalty - experiment_penalty - risk_penalty
        ))
        score = max(0, score)
        if impressions < 10:
            score = min(score, 25)
        candidate = {
            **candidate, "priority_score": score,
            "expected_click_gain": expected_click_gain,
            "score_factors": {
                "traffic_potential": round(volume_score + ctr_opportunity, 1),
                "traffic_trend": round(loss_score + trend, 1),
                "affiliate_income": round(monetization, 1),
                "monetization_opportunity": round(monetization_gap, 1),
                "seo_health": round(health_opportunity, 1),
                "data_quality": round(data_quality, 1),
                "ai_confidence": round(confidence, 1),
                "existing_work_penalty": -work_penalty,
                "active_experiment_penalty": -experiment_penalty,
                "waiting_time": round(waiting, 1),
                "expected_gain": round(expected_gain, 1),
                "learning": round(learning_adjustment, 1),
            },
        }
        candidate["priority_label"] = self._label(score)
        candidate["monetization_opportunity"] = monetization_gap > 0
        return candidate

    def rank_candidates(
        self, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        ranked = sorted(
            (self.score_candidate(item) for item in candidates),
            key=lambda item: (
                -item["priority_score"], -item["current_impressions"],
                item["target_url"],
            ),
        )
        return ranked

    def select_single_decision(
        self, website_id: str | None = None
    ) -> dict[str, Any] | None:
        current = self.get_current_decision(website_id)
        if current:
            return current["decision"]
        ranked = self.rank_candidates(self.collect_candidates(website_id))
        if not ranked:
            return None
        selected = ranked[0]
        selected["why_selected"] = self.explain_decision(selected)
        selected["why_not_other_tasks"] = [
            (
                f"{item['task_title']} blev fravalgt: score "
                f"{item['priority_score']} mod {selected['priority_score']} "
                "og lavere dokumenteret volumen eller effekt."
            )
            for item in ranked[1:4]
        ]
        self._validate_decision(selected)
        selected["decision_id"] = self.database.create_decision(selected)
        return selected

    def explain_decision(self, candidate: dict[str, Any]) -> str:
        commission = max(0.0, float(candidate.get("affiliate_commission", 0)))
        if commission > 0:
            money = (
                f" Siden har givet {commission:.0f} kr. i provision, hvilket "
                "vægter den op."
            )
        elif candidate.get("monetization_opportunity"):
            money = (
                " Siden har trafik men ingen registreret provision endnu — en "
                "moneteringschance."
            )
        else:
            money = ""
        return (
            f"Valgt fordi URL'en har {candidate['current_impressions']} "
            f"visninger, {candidate['current_clicks']} klik mod "
            f"{candidate['previous_clicks']} før, og en score på "
            f"{candidate['priority_score']}. Manuel websiteprioritet udgør "
            f"kun en mindre del af scoren.{money}"
        )

    def daily_overview(self) -> dict[str, Any]:
        """Return the current queue and experiment state for the dashboard."""
        active = self.database.get_seo_experiments(
            statuses=(
                "approved", "running", "waiting_for_data",
                "ready_for_evaluation",
            )
        )
        candidates = self.rank_candidates(self.collect_candidates())
        queued_websites: list[str] = []
        for item in candidates:
            if item["website"] not in queued_websites:
                queued_websites.append(item["website"])
        evaluation_dates = [
            item["planned_evaluation_date"] for item in active
            if item.get("planned_evaluation_date")
        ]
        return {
            "active_experiments": len(active),
            "queued_websites": queued_websites,
            "next_evaluation": min(evaluation_dates) if evaluation_dates else None,
            "candidate_count": len(candidates),
        }

    def get_current_decision(
        self, website_id: str | None = None
    ) -> dict[str, Any] | None:
        rows = self.database.get_decisions(
            statuses=("proposed", "approved", "converted_to_experiment"),
            website_id=website_id,
        )
        if not rows:
            return None
        rows[0]["decision"]["decision_id"] = rows[0]["id"]
        return rows[0]

    def dismiss_decision(self, decision_id: int) -> None:
        self.database.update_decision_status(decision_id, "rejected")

    def send_decision_to_project_manager(
        self, decision_id: int
    ) -> dict[str, int]:
        """Create exactly one approval-pending project, task, and experiment."""
        records = [
            item for item in self.database.get_decisions()
            if item["id"] == decision_id
        ]
        if not records:
            raise ValueError("Beslutningen findes ikke.")
        record = records[0]
        decision = record["decision"]
        self._validate_decision(decision)
        existing_experiment = next((
            item for item in self.experiments.get_experiments_for_url(
                decision["target_url"]
            ) if item.get("decision_id") == decision_id
        ), None)
        if existing_experiment:
            return {
                "project_id": existing_experiment["project_id"],
                "task_id": existing_experiment["task_id"],
                "experiment_id": existing_experiment["id"],
            }
        project_id = self.database.create_project_record({
            "website_id": decision["website"],
            "title": f"SEO-eksperiment: {decision['target_url']}",
            "description": decision["task_description"],
            "status": "planning", "priority": decision["priority_label"].lower(),
            "expected_effect": decision["expected_effect"],
            "created_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
        })
        subproject_id = self.database.create_subproject_record({
            "project_id": project_id, "title": "Afventer godkendelse",
            "description": "Én isoleret SEO-ændring med målelig baseline.",
            "status": "planning", "sequence": 1,
            "created_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
        })
        existing = [
            task for task in self.database.get_task_records_for_project(project_id)
            if task["title"] == decision["task_title"]
        ]
        task_id = existing[0]["id"] if existing else self.database.create_task_record({
            "subproject_id": subproject_id,
            "website_id": decision["website"],
            "title": decision["task_title"],
            "description": (
                decision["task_description"] + "\n\n"
                + "\n".join(
                    f"{index}. {step}" for index, step in enumerate(
                        decision["exact_steps"], start=1
                    )
                ) + "\n\nFærdigkriterium: "
                + decision["completion_criteria"]
            ),
            "reason": decision["why_selected"],
            "assigned_agent": decision["assigned_agent"],
            "estimated_minutes": decision["estimated_minutes"],
            "expected_effect": decision["expected_effect"],
            "measurement_method": decision["measurement_method"],
            "priority_score": decision["priority_score"],
            "status": "planning", "depends_on_task_id": None,
            "created_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
        })
        experiment_id = self.experiments.create_experiment(
            decision, decision_id=decision_id,
            project_id=project_id, task_id=task_id,
        )
        baseline = self.experiments.calculate_baseline(
            decision["website"], decision["target_url"],
            decision.get("target_query", ""),
        )
        self.database.update_seo_experiment(experiment_id, baseline)
        self.database.update_decision_status(
            decision_id, "converted_to_experiment"
        )
        return {
            "project_id": project_id, "task_id": task_id,
            "experiment_id": experiment_id,
        }

    def _conflicts_with_work(self, candidate: dict[str, Any]) -> bool:
        url = candidate["target_url"].lower()
        return any(
            url in (str(item.get("title", "")) + " "
                    + str(item.get("description", ""))).lower()
            and item["status"] not in {"completed", "cancelled"}
            for item in self.database.get_task_records_for_project()
        )

    def has_conflict(self, candidate: dict[str, Any]) -> bool:
        """Block only work that can contaminate an existing measurement."""
        target_url = str(candidate.get("target_url", ""))
        if target_url and self.experiments.is_url_locked(target_url):
            return True
        active = self.database.get_seo_experiments(
            website_id=candidate.get("website"),
            statuses=(
                "approved", "running", "waiting_for_data",
                "ready_for_evaluation",
            ),
        )
        if candidate.get("scope") == "sitewide" and active:
            return True
        if any(
            item.get("target_url") == target_url
            and item.get("experiment_type")
            == candidate.get("experiment_type")
            for item in active
        ):
            return True
        return self._conflicts_with_work(candidate)

    def _website_signals(self, website_id: str) -> dict[str, Any]:
        """Collect stored operational signals without external requests."""
        source = self.database.get_website_intelligence_source(website_id) or {}
        health = source.get("seo_health") or {}
        experiments = self.experiments.get_experiments_for_website(website_id)
        active_experiments = [
            item for item in experiments
            if item["status"] in {
                "approved", "running", "waiting_for_data",
                "ready_for_evaluation",
            }
        ]
        completed = [
            item for item in experiments
            if item["status"] == "completed" and item.get("completed_at")
        ]
        days_since = 90
        if completed:
            latest = max(item["completed_at"] for item in completed)
            try:
                value = datetime.fromisoformat(latest.replace("Z", "+00:00"))
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                days_since = max(
                    0,
                    (
                        datetime.now(timezone.utc)
                        - value.astimezone(timezone.utc)
                    ).days,
                )
            except (TypeError, ValueError):
                days_since = 90
        return {
            "affiliate_commission": float(
                (source.get("partner_ads") or {}).get("commission", 0) or 0
            ),
            "seo_health_score": float(health.get("score", 50) or 50),
            "seo_trend": health.get("trend", "unknown"),
            "has_active_work": bool(
                source.get("active_projects") or source.get("active_tasks")
            ),
            "active_experiment_count": len(active_experiments),
            "days_since_implementation": days_since,
        }

    def _comparisons(
        self, website_id: str, dimension: str,
        key_field: str | tuple[str, ...],
    ) -> list[dict[str, Any]]:
        rows = self.database.get_search_console_dimensions(
            dimension, website_id=website_id
        )
        periods = sorted({
            (row["period_start"], row["period_end"]) for row in rows
        }, reverse=True)
        if len(periods) < 2:
            return []
        keys = (key_field,) if isinstance(key_field, str) else key_field
        def identity(row: dict[str, Any]) -> tuple[Any, ...]:
            return tuple(row[key] for key in keys)
        current = {
            identity(row): row for row in rows
            if (row["period_start"], row["period_end"]) == periods[0]
        }
        previous = {
            identity(row): row for row in rows
            if (row["period_start"], row["period_end"]) == periods[1]
        }
        result = []
        for row_key, row in current.items():
            before = previous.get(row_key, {})
            result.append({
                **dict(zip(keys, row_key)),
                "current_clicks": int(row["clicks"]),
                "previous_clicks": int(before.get("clicks", 0)),
                "current_impressions": int(row["impressions"]),
                "previous_impressions": int(before.get("impressions", 0)),
                "current_ctr": float(row["ctr"]),
                "previous_ctr": float(before.get("ctr", 0)),
                "current_position": float(row["average_position"]),
                "previous_position": float(
                    before.get("average_position", row["average_position"])
                ),
            })
        return result

    @staticmethod
    def _confidence(page: dict[str, Any]) -> int:
        return min(95, 50 + int(math.log10(
            int(page["current_impressions"]) + 1
        ) * 15))

    @staticmethod
    def _data_quality(page: dict[str, Any]) -> str:
        return (
            "Høj" if page["current_impressions"] >= 500 else
            "Mellem" if page["current_impressions"] >= 50 else "Lav"
        )

    @staticmethod
    def _label(score: int) -> str:
        return (
            "Kritisk" if score >= 85 else "Høj" if score >= 70
            else "Mellem" if score >= 45 else "Lav"
        )

    @staticmethod
    def _validate_decision(decision: dict[str, Any]) -> None:
        required = {
            "website", "target_url", "task_title", "task_description",
            "exact_steps", "completion_criteria", "assigned_agent",
            "estimated_minutes", "expected_effect", "expected_effect_reason",
            "priority_score", "priority_label", "confidence",
            "measurement_method", "experiment_type", "experiment_goal",
            "waiting_period_days", "why_selected", "why_not_other_tasks",
        }
        missing = [key for key in required if key not in decision]
        if missing:
            raise ValueError("Beslutningen mangler: " + ", ".join(missing))
        text = (
            decision["task_title"] + " " + decision["task_description"]
        ).lower()
        if any(value in text for value in GENERIC_TASKS):
            raise ValueError("Generiske opgaver accepteres ikke.")
        if not 1 <= int(decision["estimated_minutes"]) <= 120:
            raise ValueError("Opgaven skal kunne udføres på højst 120 minutter.")
        if not isinstance(decision["exact_steps"], list) or not (
            1 <= len(decision["exact_steps"]) <= 5
        ):
            raise ValueError("Exact steps skal indeholde 1-5 trin.")
