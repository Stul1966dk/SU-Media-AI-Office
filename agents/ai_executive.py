"""Evidence-based daily company prioritization without operational side effects."""

import json
import logging
import re
from datetime import date
from typing import Any

from core.ai_service import AIResponse, AIService
from core.database import Database
from core.prompt_guidelines import PromptGuidelines
from core.executive_intelligence import ExecutiveIntelligence, GENERIC_ACTIONS


IGNORED_STATUSES = {"phasing_out", "archived", "cancelled"}
ACTION_TYPES = {
    "create_project", "continue_project", "perform_task", "monitor", "no_action"
}
FOCUS_FIELDS = {
    "rank", "website", "title", "reason", "evidence",
    "recommended_action", "action_type", "project_id", "task_id",
    "assigned_agent", "estimated_minutes", "expected_effect",
    "priority_score", "confidence",
    "problem_or_opportunity", "why_it_matters", "likely_cause",
    "expected_effect_reason", "priority_label", "priority_reason",
    "measurement_method", "limitations", "data_sources",
    "task_title", "task_description", "target_url", "target_query",
    "exact_steps", "completion_criteria",
}
ROOT_FIELDS = {
    "summary", "company_status", "focus_areas", "risks", "opportunities",
    "total_estimated_minutes", "model",
}


class BriefingValidationError(ValueError):
    """A model response could not be normalized into a safe briefing."""


