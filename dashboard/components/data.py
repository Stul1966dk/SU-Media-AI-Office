"""Read-only dashboard data facade."""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, TypeVar

from core.database import Database
from core.priority_config import PRIORITY_CONFIG
from core.priority_scoring import score_priority_item, stable_priority_key


T = TypeVar("T")


@dataclass(frozen=True)
class DashboardData:
    """All database results needed for one dashboard render."""

    system_status: dict[str, dict[str, Any]]
    overview: dict[str, int]
    economy: dict[str, Any]
    seo_counts: dict[str, int]
    seo_sites: list[dict[str, Any]]
    priority_tasks: list[dict[str, Any]]
    recent_sales: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]
    ai_status: dict[str, Any]

    @property
    def displayed_database_results(self) -> int:
        """Count records rendered in the dashboard's data tables."""
        return sum(
            len(rows)
            for rows in (
                self.seo_sites,
                self.priority_tasks,
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
    system_status = _safe(database.get_dashboard_system_health, {})
    seo_sites = _safe(
        lambda: database.get_latest_seo_health_sites(seo_trend), []
    )
    project_tasks = _safe(database.get_priority_tasks, [])
    action_context = _safe(
        database.get_dashboard_action_context,
        {
            "experiments": [], "coverage": [], "seo_health": [],
            "plausible_daily": [], "active_experiments": [],
        },
    )
    persisted_priority_tasks = _safe(
        lambda: database.get_priority_task_scores(), []
    )
    if not isinstance(persisted_priority_tasks, list):
        persisted_priority_tasks = []
    return DashboardData(
        system_status=system_status,
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
                "month_sales_rows": [],
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
        seo_sites=seo_sites,
        priority_tasks=(
            persisted_priority_tasks
            or build_dashboard_priority_tasks(
                system_status=system_status,
                seo_sites=action_context["seo_health"],
                project_tasks=project_tasks,
                experiments=action_context["experiments"],
                active_experiments=action_context.get(
                    "active_experiments", []
                ),
                coverage=action_context["coverage"],
                plausible_rows=action_context["plausible_daily"],
                today=(now.date() if now else date.today()),
            )
        ),
        recent_sales=_safe(database.get_recent_sales, []),
        recent_events=_safe(database.get_recent_events, []),
        ai_status=_safe(
            database.get_ai_analysis_status,
            {
                "total": 0,
                "average_confidence": 0,
                "latest_analysis": None,
            },
        ),
    )


def build_dashboard_priority_tasks(
    *,
    system_status: dict[str, dict[str, Any]],
    seo_sites: list[dict[str, Any]],
    project_tasks: list[dict[str, Any]],
    experiments: list[dict[str, Any]],
    active_experiments: list[dict[str, Any]] | None = None,
    coverage: list[dict[str, Any]],
    plausible_rows: list[dict[str, Any]] | None = None,
    today: date | None = None,
    limit: int | None = 5,
) -> list[dict[str, Any]]:
    """Combine and dynamically score existing actionable signals."""
    experiment_websites = {
        str(row.get("website", "")) for row in (active_experiments or [])
    }
    combined_items = build_combined_traffic_tasks(
        seo_sites=seo_sites,
        plausible_rows=plausible_rows or [],
        today=today,
    )
    combined_websites = {item["website"] for item in combined_items}
    items: list[dict[str, Any]] = list(combined_items)
    for component, health in system_status.items():
        if not health.get("is_ok"):
            items.append(_action(
                "system_error",
                f"{component.replace('_', ' ').title()} melder fejl.",
                "", "pages/12_Systemstatus.py", "Åbn Systemstatus",
            ))
    for row in seo_sites:
        trend = str(row.get("trend", "")).lower()
        if trend in {"critical", "declining"}:
            critical = trend == "critical"
            item = _action(
                "seo_health",
                (
                    "SEO Health viser et markant fald."
                    if critical else "SEO Health er faldende."
                ),
                str(row.get("website", "")),
                "pages/9_SEO.py", "Åbn SEO",
            )
            item.update({
                "click_change": row.get("click_change"),
                "ctr_change": row.get("ctr_change"),
                "position_change": row.get("position_change"),
                "seo_health_trend": trend,
            })
            items.append(item)
    for row in experiments:
        items.append(_action(
            "experiment_ready", "SEO-eksperiment er klar til evaluering.",
            str(row.get("website", "")),
            "pages/13_Eksperimenter.py", "Åbn Eksperimenter",
        ))
    for website, change in _plausible_traffic_declines(
        plausible_rows or [], today=today
    ):
        if website in combined_websites:
            continue
        item = _action(
            "plausible_decline", "Plausible-trafikken er faldet.", website,
            "pages/1_Website_Profile.py", "Åbn Website Profile",
        )
        item["change"] = f"{change:.1f} %".replace(".", ",")
        item["plausible_change"] = change
        items.append(item)
    for row in coverage:
        website = str(row.get("website", ""))
        if not row.get("latest_search_console"):
            items.append(_action(
                "missing_search_console", "Search Console-data mangler.",
                website,
                "pages/9_SEO.py", "Åbn SEO",
            ))
        if not row.get("latest_plausible"):
            items.append(_action(
                "missing_plausible", "Plausible-data mangler.", website,
                "app.py", "Opdater data",
            ))
    for row in project_tasks:
        score = int(row.get("priority_score") or 0)
        title = str(row.get("task", "Ny opgave"))
        target = (
            "pages/14_Title_Optimering.py"
            if "title" in title.lower()
            else "pages/8_Opgaver.py"
        )
        item = _action(
            "project_task", title, str(row.get("website", "")),
            target, "Åbn opgave",
        )
        item["source_priority_score"] = score
        items.append(item)
    for item in items:
        item["has_active_experiment"] = (
            item["website"] in experiment_websites
        )
    scored = [score_priority_item(item) for item in items]
    scored.sort(key=stable_priority_key)
    return scored if limit is None else scored[:limit]


def build_combined_traffic_tasks(
    *,
    seo_sites: list[dict[str, Any]],
    plausible_rows: list[dict[str, Any]],
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Combine qualified Plausible declines with negative Search Console."""
    seo_by_website = {
        str(row.get("website", "")): row for row in seo_sites
    }
    tasks = []
    for website, plausible_change in _plausible_traffic_declines(
        plausible_rows, today=today
    ):
        seo = seo_by_website.get(website)
        if not seo:
            continue
        click_change = _optional_float(seo.get("click_change"))
        position_change = _optional_float(seo.get("position_change"))
        thresholds = PRIORITY_CONFIG["thresholds"]
        clicks_declined = (
            click_change is not None
            and click_change
            < thresholds["search_console_click_decline_pct"]
        )
        position_declined = (
            position_change is not None
            and position_change > thresholds["position_worsening"]
        )
        if not (clicks_declined or position_declined):
            continue
        critical = clicks_declined
        search_change = _search_console_change(
            click_change, position_change,
            include_position=position_declined,
        )
        item = _action(
            "combined_traffic_decline",
            "Både SEO-trafik og samlet trafik er faldet.",
            website,
            "pages/1_Website_Profile.py",
            "Åbn Website Profile",
        )
        item.update({
            "change": f"{plausible_change:.1f} %".replace(".", ","),
            "plausible_change": plausible_change,
            "click_change": click_change,
            "ctr_change": _optional_float(seo.get("ctr_change")),
            "position_change": position_change,
            "seo_health_trend": str(seo.get("trend", "")).lower(),
            "search_console_change": search_change,
            "explanation": (
                "Plausible viser et markant trafikfald, samtidig med at "
                f"Search Console viser {search_change.lower()}."
            ),
            "task_type": "combined_traffic_decline",
        })
        tasks.append(item)
    scored = [score_priority_item(item) for item in tasks]
    return sorted(scored, key=stable_priority_key)


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _search_console_change(
    click_change: float | None,
    position_change: float | None,
    *,
    include_position: bool,
) -> str:
    parts = []
    if click_change is not None and click_change < 0:
        parts.append(
            f"klik {click_change:+.1f} %".replace(".", ",")
        )
    if include_position and position_change is not None:
        parts.append(
            f"placering {position_change:+.1f}".replace(".", ",")
        )
    return " og ".join(parts)


def _plausible_traffic_declines(
    rows: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> list[tuple[str, float]]:
    """Return active websites with a complete seven-day decline of 20%."""
    yesterday = (today or date.today()) - timedelta(days=1)
    by_website: dict[str, dict[date, int]] = {}
    for row in rows:
        try:
            website = str(row["website"])
            metric_date = date.fromisoformat(str(row["metric_date"])[:10])
            visitors = int(row["visitors"])
        except (KeyError, TypeError, ValueError):
            continue
        by_website.setdefault(website, {})[metric_date] = visitors

    current_dates = [
        yesterday - timedelta(days=offset) for offset in range(7)
    ]
    previous_dates = [
        yesterday - timedelta(days=offset) for offset in range(7, 14)
    ]
    declines = []
    for website, metrics in by_website.items():
        if not all(item in metrics for item in current_dates + previous_dates):
            continue
        current = sum(metrics[item] for item in current_dates)
        previous = sum(metrics[item] for item in previous_dates)
        thresholds = PRIORITY_CONFIG["thresholds"]
        if previous < thresholds["plausible_previous_visitors"]:
            continue
        change = (current - previous) / previous * 100
        if change <= -thresholds["plausible_decline_pct"]:
            declines.append((website, change))
    return sorted(declines)


def _action(
    task_type: str,
    description: str,
    website: str,
    target: str,
    link_label: str,
) -> dict[str, Any]:
    normalized_website = website or "—"
    task_key = "|".join((
        task_type, normalized_website, description, target
    ))
    return {
        "task_key": task_key,
        "task_type": task_type,
        "description": description,
        "website": normalized_website,
        "target": target,
        "link_label": link_label,
    }


def _safe(function: Callable[[], T], fallback: T) -> T:
    try:
        return function()
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        return fallback
