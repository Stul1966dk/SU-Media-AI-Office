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
                # A pure monetisation gap (no separate SEO problem) becomes a
                # monetisation change instead of a title/meta rewrite.
                if monetization_gap and click_drop <= 0 and not low_ctr:
                    self._to_monetization_candidate(candidate, page)
                if not include_locked and self.has_conflict(candidate):
                    continue
                candidates.append(candidate)
        return candidates

    @staticmethod
    def _to_monetization_candidate(
        candidate: dict[str, Any], page: dict[str, Any]
    ) -> None:
        """Convert a base candidate into a monetization change suggestion."""
        impressions = int(page["current_impressions"])
        target_url = candidate["target_url"]
        candidate.update({
            "experiment_type": "monetization",
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

    def page_revenue_map(self) -> dict[str, float]:
        """Return DKK commission earned per page key from recorded sales."""
        return revenue_by_page(self.database.get_commission_records())

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
        score = round(min(
            100, volume_score + loss_score + ctr_opportunity
            + monetization + monetization_gap + manual + confidence
            + data_quality + health_opportunity + trend + waiting
            + expected_gain
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
