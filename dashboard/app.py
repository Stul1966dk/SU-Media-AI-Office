"""Read-only Streamlit dashboard for SU Media AI Office."""

import sys
import inspect
import importlib
import importlib.util
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
    render_next_step,
    render_sidebar,
    render_page_link,
    render_status,
    render_table,
)
from dashboard.components.website_selector import get_selected_website_id
from dashboard.components.startup_sync import render_startup_sync_status
from core.system_health import check_runtime_services
from core.data_refresh_service import DataRefreshService
from core.refresh_status import (
    canonical_status, result_status, status_label,
)


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
def _runtime_health(_database: Any) -> dict[str, dict[str, Any]]:
    """Run external/runtime checks at most once every five minutes."""
    parameters = inspect.signature(check_runtime_services).parameters
    if "database" in parameters:
        return check_runtime_services(
            project_root=PROJECT_ROOT, database=_database
        )
    # A Streamlit hot reload can temporarily retain the pre-Sprint 8
    # function object. Keep the Dashboard usable until the process restarts.
    return check_runtime_services(project_root=PROJECT_ROOT)


def main() -> None:
    """Open the daily workflow as the application's true starting point."""
    import dashboard.components.ui as ui_module

    importlib.reload(ui_module)
    daily_path = PROJECT_ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
    spec = importlib.util.spec_from_file_location(
        "dashboard_daily_start", daily_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Siden I dag kunne ikke indlæses.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


def render_portfolio() -> None:
    """Render the complete portfolio dashboard from database-backed sections."""
    st.set_page_config(
        page_title="Portefølje",
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
        _apply_hot_reload_compatibility(database)
        for component, health in _runtime_health(database).items():
            database.set_system_health(component, health)
        data = load_dashboard_data(
            database,
            seo_trend=selected_trend,
            now=now,
        )
    finally:
        database.close()

    st.title("Portefølje")
    render_help_panel(
        purpose="Giv et samlet overblik over AI Office og de vigtigste datakilder.",
        requirements="Den lokale database og de services, du ønsker at bruge.",
        actions="Se systemstatus og fortsæt til det anbefalede næste trin.",
        limitations=(
            "Når automatisk synkronisering er aktiveret under Indstillinger, "
            "opdaterer forsiden data én gang ved starten af app-sessionen. "
            "Scanninger og analyser startes fortsat kun manuelt."
        ),
    )
    st.caption(format_datetime(now))
    render_next_step(
        text="Gå til I dag for at arbejde videre med den vigtigste opgave.",
        path="app.py",
        label="Fortsæt til I dag",
    )
    _render_overview(data)
    _render_economy(data)
    _render_seo_health(data, selected_trend)
    with st.expander("Se øvrige prioriterede signaler"):
        _render_priority_tasks(data)
    with st.expander("Se dataopdatering og teknisk status"):
        st.subheader("Synkronisering ved app-start")
        render_startup_sync_status()
        _render_data_refresh()
        _render_system_status(data)
        _render_ai_status(data)
        _render_events(data)


def _apply_hot_reload_compatibility(database: Any) -> None:
    """Add harmless read shims when Streamlit retained an older DB class."""
    database_class = type(database)
    if (
        "get_traffic_recommendation_decisions"
        not in vars(database_class)
    ):
        database.get_traffic_recommendation_decisions = lambda: []


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
    aggregate_status = result_status(result)
    if aggregate_status == "error":
        st.error("Dataopdateringen fejlede")
    elif aggregate_status == "warning":
        st.warning("Dataopdateringen er gennemført med advarsler")
    else:
        st.success("Dataopdateringen er gennemført")
    st.write(
        f"**Start:** {format_datetime(result['started_at'])}  \n"
        f"**Slut:** {format_datetime(result['completed_at'])}  \n"
        f"**Varighed:** {result['duration_seconds']:.1f} sek.  \n"
        f"**Gennemførte trin:** {result['completed_steps']}  \n"
        f"**Trin med advarsler:** {result.get('warning_steps', 0)}  \n"
        f"**Trin med fejl:** {result['failed_steps']}  \n"
        f"**Oversprungne trin:** {result.get('skipped_steps', 0)}"
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
    plausible = _refresh_step(result, "Plausible")
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
    if plausible:
        st.write(
            f"**Plausible:** "
            f"{_refresh_status_label(plausible.get('status', ''))}"
        )
        attempted, updated, datapoints = st.columns(3)
        attempted.metric(
            "Websites forsøgt", plausible.get("websites_attempted", 0)
        )
        updated.metric(
            "Websites opdateret", plausible.get("websites_updated", 0)
        )
        datapoints.metric(
            "Datapunkter gemt", plausible.get("datapoints_saved", 0)
        )
        errors = plausible.get("errors") or []
        if errors:
            with st.expander("Plausible-fejl pr. website"):
                for error in errors:
                    st.write(
                        f"- **{error.get('website', 'Ukendt')}:** "
                        f"{error.get('message', 'Ukendt fejl')}"
                    )
    selected = st.session_state.get("selected_website_id")
    if selected:
        database = open_database()
        try:
            analysis = database.get_latest_analysis(website_id=selected)
        finally:
            database.close()
        if analysis:
            st.info(
                f"Data og analyse for {selected} er klar. Fortsæt på I dag "
                "for at se den prioriterede opgave."
            )
        else:
            st.info(
                f"Data for {selected} er opdateret. AI-analyse er et "
                "valgfrit værktøj; næste opgave findes på I dag."
            )
        render_page_link("app.py", "Fortsæt til I dag")


def _refresh_step(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(
        (step for step in result["steps"] if step["step"] == name), {}
    )


def _refresh_status_label(status: str) -> str:
    if status == "running":
        return "Kører"
    return status_label(canonical_status({"status": status}))


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
    rows = data.economy.get("month_sales_rows", [])
    with st.expander("Vis beregning"):
        if not rows:
            st.info("Ingen Partner Ads-salg i den aktuelle måned.")
            return
        render_table(
            [
                {
                    "dato": row["dato"].strftime("%d.%m.%Y"),
                    "website": row["website"],
                    "reference": row["reference"],
                    "provision": row["provision"],
                }
                for row in rows
            ],
            columns={
                "dato": "Dato",
                "website": "Website",
                "reference": "Ordre/reference",
                "provision": "Provision i DKK",
            },
        )
        st.write(f"**Antal salg:** {len(rows)}")
        st.write(
            "**Samlet provision:** "
            f"{_currency(data.economy['month_commission'])}"
        )


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
            width="stretch",
        ):
            st.session_state["seo_trend"] = (
                None if selected_trend == trend else trend
            )
            st.rerun()
    if selected_trend:
        st.caption(f"Filter: {selected_trend.capitalize()}")
    st.dataframe(
        [
            {
                "Website": row["website"],
                "SEO-score": round(float(row["score"]), 1),
                "Trend": str(row["trend"]).capitalize(),
                "Klikændring": (
                    round(float(row["click_change"]), 1)
                    if row.get("click_change") is not None else None
                ),
                "Placeringsændring": (
                    round(float(row["position_change"]), 1)
                    if row.get("position_change") is not None else None
                ),
            }
            for row in data.seo_sites
        ],
        column_config={
            "SEO-score": st.column_config.NumberColumn(
                "SEO-score",
                help=(
                    "Samlet 0–100-score baseret på ændringer i klik, "
                    "visninger, CTR og gennemsnitlig placering."
                ),
                format="%.1f",
            ),
            "Trend": st.column_config.TextColumn(
                "Trend",
                help=(
                    "Growing: mindst 70. Stable: 45–69,9. "
                    "Declining: 25–44,9. Critical: under 25."
                ),
            ),
            "Klikændring": st.column_config.NumberColumn(
                "Klikændring %",
                help=(
                    "Procentvis ændring i klik i de seneste 28 dage "
                    "sammenlignet med de foregående 28 dage."
                ),
                format="%.1f",
            ),
            "Placeringsændring": st.column_config.NumberColumn(
                "Placeringsændring",
                help=(
                    "Forskel i vægtet gennemsnitsplacering. Negativ er "
                    "en forbedring; positiv er en forværring."
                ),
                format="%.1f",
            ),
        },
        width="stretch",
        hide_index=True,
    )


def _render_priority_tasks(data: DashboardData) -> None:
    st.subheader("Vigtigste opgaver")
    if not data.priority_tasks:
        st.info("Ingen højprioriterede opgaver fundet.")
        return
    for item in data.priority_tasks:
        priority, description, website, change, link = st.columns(
            [1.4, 3.4, 1.8, 1.3, 2.1], vertical_alignment="center"
        )
        priority.markdown(f"**{item['priority']}**")
        description.write(item["description"])
        website.write(item["website"])
        change.write(item.get("change", "—"))
        with link:
            render_page_link(item["target"], item["link_label"])


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
