"""Read-only Streamlit dashboard for SU Media AI Office."""

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.data import DashboardData, load_dashboard_data
from dashboard.components.database import open_database
from dashboard.components.ui import (
    load_styles,
    render_sidebar,
    render_status,
    render_table,
)


DASHBOARD_WIDGET_COUNT = 24
STATUS_LABELS = {
    "database": "Database",
    "partner_ads": "Partner Ads",
    "search_console": "Search Console",
    "agent_orchestrator": "Agent Orchestrator",
    "knowledge_engine": "Knowledge Engine",
}
SEO_TRENDS = ("growing", "stable", "declining", "critical")


def main() -> None:
    """Render the complete dashboard from database-backed sections."""
    st.set_page_config(
        page_title="SU Media AI Office",
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
        data = load_dashboard_data(
            database,
            seo_trend=selected_trend,
            now=now,
        )
    finally:
        database.close()

    st.title("SU Media AI Office")
    st.caption(now.strftime("%d-%m-%Y %H:%M:%S"))
    _render_system_status(data)
    _render_overview(data)
    _render_economy(data)
    _render_seo_health(data, selected_trend)
    _render_priority_tasks(data)
    _render_recovery(data)
    _render_sales(data)
    _render_events(data)


def _render_system_status(data: DashboardData) -> None:
    st.subheader("Systemstatus")
    columns = st.columns(5)
    for column, (key, label) in zip(columns, STATUS_LABELS.items()):
        with column:
            render_status(label, data.system_status.get(key, False))


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
    amount = Decimal(str(value))
    formatted = f"{amount:,.2f}".translate(
        str.maketrans({",": ".", ".": ","})
    )
    return f"{formatted} kr."


if __name__ == "__main__":
    main()
