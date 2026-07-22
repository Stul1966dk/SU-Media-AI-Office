"""Read-only Streamlit dashboard for SU Media AI Office."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.data import DashboardData, load_dashboard_data
from dashboard.components.database import open_database
from dashboard.components.errors import safe_error_detail
from dashboard.components.help_panel import render_help_panel
from dashboard.components.formatting import (
    format_ai_assessment, format_currency, format_datetime,
)
from dashboard.components.ui import (
    load_styles,
    render_sidebar,
    render_page_link,
    render_status,
    render_table,
)
from dashboard.components.website_selector import get_selected_website_id
from core.system_health import check_runtime_services
from core.data_refresh_service import DataRefreshService


DASHBOARD_WIDGET_COUNT = 28
STATUS_LABELS = {
    "database": "Database",
    "partner_ads": "Partner Ads",
    "search_console": "Search Console",
    "agent_orchestrator": "Agent Orchestrator",
    "knowledge_engine": "Knowledge Engine",
    "openai": "OpenAI",
}
SEO_TRENDS = ("growing", "stable", "declining", "critical")


@st.cache_data(ttl=300, show_spinner=False)
def _runtime_health() -> dict[str, dict[str, Any]]:
    """Run external/runtime checks at most once every five minutes."""
    return check_runtime_services(project_root=PROJECT_ROOT)


def main() -> None:
    """Render the complete dashboard from database-backed sections."""
    st.set_page_config(
        page_title="Dashboard",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    now = datetime.now().astimezone()
    selected_trend = st.session_state.get("seo_trend")
    database = open_database()
    try:
        for component, health in _runtime_health().items():
            database.set_system_health(component, health)
        data = load_dashboard_data(
            database,
            seo_trend=selected_trend,
            now=now,
        )
    finally:
        database.close()

    st.title("Dashboard")
    render_help_panel(
        purpose="Giv et samlet overblik over AI Office og de vigtigste datakilder.",
        requirements="Den lokale database og de services, du ønsker at bruge.",
        actions="Se systemstatus og fortsæt til det anbefalede næste trin.",
        limitations="Forsiden starter ikke scanninger eller analyser automatisk.",
    )
    st.caption(format_datetime(now))
    _render_data_refresh()
    _render_system_status(data)
    _render_ai_status(data)
    _render_overview(data)
    _render_getting_started(data)
    _render_economy(data)
    _render_seo_health(data, selected_trend)
    _render_priority_tasks(data)
    _render_recovery(data)
    _render_sales(data)
    _render_events(data)


def _render_data_refresh() -> None:
    st.subheader("Opdater alle data")
    st.caption(
        "Opdaterer Registry, Partner Ads, Search Console, SEO History, "
        "Website Intelligence og systemstatus. Discovery og Content Explorer "
        "køres fortsat manuelt."
    )
    selected_website = get_selected_website_id()
    scope = st.radio(
        "Omfang", ["Kun aktivt website", "Alle aktive websites"],
        horizontal=True, key="refresh_scope",
    )
    if st.button("Opdater alle data", type="primary"):
        database = open_database()
        bar = st.progress(0, text="Forbereder opdatering…")
        messages = st.empty()
        statuses: dict[str, str] = {}

        def progress(step: str, status: str, _result: dict[str, Any]) -> None:
            statuses[step] = status
            done = sum(value != "running" for value in statuses.values())
            bar.progress(
                min(
                    100,
                    round(done / len(DataRefreshService.STEPS) * 100),
                ),
                text=f"{step}: {_refresh_status_label(status)}",
            )
            messages.markdown("\n".join(
                f"- **{name}:** {_refresh_status_label(value)}"
                for name, value in statuses.items()
            ))

        try:
            result = DataRefreshService(database).refresh_all(
                progress,
                website_ids=(
                    [selected_website]
                    if scope == "Kun aktivt website" and selected_website
                    else None
                ),
            )
            st.session_state["data_refresh_result"] = result
        except Exception as error:
            st.session_state["data_refresh_error"] = {
                "message": safe_error_detail(error),
                "type": type(error).__name__,
            }
        finally:
            database.close()
        st.rerun()
    error = st.session_state.pop("data_refresh_error", None)
    if error:
        st.error("Dataopdateringen kunne ikke startes: " + error["message"])
        with st.expander("Tekniske detaljer"):
            st.code(error["type"])
    result = st.session_state.get("data_refresh_result")
    if not result:
        database = open_database()
        try:
            result = database.get_last_data_refresh_result()
        finally:
            database.close()
    if not result:
        return
    st.success("Dataopdateringen er afsluttet")
    st.write(
        f"**Start:** {format_datetime(result['started_at'])}  \n"
        f"**Slut:** {format_datetime(result['completed_at'])}  \n"
        f"**Varighed:** {result['duration_seconds']:.1f} sek.  \n"
        f"**Gennemførte trin:** {result['completed_steps']}  \n"
        f"**Trin med fejl:** {result['failed_steps']}"
    )
    for step in result["steps"]:
        st.write(
            f"**{step['step']}:** {_refresh_status_label(step['status'])}"
            + (f" — {step.get('reason')}" if step.get("reason") else "")
        )
    partner = _refresh_step(result, "Partner Ads")
    properties = _refresh_step(result, "Search Console-properties")
    daily = _refresh_step(result, "Search Console-dagstal")
    dimensions = _refresh_step(
        result, "Search Console-sider og søgeord"
    )
    seo = _refresh_step(result, "SEO History")
    intelligence = _refresh_step(result, "Website Intelligence")
    for column, (label, value) in zip(st.columns(5), (
        ("Nye Partner Ads-salg", partner.get("new", 0)),
        ("Properties behandlet", properties.get("total", 0)),
        ("SC-rækker ændret", daily.get("rows_created", 0)
         + daily.get("rows_updated", 0)
         + dimensions.get("rows_created", 0)
         + dimensions.get("rows_updated", 0)),
        ("Websites med SEO Health", seo.get("websites_updated", 0)),
        ("Websiteprofiler opdateret", intelligence.get("profiles_updated", 0)
         + intelligence.get("profiles_created", 0)),
    )):
        column.metric(label, value)
    selected = st.session_state.get("selected_website_id")
    if selected:
        database = open_database()
        try:
            analysis = database.get_latest_analysis(website_id=selected)
        finally:
            database.close()
        if analysis:
            st.info("Analysen er klar. Generér Executive Briefing.")
            render_page_link(
                "pages/3_Executive_Briefing.py",
                f"Generér Executive Briefing for {selected}",
            )
        else:
            st.info(f"Data er opdateret. Kør AI Analyst for {selected}.")
            render_page_link(
                "pages/6_AI_Analyst.py", f"Kør AI Analyst for {selected}"
            )


def _refresh_step(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(
        (step for step in result["steps"] if step["step"] == name), {}
    )


def _refresh_status_label(status: str) -> str:
    return {
        "running": "Kører", "completed": "Gennemført",
        "error": "Fejl", "skipped": "Ikke kørt",
    }.get(status, status)


def _render_system_status(data: DashboardData) -> None:
    st.subheader("Systemstatus")
    columns = st.columns(6)
    for column, (key, label) in zip(columns, STATUS_LABELS.items()):
        with column:
            health = data.system_status.get(key, {})
            render_status(
                label, bool(health.get("is_ok")),
                str(health.get("detail", "")),
                str(health.get("checked_at", "")),
            )


def _render_ai_status(data: DashboardData) -> None:
    st.subheader("AI Status")
    total, confidence, latest = st.columns(3)
    total.metric("Antal analyser", data.ai_status["total"])
    confidence.metric(
        "Gennemsnitlig AI-vurdering",
        format_ai_assessment(
            data.ai_status['average_confidence'], include_percent=True
        ),
    )
    latest.metric(
        "Seneste analyse",
        (
            format_datetime(data.ai_status["latest_analysis"])
            if data.ai_status["latest_analysis"] else "Ingen data."
        ),
    )


def _render_overview(data: DashboardData) -> None:
    st.subheader("Oversigt")
    labels = (
        ("Antal websites", "websites"),
        ("Aktive websites", "active_websites"),
        ("Monetized", "monetized"),
        ("Under udfasning", "phasing_out"),
        ("Aktive projekter", "active_projects"),
        ("Åbne opgaver", "open_tasks"),
    )
    for start in (0, 3):
        for column, (label, key) in zip(
            st.columns(3),
            labels[start : start + 3],
        ):
            column.metric(label, data.overview[key])


def _render_getting_started(data: DashboardData) -> None:
    st.subheader("Sådan kommer du i gang")
    if data.overview["websites"] == 0:
        message, target = "Registrér de første websites.", "pages/11_Websites.py"
    elif not data.seo_sites:
        message, target = "Hent Search Console-data.", "pages/9_SEO.py"
    elif data.ai_status["total"] == 0:
        message, target = "Kør AI Analyst for et website.", "pages/6_AI_Analyst.py"
    else:
        message, target = "Generér Executive Briefing.", "pages/3_Executive_Briefing.py"
    st.info(f"Næste anbefalede trin: {message}")
    render_page_link(target, message)


def _render_economy(data: DashboardData) -> None:
    st.subheader("Økonomi")
    values = (
        ("Dagens provision", _currency(data.economy["today_commission"])),
        ("Månedens provision", _currency(data.economy["month_commission"])),
        ("Salg i dag", data.economy["today_sales"]),
        ("Salg denne måned", data.economy["month_sales"]),
    )
    for column, (label, value) in zip(st.columns(4), values):
        column.metric(label, value)


def _render_seo_health(
    data: DashboardData,
    selected_trend: str | None,
) -> None:
    st.subheader("SEO Health")
    for column, trend in zip(st.columns(4), SEO_TRENDS):
        label = trend.capitalize()
        count = data.seo_counts.get(trend, 0)
        if column.button(
            f"{label}\n{count}",
            key=f"seo-filter-{trend}",
            type="primary" if selected_trend == trend else "secondary",
            use_container_width=True,
        ):
            st.session_state["seo_trend"] = (
                None if selected_trend == trend else trend
            )
            st.rerun()
    if selected_trend:
        st.caption(f"Filter: {selected_trend.capitalize()}")
    render_table(
        data.seo_sites,
        columns={
            "website": "Website",
            "score": "SEO-score",
            "trend": "Trend",
            "click_change": "Klikændring %",
            "position_change": "Placeringsændring",
        },
    )


def _render_priority_tasks(data: DashboardData) -> None:
    st.subheader("Vigtigste opgaver")
    render_table(
        data.priority_tasks,
        columns={
            "website": "Website",
            "project": "Projekt",
            "task": "Opgave",
            "assigned_agent": "Ansvarlig agent",
            "priority_score": "Prioritet",
            "estimated_minutes": "Estimeret tid",
            "status": "Status",
        },
    )


def _render_recovery(data: DashboardData) -> None:
    st.subheader("SEO Recovery")
    render_table(
        data.recovery_projects,
        columns={
            "website": "Website",
            "seo_score": "SEO-score",
            "trend": "Trend",
            "project": "Projekt",
            "status": "Status",
        },
    )


def _render_sales(data: DashboardData) -> None:
    st.subheader("Partner Ads")
    render_table(
        data.recent_sales,
        columns={
            "dato": "Dato",
            "website": "Website",
            "omsaetning": "Omsætning",
            "provision": "Provision",
        },
    )


def _render_events(data: DashboardData) -> None:
    st.subheader("Seneste agentaktivitet")
    render_table(
        data.recent_events,
        columns={
            "created_at": "Tidspunkt",
            "event_type": "Hændelse",
            "source": "Kilde",
            "website": "Website",
            "status": "Status",
        },
    )


def _currency(value: Any) -> str:
    return format_currency(value)


if __name__ == "__main__":
    main()
