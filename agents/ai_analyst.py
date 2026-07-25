"""Central read-only AI analyst for evidence-based recommendations."""

import json
import logging
import re
from datetime import date, timedelta
from typing import Any

from agents.project_manager import ProjectManager
from agents.website_intelligence import WebsiteIntelligenceAgent
from core.ai_service import AIResponse, AIService
from core.database import Database
from core.knowledge_engine import KnowledgeEngine
from core.seo_history import SEOHistory
from core.task_engine import TaskEngine


PRIORITIES = {"low", "medium", "high", "critical"}
REPORT_FIELDS = {
    "summary": str,
    "problem": str,
    "root_cause": str,
    "recommended_action": str,
    "priority": str,
    "confidence": int,
    "expected_effect": str,
    "reasoning": list,
    "required_agents": list,
    "suggested_tasks": list,
}
KNOWLEDGE_FILES = {
    "company_playbook",
    "seo_rules",
    "tone_of_voice",
    "affiliate_rules",
}
REDACTED = "[REDACTED]"


class AIAnalyst:
    """Analyze persisted office data without executing operational actions."""

    def __init__(
        self,
        *,
        ai_service: AIService,
        database: Database,
        knowledge_engine: KnowledgeEngine,
        website_intelligence: WebsiteIntelligenceAgent,
        seo_history: SEOHistory,
        project_manager: ProjectManager,
        task_engine: TaskEngine,
        logger: logging.Logger | None = None,
    ) -> None:
        self.ai_service = ai_service
        self.database = database
        self.knowledge_engine = knowledge_engine
        self.website_intelligence = website_intelligence
        self.seo_history = seo_history
        self.project_manager = project_manager
        self.task_engine = task_engine
        self.logger = logger or logging.getLogger(__name__)

    def analyze_site(self, website_id: str) -> dict[str, Any]:
        """Analyze one website from persisted profile and history data."""
        context = self._website_context(website_id)
        return self._analyze(
            "website",
            context,
            website_id=website_id,
        )

    def analyze_project(self, project_id: int) -> dict[str, Any]:
        """Analyze one project and its stored tasks."""
        project = self.task_engine.get_project(project_id)
        if project is None:
            raise ValueError(f"Projekt {project_id} findes ikke.")
        website_id = project["website_id"]
        context = self._website_context(website_id)
        context["analysis_focus"] = {
            "project": self._safe_project(project),
            "project_tasks": [
                self._safe_task(item)
                for item in self.task_engine.get_tasks_for_project(project_id)
            ],
        }
        return self._analyze(
            "project",
            context,
            website_id=website_id,
            project_id=project_id,
        )

    def analyze_task(self, task_id: int) -> dict[str, Any]:
        """Analyze one stored task in its website and project context."""
        task = self.database.get_task_record(task_id)
        if task is None:
            raise ValueError(f"Opgave {task_id} findes ikke.")
        context = self._website_context(task["website_id"])
        context["analysis_focus"] = {"task": self._safe_task(task)}
        return self._analyze(
            "task",
            context,
            website_id=task["website_id"],
            project_id=task["project_id"],
            task_id=task_id,
        )

    def daily_analysis(self) -> list[dict[str, Any]]:
        """Analyze every active persisted website profile once."""
        reports = []
        for profile in self.database.get_website_profiles():
            website = self.database.get_website(profile["website_id"])
            if (
                profile["status"] == "active"
                and website is not None
                and website["active"]
                and website["status"] == "active"
            ):
                reports.append(self.analyze_site(profile["website_id"]))
        return reports

    def generate_prompt(
        self,
        analysis_type: str,
        context: dict[str, Any],
        *,
        retry: bool = False,
    ) -> str:
        """Build a sanitized, deterministic JSON analysis prompt."""
        schema = {
            "summary": "",
            "problem": "",
            "root_cause": "",
            "recommended_action": "",
            "priority": "low|medium|high|critical",
            "confidence": 0,
            "expected_effect": "",
            "reasoning": ["konkret evidens"],
            "required_agents": ["relevant agent"],
            "suggested_tasks": ["konkret opgave"],
        }
        retry_instruction = (
            "\nDit forrige svar var ugyldigt. Returnér nu kun gyldig JSON."
            if retry
            else ""
        )
        payload = json.dumps(
            self._sanitize(context),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return (
            "Du er AI Analyst i SU Media AI Office. Analysér kun de "
            f"leverede, gemte data. Analysetype: {analysis_type}. "
            "Begrund konklusioner med evidens fra input. Foreslå konkrete "
            "handlinger, men udfør intet, opret ingen projekter eller opgaver "
            "og ændr ingen websites. Returnér kun ét JSON-objekt uden "
            "markdown. Confidence skal være et heltal fra 0 til 100. "
            f"Schema: {json.dumps(schema, ensure_ascii=False)}."
            f"{retry_instruction}\nDATA:\n{payload}"
        )

    def generate_report(self, analysis: dict[str, Any]) -> str:
        """Render a complete saved analysis as readable text."""
        reasoning = "\n".join(
            f"- {item}" for item in analysis.get("reasoning", [])
        )
        tasks = "\n".join(
            f"- {item}" for item in analysis.get("suggested_tasks", [])
        )
        return (
            f"{analysis['summary']}\n\n"
            f"Problem: {analysis['problem']}\n"
            f"Rodårsag: {analysis['root_cause']}\n"
            f"Anbefalet handling: {analysis['recommended_action']}\n"
            f"Prioritet: {analysis['priority']}\n"
            f"Confidence: {analysis['confidence']}\n"
            f"Forventet effekt: {analysis['expected_effect']}\n\n"
            f"Begrundelse:\n{reasoning or '- Ingen'}\n\n"
            f"Foreslåede opgaver:\n{tasks or '- Ingen'}"
        )

    def _analyze(
        self,
        analysis_type: str,
        context: dict[str, Any],
        *,
        website_id: str | None = None,
        project_id: int | None = None,
        task_id: int | None = None,
    ) -> dict[str, Any]:
        responses: list[AIResponse] = []
        report: dict[str, Any] | None = None
        for attempt in range(2):
            prompt = self.generate_prompt(
                analysis_type,
                context,
                retry=attempt == 1,
            )
            response = self.ai_service.generate_response(prompt)
            responses.append(response)
            self._log_usage(response)
            try:
                report = self._validate_json(response.text)
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
            break

        usage = self._usage(responses)
        if report is None:
            report = {
                "summary": "AI-analysen kunne ikke valideres.",
                "problem": "Modellen returnerede ugyldig JSON to gange.",
                "root_cause": "Ugyldigt struktureret modelsvar.",
                "recommended_action": "Gennemgå prompt og prøv analysen igen.",
                "priority": "low",
                "confidence": 0,
                "expected_effect": "Ingen handling før gyldig analyse.",
                "reasoning": [],
                "required_agents": [],
                "suggested_tasks": [],
            }
            stored_type = f"{analysis_type}_error"
        else:
            stored_type = analysis_type

        analysis = {
            **report,
            "website_id": website_id,
            "project_id": project_id,
            "task_id": task_id,
            "analysis_type": stored_type,
            **usage,
        }
        analysis["id"] = self.database.save_ai_analysis(analysis)
        analysis["disposition"] = self._disposition(analysis["confidence"])
        return analysis

    def _website_context(self, website_id: str) -> dict[str, Any]:
        website = self.database.get_website(website_id)
        if (
            website is None
            or not website["active"]
            or website["status"] != "active"
        ):
            raise ValueError(f"Website er ikke aktivt: {website_id}")
        profile = self.database.get_website_profile_detail(website_id)
        source = self.database.get_website_intelligence_source(website_id)
        if profile is None or source is None:
            raise ValueError(f"Websiteprofil findes ikke: {website_id}")
        metrics = self.database.get_search_console_daily_metrics(
            website_id=website_id,
            start_date=(date.today() - timedelta(days=180)).isoformat(),
            end_date=date.today().isoformat(),
        )
        return {
            "website_profile": profile["profile"],
            "website_statistics": profile["statistics"],
            "website_categories": profile["categories"],
            "seo_health": source["seo_health"],
            "search_console_history": [
                {
                    "date": item["metric_date"],
                    "clicks": item["clicks"],
                    "impressions": item["impressions"],
                    "ctr": item["ctr"],
                    "position": item["average_position"],
                }
                for item in metrics
            ],
            "partner_ads_history": [
                {
                    "date": item["dato"],
                    "revenue": item["omsaetning"],
                    "commission": item["provision"],
                }
                for item in source["partner_ads"]["sales"]
            ],
            "active_projects": [
                self._safe_project(item)
                for item in source["active_projects"]
            ],
            "active_tasks": [
                self._safe_task(item) for item in source["active_tasks"]
            ],
            "knowledge": self._knowledge_context(),
        }

    def _knowledge_context(self) -> dict[str, str]:
        return {
            document.path.stem: document.content
            for document in self.knowledge_engine.get_documents()
            if document.path.stem in KNOWLEDGE_FILES
        }

    @staticmethod
    def _safe_project(project: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "id",
            "website_id",
            "title",
            "description",
            "status",
            "priority",
            "expected_effect",
        )
        return {field: project.get(field) for field in fields}

    @staticmethod
    def _safe_task(task: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "id",
            "project_id",
            "project_title",
            "subproject_title",
            "title",
            "description",
            "reason",
            "assigned_agent",
            "estimated_minutes",
            "expected_effect",
            "measurement_method",
            "priority_score",
            "status",
        )
        return {field: task.get(field) for field in fields}

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._sanitize(item)
                for key, item in value.items()
                if not re.search(
                    r"api.?key|token|secret|credential|password|"
                    r"ordrenr|email|phone|telefon|person",
                    str(key),
                    re.IGNORECASE,
                )
            }
        if isinstance(value, list):
            return [cls._sanitize(item) for item in value]
        if isinstance(value, str):
            text = re.sub(
                r"(?i)\b(sk|rk|pk)-[A-Za-z0-9_-]{8,}\b",
                REDACTED,
                value,
            )
            text = re.sub(
                r"(?i)\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
                REDACTED,
                text,
            )
            text = re.sub(
                r"(?<!\w)(?:\+45\s*)?(?:\d[\s.-]*){8}(?!\w)",
                REDACTED,
                text,
            )
            return text
        return value

    @staticmethod
    def _validate_json(text: str) -> dict[str, Any]:
        report = json.loads(text)
        if not isinstance(report, dict) or set(report) != set(REPORT_FIELDS):
            raise ValueError("JSON-schema matcher ikke.")
        for field, expected_type in REPORT_FIELDS.items():
            value = report[field]
            if field == "confidence":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise TypeError("Confidence skal være et heltal.")
            elif not isinstance(value, expected_type):
                raise TypeError(f"Ugyldig type for {field}.")
        if report["priority"] not in PRIORITIES:
            raise ValueError("Ugyldig prioritet.")
        if not 0 <= report["confidence"] <= 100:
            raise ValueError("Confidence skal være 0-100.")
        if not all(isinstance(item, str) for item in report["reasoning"]):
            raise TypeError("Reasoning skal være tekst.")
        if not all(
            isinstance(item, str) for item in report["required_agents"]
        ):
            raise TypeError("Required agents skal være tekst.")
        return report

    @staticmethod
    def _usage(responses: list[AIResponse]) -> dict[str, Any]:
        last = responses[-1]
        return {
            "model": last.model,
            "prompt_tokens": sum(item.prompt_tokens for item in responses),
            "completion_tokens": sum(
                item.completion_tokens for item in responses
            ),
            "latency_ms": sum(item.latency_ms for item in responses),
        }

    def _log_usage(self, response: AIResponse) -> None:
        self.logger.info(
            "AI Analyst model=%s prompt_tokens=%d completion_tokens=%d "
            "latency_ms=%d",
            response.model,
            response.prompt_tokens,
            response.completion_tokens,
            response.latency_ms,
        )

    @staticmethod
    def _disposition(confidence: int) -> str:
        if confidence < 60:
            return "suggestion_only"
        if confidence <= 80:
            return "recommendation"
        return "seo_manager_review"
