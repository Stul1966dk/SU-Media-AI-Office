"""Professional startup dashboard for SU Media AI Office."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from .database import Database


class Dashboard:
    """Build and render the AI Office startup overview."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def render(
        self,
        next_task: dict[str, Any] | None,
        knowledge_document_count: int = 0,
        orchestrator_counts: dict[str, int] | None = None,
        search_console_status: dict[str, Any] | None = None,
        seo_health_status: dict[str, int] | None = None,
        seo_manager_status: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> str:
        """Return the complete dashboard as terminal-friendly text."""
        current_time = now or datetime.now().astimezone()
        sale_date = (
            f"{current_time.day}-{current_time.month}-{current_time.year}"
        )
        website_counts = self.database.get_website_counts()
        queue_counts = orchestrator_counts or {
            "pending_events": 0,
            "pending_actions": 0,
            "registered_agents": 0,
        }
        search_status = search_console_status or {
            "connection_ok": False,
            "total": 0,
            "latest_sync": None,
            "stored_metrics": 0,
        }
        seo_status = seo_health_status or {
            "growing": 0,
            "stable": 0,
            "declining": 0,
            "critical": 0,
        }
        manager_status = seo_manager_status or {
            "websites_analyzed": 0,
            "new_projects": 0,
            "updated_projects": 0,
            "no_action": 0,
            "highest_priority": None,
        }
        highest = manager_status["highest_priority"]
        highest_project = (
            f"{highest['website_id']} – {highest['reason']}"
            if highest
            else "Ingen"
        )
        today_commission = self.database.get_today_commission(sale_date)
        month_commission = self.database.get_month_commission(
            current_time.year,
            current_time.month,
        )

        lines = [
            "=" * 58,
            "SU Media AI Office",
            current_time.strftime("%d-%m-%Y %H:%M:%S"),
            "=" * 58,
            "",
            (
                "Knowledge Engine: OK "
                f"({knowledge_document_count} dokumenter)"
            ),
            "",
            "Agent Orchestrator",
            self._metric(
                "Ventende hændelser",
                queue_counts["pending_events"],
            ),
            self._metric(
                "Ventende handlinger",
                queue_counts["pending_actions"],
            ),
            self._metric(
                "Registrerede agenter",
                queue_counts["registered_agents"],
            ),
            "",
            "Search Console",
            self._metric(
                "Forbindelse",
                "OK" if search_status["connection_ok"] else "FEJL",
            ),
            self._metric("Properties", search_status["total"]),
            self._metric(
                "Seneste synkronisering",
                search_status["latest_sync"] or "Ingen",
            ),
            self._metric("Gemte dagspunkter", search_status["stored_metrics"]),
            "",
            "SEO Health",
            self._metric("Growing", seo_status["growing"]),
            self._metric("Stable", seo_status["stable"]),
            self._metric("Declining", seo_status["declining"]),
            self._metric("Critical", seo_status["critical"]),
            "",
            "SEO Manager",
            self._metric(
                "Websites analyseret",
                manager_status["websites_analyzed"],
            ),
            self._metric(
                "Nye recovery-projekter",
                manager_status["new_projects"],
            ),
            self._metric(
                "Recovery-projekter opdateret",
                manager_status["updated_projects"],
            ),
            self._metric(
                "Websites uden handling",
                manager_status["no_action"],
            ),
            self._metric("Højeste prioritet", highest_project),
            "",
            "OVERSIGT",
            self._metric("Websites", website_counts["total"]),
            self._metric("Monetized websites", website_counts["monetized"]),
            self._metric(
                "Websites under udfasning",
                website_counts["phasing_out"],
            ),
            self._metric(
                "Dagens provision",
                f"{self._format_currency(today_commission)} kr.",
            ),
            self._metric(
                "Månedens provision",
                f"{self._format_currency(month_commission)} kr.",
            ),
            self._metric(
                "Aktive projekter",
                self.database.get_active_project_count(),
            ),
            self._metric(
                "Åbne opgaver",
                self.database.get_open_task_count(),
            ),
            "",
            "DAGENS VIGTIGSTE OPGAVE",
            "",
        ]

        if next_task is None:
            lines.append("Ingen klar opgave.")
        else:
            lines.extend(
                [
                    f"Website          {next_task['website_id']}",
                    f"Projekt          {next_task['project_title']}",
                    f"Delprojekt       {next_task['subproject_title']}",
                    f"Opgave           {next_task['title']}",
                    f"Ansvarlig agent  {next_task['assigned_agent']}",
                    (
                        "Estimeret tid    "
                        f"{next_task['estimated_minutes']} minutter"
                    ),
                    f"Begrundelse      {next_task['reason']}",
                ]
            )

        lines.extend(["", "AI Office er klar.", "=" * 58])
        return "\n".join(lines)

    @staticmethod
    def _format_currency(value: Decimal) -> str:
        return f"{value:,.2f}".translate(
            str.maketrans({",": ".", ".": ","})
        )

    @staticmethod
    def _metric(label: str, value: object) -> str:
        return f"{label:<29}{value}"
