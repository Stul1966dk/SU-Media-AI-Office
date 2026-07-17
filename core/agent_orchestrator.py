"""Central event and action routing for SU Media AI Office."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from agents.decision_engine import DecisionEngine
from agents.project_manager import ProjectManager
from core.database import Database
from core.knowledge_engine import KnowledgeEngine
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry


ORCHESTRATOR_STATUSES = {
    "pending",
    "routed",
    "in_progress",
    "blocked",
    "completed",
    "failed",
    "cancelled",
}

DEFAULT_AGENTS = {
    "Affiliate Manager": {"affiliate", "sales", "commission"},
    "Project Manager": {"planning", "projects", "tasks"},
    "Webmaster": {"wordpress", "design", "technical"},
    "SEO Manager": {"seo", "search_console", "rankings"},
    "Content Manager": {"content", "articles", "product_content"},
    "Trend Agent": {"trends", "news", "market_intelligence"},
}

CAPABILITY_SIGNALS = {
    "affiliate": {"affiliate", "partner-ads"},
    "sales": {"sale", "sales", "salg"},
    "commission": {"commission", "provision"},
    "planning": {
        "planning",
        "plan",
        "redesign",
        "core update",
        "google core",
    },
    "projects": {"project", "projekt", "redesign"},
    "tasks": {"task", "tasks", "opgave", "opgaver"},
    "wordpress": {"wordpress"},
    "design": {"design", "redesign"},
    "technical": {"technical", "teknisk", "tekniske"},
    "seo": {"seo", "core update", "google core"},
    "search_console": {"search console", "search_console"},
    "rankings": {"ranking", "rankings", "placering", "placeringer"},
    "content": {"content", "indhold"},
    "articles": {"article", "articles", "artikel", "artikler"},
    "product_content": {"product content", "produktindhold"},
    "trends": {"trend", "trends", "core update", "google core"},
    "news": {"news", "nyhed", "nyheder"},
    "market_intelligence": {
        "market",
        "marked",
        "markedsændring",
        "markedsændringer",
    },
}

AGENT_ORDER = (
    "Affiliate Manager",
    "Trend Agent",
    "SEO Manager",
    "Content Manager",
    "Webmaster",
    "Project Manager",
)


@dataclass(frozen=True)
class Event:
    """Uniform input event routed by the Orchestrator."""

    event_type: str
    source: str
    website: str
    title: str
    description: str
    priority: int
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now()
        .astimezone()
        .isoformat(timespec="seconds")
    )


@dataclass(frozen=True)
class Action:
    """Uniform work action created from an event."""

    action_type: str
    assigned_agent: str
    website: str
    project_id: int | None
    task_id: int | None
    reason: str
    priority: int
    status: str
    id: int | None = None
    event_id: int | None = None
    depends_on_action_id: int | None = None


class AgentOrchestrator:
    """Route shared events to registered capabilities in a fixed order."""

    def __init__(
        self,
        decision_engine: DecisionEngine,
        project_manager: ProjectManager,
        task_engine: TaskEngine,
        knowledge_engine: KnowledgeEngine,
        database: Database,
        website_registry: WebsiteRegistry,
    ) -> None:
        self.decision_engine = decision_engine
        self.project_manager = project_manager
        self.task_engine = task_engine
        self.knowledge_engine = knowledge_engine
        self.database = database
        self.website_registry = website_registry
        self.agents: dict[str, set[str]] = {}

    def initialize(self) -> int:
        """Register the initial agents and return their count."""
        for name, capabilities in DEFAULT_AGENTS.items():
            self.register_agent(name, capabilities)
        return len(self.agents)

    def register_agent(
        self,
        name: str,
        capabilities: set[str] | list[str] | tuple[str, ...],
    ) -> None:
        """Register or replace one agent's neutral capability list."""
        self.agents[name] = {
            capability.strip().lower() for capability in capabilities
        }

    def submit_event(self, event: Event | dict[str, Any]) -> int:
        """Validate and persist one pending event."""
        normalized = event if isinstance(event, Event) else Event(**event)
        return self.database.create_event_record(
            {
                **asdict(normalized),
                "data_json": json.dumps(
                    normalized.data,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "status": "pending",
            }
        )

    def route_event(self, event: int | Event | dict[str, Any]) -> list[Action]:
        """Create an ordered, dependency-linked action chain."""
        if isinstance(event, int):
            event_id = event
            record = self.database.get_event_record(event_id)
            if record is None:
                raise ValueError(f"Hændelse {event_id} findes ikke.")
            normalized = self._event_from_record(record)
        else:
            normalized = event if isinstance(event, Event) else Event(**event)
            event_id = self.submit_event(normalized)

        agents = self._matching_agents(normalized)
        actions: list[Action] = []
        dependency: int | None = None
        for agent_name in agents:
            action = self.create_action(
                event_id=event_id,
                action_type=f"handle_{normalized.event_type}",
                assigned_agent=agent_name,
                website=normalized.website,
                project_id=normalized.data.get("project_id"),
                task_id=normalized.data.get("task_id"),
                reason=(
                    f"Hændelsen matcher {agent_name}s registrerede kapabiliteter."
                ),
                priority=normalized.priority,
                depends_on_action_id=dependency,
            )
            actions.append(action)
            dependency = action.id

        self.database.update_event_status(
            event_id,
            "routed",
            processed_at=self._now(),
        )
        return actions

    def create_action(
        self,
        *,
        event_id: int,
        action_type: str,
        assigned_agent: str,
        website: str,
        project_id: int | None,
        task_id: int | None,
        reason: str,
        priority: int,
        depends_on_action_id: int | None = None,
    ) -> Action:
        """Persist one action, blocking it when it has a dependency."""
        if assigned_agent not in self.agents:
            raise ValueError(f"Agent er ikke registreret: {assigned_agent}")
        status = "blocked" if depends_on_action_id is not None else "pending"
        action_id = self.database.create_action_record(
            {
                "event_id": event_id,
                "action_type": action_type,
                "assigned_agent": assigned_agent,
                "website": website,
                "project_id": project_id,
                "task_id": task_id,
                "reason": reason,
                "priority": priority,
                "status": status,
                "depends_on_action_id": depends_on_action_id,
                "created_at": self._now(),
            }
        )
        return Action(
            id=action_id,
            event_id=event_id,
            action_type=action_type,
            assigned_agent=assigned_agent,
            website=website,
            project_id=project_id,
            task_id=task_id,
            reason=reason,
            priority=priority,
            status=status,
            depends_on_action_id=depends_on_action_id,
        )

    def get_pending_actions(self) -> list[dict[str, Any]]:
        """Return executable actions whose dependencies are satisfied."""
        return self.database.get_action_records(statuses=("pending",))

    def complete_action(
        self,
        action_id: int,
        result: dict[str, Any],
    ) -> None:
        """Complete an action, store its result, and release the next action."""
        action = self.database.get_action_record(action_id)
        if action is None:
            raise ValueError(f"Handling {action_id} findes ikke.")
        if action["status"] not in {"pending", "in_progress"}:
            raise ValueError("Kun en aktiv handling kan færdigmarkeres.")
        self.database.complete_action_record(
            action_id,
            json.dumps(result, ensure_ascii=False, sort_keys=True),
            self._now(),
        )

    def run_once(self) -> list[dict[str, Any]]:
        """Route every pending event and return currently executable actions."""
        for event in self.database.get_event_records(status="pending"):
            self.route_event(int(event["id"]))
        return self.get_pending_actions()

    def get_counts(self) -> dict[str, int]:
        """Return dashboard queue and registration counts."""
        return {
            **self.database.get_orchestrator_counts(),
            "registered_agents": len(self.agents),
        }

    def _matching_agents(self, event: Event) -> list[str]:
        text = " ".join(
            (
                event.event_type,
                event.source,
                event.title,
                event.description,
                " ".join(str(value) for value in event.data.values()),
            )
        ).casefold()
        required = {
            capability
            for capability, signals in CAPABILITY_SIGNALS.items()
            if any(signal in text for signal in signals)
        }
        explicit = event.data.get("required_capabilities", [])
        if isinstance(explicit, (list, tuple, set)):
            required.update(str(item).lower() for item in explicit)

        return [
            agent
            for agent in AGENT_ORDER
            if agent in self.agents and self.agents[agent] & required
        ]

    @staticmethod
    def _event_from_record(record: dict[str, Any]) -> Event:
        return Event(
            event_type=record["event_type"],
            source=record["source"],
            website=record["website"],
            title=record["title"],
            description=record["description"],
            priority=int(record["priority"]),
            data=json.loads(record["data_json"]),
            created_at=record["created_at"],
        )

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")
