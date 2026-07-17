"""Read-only dashboard data facade."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, TypeVar

from core.database import Database


T = TypeVar("T")


@dataclass(frozen=True)
class DashboardData:
    """All database results needed for one dashboard render."""

    system_status: dict[str, bool]
    overview: dict[str, int]
    economy: dict[str, Any]
    seo_counts: dict[str, int]
    seo_sites: list[dict[str, Any]]
    priority_tasks: list[dict[str, Any]]
    recovery_projects: list[dict[str, Any]]
    recent_sales: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]

    @property
    def displayed_database_results(self) -> int:
        """Count records rendered in the dashboard's data tables."""
        return sum(
            len(rows)
            for rows in (
                self.seo_sites,
                self.priority_tasks,
                self.recovery_projects,
                self.recent_sales,
                self.recent_events,
            )
        )


def load_dashboard_data(
    database: Database,
    *,
    seo_trend: str | None = None,
    now: datetime | None = None,
) -> DashboardData:
    """Load each section independently through Database methods only."""
    return DashboardData(
        system_status=_safe(
            database.get_dashboard_system_status,
            {
                "database": False,
                "partner_ads": False,
                "search_console": False,
                "agent_orchestrator": False,
                "knowledge_engine": False,
            },
        ),
        overview=_safe(
            database.get_dashboard_overview,
            {
                "websites": 0,
                "active_websites": 0,
                "monetized": 0,
                "phasing_out": 0,
                "active_projects": 0,
                "open_tasks": 0,
            },
        ),
        economy=_safe(
            lambda: database.get_dashboard_economy(now),
            {
                "today_commission": 0,
                "month_commission": 0,
                "today_sales": 0,
                "month_sales": 0,
            },
        ),
        seo_counts=_safe(
            database.get_seo_health_summary,
            {
                "growing": 0,
                "stable": 0,
                "declining": 0,
                "critical": 0,
            },
        ),
        seo_sites=_safe(
            lambda: database.get_latest_seo_health_sites(seo_trend),
            [],
        ),
        priority_tasks=_safe(database.get_priority_tasks, []),
        recovery_projects=_safe(
            database.get_active_seo_recovery_projects,
            [],
        ),
        recent_sales=_safe(database.get_recent_sales, []),
        recent_events=_safe(database.get_recent_events, []),
    )


def _safe(function: Callable[[], T], fallback: T) -> T:
    try:
        return function()
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        return fallback