class AIExecutive:
    """Select at most three concrete, explainable priorities for approval."""

    def __init__(
        self, *, ai_service: AIService, ai_analyst: Any, database: Database,
        website_registry: Any, website_intelligence: Any, seo_history: Any,
        seo_manager: Any, project_manager: Any, task_engine: Any,
        knowledge_engine: Any, agent_orchestrator: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self.ai_service = ai_service
        self.ai_analyst = ai_analyst
        self.database = database
        self.website_registry = website_registry
        self.website_intelligence = website_intelligence
        self.seo_history = seo_history
        self.seo_manager = seo_manager
        self.project_manager = project_manager
        self.task_engine = task_engine
        self.knowledge_engine = knowledge_engine
        self.agent_orchestrator = agent_orchestrator
        self.logger = logger or logging.getLogger(__name__)

    def collect_company_context(
        self, website_id: str | None = None
    ) -> dict[str, Any]:
        """Collect only persisted business facts and company knowledge."""
        context = self.database.get_executive_context()
        context["websites"] = [
            item for item in context["websites"]
            if item.get("status") not in IGNORED_STATUSES and item.get("active")
        ]
        eligible = {item["website"] for item in context["websites"]}
        if website_id is not None:
            eligible &= {website_id}
            context["websites"] = [
                item for item in context["websites"]
                if item["website"] == website_id
            ]
        for key in ("profiles", "seo_health", "search_console",
                    "seo_recommendations", "projects", "tasks", "analyses"):
            context[key] = [
                item for item in context[key]
                if not item.get("website_id") or item.get("website_id") in eligible
            ]
        if website_id is not None:
            context["sales"] = [
                item for item in context["sales"]
                if website_id in str(item.get("source", "")).lower()
                or website_id in str(item.get("website", "")).lower()
            ]
            context["scope_limitation"] = (
                "Analysen bygger på website-niveau. Data om konkrete sider "
                "og søgeord er endnu ikke importeret."
            )
        context["company_knowledge"] = self.knowledge_engine.get_company_rules()
        context["counts"]["websites_analyzed"] = len(context["websites"])
        if website_id is not None:
            context["counts"]["active_projects"] = len(context["projects"])
            context["counts"]["open_tasks"] = len(context["tasks"])
        return self._sanitize(context)

    def rank_opportunities(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Build deterministic candidates scored from traceable evidence."""
        profiles = {x["website_id"]: x for x in context["profiles"]}
        seo = {x["website_id"]: x for x in context["seo_health"]}
        search = {x["website_id"]: x for x in context["search_console"]}
        projects = context["projects"]
        tasks = context["tasks"]
        sales = context["sales"]
        ranked = []
        for site in context["websites"]:
            website = site["website"]
            profile, health, trend = (
                profiles.get(website, {}), seo.get(website, {}),
                search.get(website, {}),
            )
            active_project = next(
                (p for p in projects if p["website_id"] == website), None
            )
            open_task = next(
                (t for t in tasks if t["website_id"] == website), None
            )
            evidence, score = [], 0
            if site.get("monetized"):
                score += 10
                evidence.append("Website er monetized.")
            seo_score = health.get("score")
            if seo_score is not None:
                score += min(25, max(0, round((100-float(seo_score))*0.25)))
                evidence.append(f"SEO Health er {float(seo_score):.1f}/100.")
            click_change = trend.get("click_change_percent")
            if click_change is not None:
                score += min(20, max(0, round(-float(click_change)*0.5)))
                evidence.append(f"Klikudvikling er {float(click_change):+.1f}%.")
            site_sales = [
                item for item in sales
                if website in str(item.get("source", "")).lower()
            ]
            commission = sum(float(item.get("commission", 0) or 0)
                             for item in site_sales)
            sales_count = sum(int(item.get("sales_count", 0) or 0)
                              for item in site_sales)
            if commission > 0:
                score += min(20, 5 + round(commission / 100))
                evidence.append(
                    f"Salgshistorik: {sales_count} salg og "
                    f"{commission:.2f} i provision."
                )
            if active_project:
                score += 12
                evidence.append(f"Aktivt projekt #{active_project['id']}: "
                                f"{active_project['title']}.")
            if open_task:
                score += 8
                evidence.append(f"Åben opgave #{open_task['id']}: "
                                f"{open_task['title']}.")
            evidence_count = len(evidence)
            confidence = min(95, 30 + evidence_count * 13)
            ranked.append({
                "website": website,
                "title": (open_task or active_project or {}).get(
                    "title", f"Undersøg potentialet på {website}"
                ),
                "evidence": evidence,
                "priority_score": min(100, score) if evidence_count >= 2 else min(49, score),
                "confidence": confidence,
                "project_id": active_project["id"] if active_project else None,
                "task_id": open_task["id"] if open_task else None,
                "estimated_minutes": min(120, int(
                    (open_task or {}).get("estimated_minutes", 60)
                )),
            })
        return sorted(ranked, key=lambda x: (-x["priority_score"], -x["confidence"]))

    def select_focus_areas(self, opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Select and normalize no more than the three strongest candidates."""
        return opportunities[:3]

    def recommend_next_action(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Convert a candidate into a concrete, approval-only next action."""
        confidence = candidate["confidence"]
        if confidence < 60:
            action_type, action = "monitor", "Indsaml manglende data og revurdér."
        elif candidate.get("task_id"):
            action_type, action = "perform_task", "Fortsæt den identificerede åbne opgave."
        elif candidate.get("project_id"):
            action_type, action = "continue_project", "Definér næste opgave i det aktive projekt."
        else:
            action_type, action = "create_project", "Godkend afgrænset analyseprojekt."
        return {
            **candidate,
            "reason": "Prioriteret ud fra: " + "; ".join(candidate["evidence"]),
            "recommended_action": action,
            "action_type": action_type,
            "assigned_agent": "Project Manager",
            "expected_effect": "Reduceret usikkerhed og målbar fremdrift.",
        }

    def generate_daily_briefing(
        self, website_id: str | None = None
    ) -> dict[str, Any]:
        """Generate, validate and persist today's briefing; retry JSON once."""
        context = self.collect_company_context(website_id=website_id)
        ranked = self.rank_opportunities(context)
        proposed = [self.recommend_next_action(x)
                    for x in self.select_focus_areas(ranked)]
        prompt = PromptGuidelines(self.database).apply(
            self._prompt(context, proposed), "executive_briefing"
        )
        response = self.ai_service.generate_response(prompt)
        responses: list[AIResponse] = [response]
        self._log_response_structure(response.text, "initial")
        try:
            result = self._validate_json(response.text)
        except (ValueError, TypeError, json.JSONDecodeError) as initial_error:
            self.logger.warning(
                "AI Executive modelsvar ugyldigt: %s: %s",
                type(initial_error).__name__, str(initial_error),
            )
            repair = self.ai_service.generate_response(
                PromptGuidelines(self.database).apply(
                    self._repair_prompt(response.text, initial_error),
                    "executive_briefing",
                )
            )
            responses.append(repair)
            self._log_response_structure(repair.text, "repair")
            try:
                result = self._validate_json(repair.text)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.logger.warning(
                    "AI Executive repair ugyldig: %s: %s",
                    type(error).__name__, str(error),
                )
                raise BriefingValidationError(
                    f"{type(error).__name__}: {error}"
                ) from None
        result["model"] = responses[-1].model
        result = ExecutiveIntelligence(
            self.database, self.knowledge_engine.get_company_rules()
        ).enrich_briefing(result, website_id=website_id)
        metadata = {
            "prompt_tokens": sum(x.prompt_tokens for x in responses),
            "completion_tokens": sum(x.completion_tokens for x in responses),
            "latency_ms": sum(x.latency_ms for x in responses),
        }
        self.save_briefing(result, metadata)
        return {**result, **metadata, "briefing_date": date.today().isoformat(),
                "status": "completed", "counts": context["counts"]}

    def save_briefing(
        self, briefing: dict[str, Any], usage: dict[str, int] | None = None
    ) -> int:
        return self.database.save_executive_briefing({
            **briefing, **(usage or {}), "briefing_date": date.today().isoformat(),
            "status": "completed",
        })

    def get_latest_briefing(self) -> dict[str, Any] | None:
        return self.database.get_latest_executive_briefing()

    @staticmethod
    def missing_data(context: dict[str, Any]) -> list[str]:
        """Return plain-language names for missing evidence sources."""
        return [
            label for key, label in (
                ("websites", "aktive websites"),
                ("profiles", "websiteprofiler"),
                ("seo_health", "SEO Health"),
                ("search_console", "Search Console-data"),
                ("sales", "salgshistorik"),
                ("analyses", "AI-analyser"),
            ) if not context.get(key)
        ]

    def _prompt(self, context: dict[str, Any], proposed: list[dict[str, Any]]) -> str:
        schema = {key: ([] if key in {"focus_areas", "risks", "opportunities"}
                        else 0 if key == "total_estimated_minutes" else "")
                  for key in ROOT_FIELDS}
        return (
            "Du er AI Executive for SU Media. Returnér kun gyldig JSON. "
            "Vælg højst tre fokusområder og behold de dokumenterede scores. "
            "Ingen handling må udføres. Confidence under 60 er observation, "
            "60-79 anbefaling, og 80+ klar til godkendelse. Hver opgave er "
            "højst 120 minutter. Schema: " + json.dumps(schema, ensure_ascii=False)
            + "\nKANDIDATER:\n" + json.dumps(proposed, ensure_ascii=False)
            + "\nKONTEKST:\n" + json.dumps(context, ensure_ascii=False, default=str)
        )

    @staticmethod
    def _repair_prompt(invalid_response: str, error: Exception) -> str:
        focus_schema = {
            "rank": 1, "website": "example.dk", "title": "",
            "reason": "", "evidence": [], "recommended_action": "",
            "action_type": "monitor", "assigned_agent": "",
            "estimated_minutes": 0, "expected_effect": "",
            "priority_score": 0, "confidence": 0,
            "problem_or_opportunity": "", "why_it_matters": "",
            "likely_cause": "", "expected_effect_reason": "",
            "priority_label": "low|medium|high|critical",
            "priority_reason": "", "measurement_method": "",
            "limitations": [], "task_title": "", "task_description": "",
            "target_url": "", "target_query": "", "exact_steps": [],
            "completion_criteria": "",
        }
        root_schema = {
            "summary": "", "company_status": "",
            "focus_areas": [focus_schema], "risks": [],
            "opportunities": [], "total_estimated_minutes": 0, "model": "",
        }
        return (
            "Reparer JSON-svaret nedenfor. Returnér kun ét JSON-objekt og "
            "præcis dette schema uden forklaring eller markdown. Hvert "
            "fokusområde skal indeholde samtlige viste felter. Bevar website, "
            "confidence og priority_score fra svaret; opfind dem ikke. Schema: "
            + json.dumps(root_schema, ensure_ascii=False)
            + "\nValideringsfejl: "
            + f"{type(error).__name__}: {str(error)[:200]}"
            + "\nSvar der skal repareres:\n" + invalid_response
        )

    def _log_response_structure(self, text: str, phase: str) -> None:
        """Log only JSON keys and types, never response values."""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(
                    r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I
                )
            structure = self._json_structure(json.loads(cleaned))
        except Exception as error:
            structure = {"parse_error": type(error).__name__}
        self.logger.debug(
            "AI Executive %s JSON-struktur: %s",
            phase, json.dumps(structure, ensure_ascii=False),
        )

    @classmethod
    def _json_structure(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): cls._json_structure(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return {
                "type": "list", "length": len(value),
                "items": [cls._json_structure(item) for item in value[:1]],
            }
        return type(value).__name__

    @staticmethod
    def _validate_json(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I
            )
        raw = json.loads(cleaned)
        if not isinstance(raw, dict):
            raise TypeError("Briefingen skal være et JSON-objekt.")
        result = AIExecutive._normalize_mapping(raw, {
            "focusareas": "focus_areas",
            "companystatus": "company_status",
            "totalestimatedminutes": "total_estimated_minutes",
        })
        for field, default in (
            ("summary", ""), ("company_status", ""), ("focus_areas", []),
            ("risks", []), ("opportunities", []),
            ("total_estimated_minutes", 0), ("model", ""),
        ):
            result.setdefault(field, default)
        result = {key: result[key] for key in ROOT_FIELDS}
        if not isinstance(result["focus_areas"], list) or len(result["focus_areas"]) > 3:
            raise ValueError("Der må højst være tre fokusområder.")
        normalized_focus = []
        aliases = {
            "actiontype": "action_type", "projectid": "project_id",
            "taskid": "task_id", "assignedagent": "assigned_agent",
            "estimatedminutes": "estimated_minutes",
            "expectedeffect": "expected_effect",
            "priorityscore": "priority_score",
            "focus": "title",
            "recommendation": "recommended_action",
            "action": "recommended_action",
            "recommendedaction": "recommended_action",
            "reasons": "reason",
            "priority": "priority_score",
        }
        for rank, raw_focus in enumerate(result["focus_areas"], 1):
            if not isinstance(raw_focus, dict):
                raise TypeError(f"Fokusområde {rank} skal være et objekt.")
            focus = AIExecutive._normalize_mapping(raw_focus, aliases)
            for field, default in {
                "rank": rank, "project_id": None,
                "task_id": None, "assigned_agent": "Project Manager",
                "estimated_minutes": 0, "expected_effect": "",
            }.items():
                focus.setdefault(field, default)
            critical_missing = [
                field for field in (
                    "website", "recommended_action",
                    "priority_score", "confidence",
                )
                if field not in focus or focus[field] in (None, "")
            ]
            if critical_missing:
                raise ValueError(
                    f"Fokusområde {rank} mangler kritiske felter: "
                    + ", ".join(critical_missing)
                )
            defaults = {
                "title": f"Prioriteret indsats for {focus['website']}",
                "reason": "Datagrundlaget peger på et muligt indsatsområde.",
                "evidence": [],
                "action_type": "monitor",
            }
            for field, default in defaults.items():
                if field not in focus or focus[field] in (None, ""):
                    focus[field] = default
            focus = {key: focus.get(key) for key in FOCUS_FIELDS}
            focus["rank"] = rank
            if focus["action_type"] not in ACTION_TYPES:
                raise ValueError(
                    f"Fokusområde {rank} har ugyldig handlingstype."
                )
            action = str(focus["recommended_action"]).strip().lower()
            if any(generic in action for generic in GENERIC_ACTIONS):
                raise ValueError(
                    f"Fokusområde {rank} har en for generisk anbefaling."
                )
            for field in ("priority_score", "confidence"):
                if isinstance(focus[field], bool):
                    raise TypeError(field)
                try:
                    focus[field] = int(float(focus[field]))
                except (TypeError, ValueError):
                    raise TypeError(
                        f"Fokusområde {rank}: {field} skal være et tal."
                    ) from None
                focus[field] = max(0, min(100, focus[field]))
            try:
                focus["estimated_minutes"] = max(
                    0, min(120, int(float(focus["estimated_minutes"])))
                )
            except (TypeError, ValueError):
                raise TypeError(
                    f"Fokusområde {rank}: estimated_minutes skal være et tal."
                ) from None
            if isinstance(focus["evidence"], str):
                focus["evidence"] = [focus["evidence"]]
            if not isinstance(focus["evidence"], list):
                raise TypeError("Evidens skal være en liste.")
            focus["evidence"] = [str(item) for item in focus["evidence"]]
            if focus["confidence"] < 60:
                focus["action_type"] = "monitor"
            normalized_focus.append(focus)
        result["focus_areas"] = normalized_focus
        for field in ("risks", "opportunities"):
            if isinstance(result[field], str):
                result[field] = [result[field]]
            if not isinstance(result[field], list):
                raise TypeError(f"{field} skal være en liste.")
            result[field] = result[field]
        result["total_estimated_minutes"] = sum(
            item["estimated_minutes"] for item in result["focus_areas"]
        )
        return result

    @staticmethod
    def _normalize_mapping(
        value: dict[str, Any], aliases: dict[str, str]
    ) -> dict[str, Any]:
        normalized = {}
        for key, item in value.items():
            compact = re.sub(r"[^a-z0-9]", "", str(key).lower())
            canonical = aliases.get(
                compact,
                re.sub(r"[\s-]+", "_", str(key).strip().lower()),
            )
            normalized[canonical] = item
        return normalized

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: cls._sanitize(v) for k, v in value.items()
                    if not re.search(
                        r"api.?key|token|secret|credential|password|email|phone",
                        str(k), re.I)}
        if isinstance(value, list):
            return [cls._sanitize(v) for v in value]
        if isinstance(value, str):
            return re.sub(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b",
                          "[REDACTED]", value, flags=re.I)
        return value
