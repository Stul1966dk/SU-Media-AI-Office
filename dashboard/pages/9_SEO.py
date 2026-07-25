"""Website-scoped SEO dashboard and explicit Search Console import."""

import sys
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.search_console_service import SearchConsoleService
from dashboard.components.database import open_database
from dashboard.components.errors import safe_error_detail
from dashboard.components.formatting import format_date
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import (
    load_styles, render_page_link, render_sidebar, render_table,
)
from dashboard.components.website_selector import (
    get_selected_website_id,
    set_selected_website,
)
from integrations.search_console import (
    SearchConsoleAuthenticationError,
)
from integrations.search_console_integration import SearchConsoleIntegration


PERIODS = {"7 dage": 7, "28 dage": 28, "90 dage": 90, "12 måneder": 365}


def build_service(database: Any) -> SearchConsoleService:
    return SearchConsoleIntegration(PROJECT_ROOT, database).search_service()


def run_search_console_import(
    service: SearchConsoleService, *, days: int = 35,
    website_ids: list[str] | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    report = progress or (lambda _value, _text: None)
    report(10, "Kontrollerer Search Console-forbindelsen…")
    properties = service.synchronize()
    report(35, f"{properties.matched} websites matchet. Henter søgedata…")
    metrics = service.sync_all_properties(
        days=days,
        website_ids=website_ids,
        force_full_refresh=True,
    )
    report(60, "Henter sider, søgeord og kombinationer…")
    dimensions = service.sync_dimensions(website_ids=website_ids)
    report(90, "Opdaterer dashboardets oversigter…")
    result = {
        **asdict(metrics), "properties_total": properties.total,
        "properties_matched": properties.matched,
        "websites_imported": metrics.properties_processed - metrics.properties_failed,
        "days_requested": days,
        "website_days_imported": metrics.rows_created + metrics.rows_updated,
        "page_rows": dimensions.page_rows,
        "query_rows": dimensions.query_rows,
        "page_query_rows": dimensions.page_query_rows,
    }
    report(100, "Importen er færdig.")
    return result


def main() -> None:
    st.set_page_config(page_title="SEO", page_icon="📈", layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("SEO")
    render_help_panel(
        purpose="Følg Search Console- og SEO-udviklingen for ét website.",
        requirements="Det valgte website skal have importerede Search Console-data.",
        actions="Skift periode, udforsk fanerne eller start en eksplicit import.",
        limitations="Sidevisning kalder ingen API'er og opretter ingen projekter.",
    )
    database = open_database()
    try:
        websites = [
            item["website"] for item in database.get_all_websites()
            if item["active"] and item["status"] not in
            {"phasing_out", "archived", "cancelled"}
        ]
        current = get_selected_website_id()
        website_id = st.selectbox(
            "Website", websites,
            index=websites.index(current) if current in websites else 0,
        ) if websites else None
        if website_id:
            set_selected_website(website_id)
        period_label = st.selectbox(
            "Periode", list(PERIODS), index=1
        )
        days = PERIODS[period_label]
        _render_import(database, website_id)
        if not website_id:
            st.info("Registrér et aktivt website, før SEO-data kan vises.")
            return
        end = date.today()
        start = end - timedelta(days=days - 1)
        previous_start = start - timedelta(days=days)
        rows = database.get_search_console_daily_metrics(
            website_id=website_id,
            start_date=previous_start.isoformat(),
            end_date=end.isoformat(),
        )
        current_rows = [x for x in rows if x["metric_date"] >= start.isoformat()]
        previous_rows = [x for x in rows if x["metric_date"] < start.isoformat()]
        health_period = f"{days}d" if days in {7, 28, 90} else "90d"
        health = database.get_seo_health_history(
            website_id=website_id, period=health_period
        )
        latest_health = health[0] if health else None
        analysis = database.get_latest_analysis(website_id=website_id)
        recovery = [
            item for item in database.get_active_seo_recovery_projects()
            if item.get("website") == website_id
        ]
        tasks = [
            item for item in database.get_task_records_for_project()
            if item["website_id"] == website_id and
            item["status"] not in {"completed", "cancelled"}
        ]
        profile = database.get_website(website_id)
        source = database.get_website_intelligence_source(website_id)
        service = build_service(database)
        page_comparisons = service.get_dimension_comparisons(website_id, "page")
        query_comparisons = service.get_dimension_comparisons(website_id, "query")
        page_query_comparisons = service.get_dimension_comparisons(
            website_id, "page_query"
        )
    finally:
        database.close()
    if not current_rows:
        st.info(
            f"{website_id} mangler Search Console-data for perioden. "
            "Klik Hent Search Console-data ovenfor."
        )
    current_kpi = _aggregate(current_rows)
    previous_kpi = _aggregate(previous_rows)
    tabs = st.tabs([
        "Oversigt", "Historik", "Top sider", "Top søgeord",
        "Muligheder", "AI analyse", "Rå data",
    ])
    with tabs[0]:
        _render_kpis(current_kpi, previous_kpi, latest_health)
        st.write(
            f"SEO Health er baseret på den seneste gemte {health_period}-analyse."
        )
        if analysis:
            st.write(f"**Seneste AI-anbefaling:** {analysis['recommended_action']}")
        else:
            st.info("Ingen AI-analyse endnu. Brug fanen AI analyse.")
        st.subheader("Aktive SEO Recovery-projekter")
        render_table(recovery, columns={
            "project": "Projekt", "status": "Status",
            "seo_score": "SEO Health", "trend": "Trend",
        })
        st.subheader("Åbne SEO-opgaver")
        render_table(tasks, columns={
            "title": "Opgave", "assigned_agent": "Agent",
            "estimated_minutes": "Minutter", "status": "Status",
        })
    with tabs[1]:
        _render_history(current_rows, health)
    with tabs[2]:
        selected_page = _render_dimension_table(
            page_comparisons, "page_url", "side"
        )
        if selected_page:
            st.subheader("Søgeord for den valgte side")
            _render_dimension_table([
                row for row in page_query_comparisons
                if row.get("page_url") == selected_page
            ], "query", "søgeord", filters=False)
    with tabs[3]:
        _render_dimension_table(query_comparisons, "query", "søgeord")
    with tabs[4]:
        _render_concrete_opportunities(page_comparisons, query_comparisons)
    with tabs[5]:
        if analysis:
            st.write(f"**Seneste analyse:** {analysis['summary']}")
            st.write(f"**Anbefaling:** {analysis['recommended_action']}")
        else:
            st.info("Der findes endnu ingen AI-analyse for dette website.")
        render_page_link(
            "pages/6_AI_Analyst.py",
            f"Kør ny analyse for {website_id}",
        )
        st.caption(
            "Analysen bruger websiteprofil, SEO Health, Search Console, "
            "salgshistorik, projekter, opgaver og virksomhedsregler."
        )
    with tabs[6]:
        _render_raw_data(current_rows)


def _render_import(database: Any, website_id: str | None) -> None:
    integration = SearchConsoleIntegration(PROJECT_ROOT, database)
    connection = integration.status(validate=False)
    previous = st.session_state.pop("search_console_import_result", None)
    error = st.session_state.pop("search_console_import_error", None)
    if previous:
        st.success(
            f"{previous['websites_imported']} websites og "
            f"{previous['website_days_imported']} website-dage importeret. "
            f"Sider: {previous.get('page_rows', 0)}, søgeord: "
            f"{previous.get('query_rows', 0)}, kombinationer: "
            f"{previous.get('page_query_rows', 0)}. "
            f"Fejl: {previous['properties_failed']}."
        )
    if error:
        if error["type"] == "SearchConsoleAuthenticationError":
            st.error(
                "Google Search Console-forbindelsen mangler eller er udløbet."
            )
            render_page_link(
                "pages/18_Integrationer.py",
                "Åbn Indstillinger → Integrationer",
            )
        else:
            st.error(error["message"])
        with st.expander("Tekniske detaljer"):
            st.code(error["type"])
    elif not connection["connected"] or connection["last_error"]:
        st.error(
            "Google Search Console-forbindelsen mangler eller er udløbet."
        )
        render_page_link(
            "pages/18_Integrationer.py",
            "Åbn Indstillinger → Integrationer",
        )
    scope = st.radio(
        "Omfang", ["Kun aktivt website", "Alle aktive websites"],
        horizontal=True, key="search_console_scope",
    )
    if st.button("Hent Search Console-data", type="primary"):
        bar = st.progress(0, text="Forbereder import…")
        try:
            result = run_search_console_import(
                build_service(database), days=35,
                website_ids=([website_id] if
                             scope == "Kun aktivt website" and website_id
                             else None),
                progress=lambda value, text: bar.progress(value, text=text),
            )
            database.set_system_status("search_console", True)
            st.session_state["search_console_import_result"] = result
        except SearchConsoleAuthenticationError as exc:
            integration.record_authentication_error(exc)
            st.session_state["search_console_import_error"] = {
                "message": "Google Search Console-forbindelsen skal fornyes.",
                "type": type(exc).__name__,
            }
        except Exception as exc:
            database.set_system_status("search_console", False)
            st.session_state["search_console_import_error"] = {
                "message": "Importen fejlede: " + safe_error_detail(exc),
                "type": type(exc).__name__,
            }
        st.rerun()


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, float]:
    clicks = sum(item["clicks"] for item in rows)
    impressions = sum(item["impressions"] for item in rows)
    weighted_position = sum(
        item["average_position"] * item["impressions"] for item in rows
    )
    return {
        "clicks": float(clicks), "impressions": float(impressions),
        "ctr": clicks / impressions if impressions else 0.0,
        "position": weighted_position / impressions if impressions else 0.0,
    }


def _render_dimension_table(
    rows: list[dict[str, Any]], key_field: str, label: str,
    *, filters: bool = True,
) -> str | None:
    """Render comparable page/query metrics and return a selected page."""
    if not rows:
        st.info(
            f"Ingen {label}-data fundet. Hent Search Console-data for at "
            "importere den seneste og foregående 28-dages periode."
        )
        return None
    filtered = rows
    if filters:
        choice = st.selectbox(
            "Filter", [
                "Vigtigste", "Største klikfald", "Største CTR-fald",
                "Størst vækst", "Høje visninger og lav CTR",
                "Placering 4 til 15", "Ingen klik trods visninger",
            ], key=f"filter_{key_field}",
        )
        if choice == "Største klikfald":
            filtered = sorted(rows, key=lambda item: item["click_change"])
        elif choice == "Største CTR-fald":
            filtered = sorted(rows, key=lambda item: item["ctr_change"])
        elif choice == "Størst vækst":
            filtered = sorted(
                rows, key=lambda item: item["click_change"], reverse=True
            )
        elif choice == "Høje visninger og lav CTR":
            filtered = sorted(
                [item for item in rows if item["current_ctr"] < .03],
                key=lambda item: item["current_impressions"], reverse=True,
            )
        elif choice == "Placering 4 til 15":
            filtered = [
                item for item in rows
                if 4 <= item["current_position"] <= 15
            ]
        elif choice == "Ingen klik trods visninger":
            filtered = [
                item for item in rows
                if item["current_clicks"] == 0
                and item["current_impressions"] > 0
            ]
    st.dataframe([{
        ("URL" if key_field == "page_url" else "Søgeord"):
            item.get(key_field, ""),
        "Klik (seneste)": item["current_clicks"],
        "Klik (før)": item["previous_clicks"],
        "Ændring i klik": item["click_change"],
        "Visninger": item["current_impressions"],
        "CTR": f"{item['current_ctr'] * 100:.2f}%",
        "Placering": round(item["current_position"], 1),
        "Trend": item["trend"],
    } for item in filtered[:250]], use_container_width=True, hide_index=True)
    if key_field == "page_url" and filtered:
        return st.selectbox(
            "Vis søgeord for side",
            [item["page_url"] for item in filtered[:250]],
        )
    return None


def _change(current: float, previous: float) -> float | None:
    return ((current - previous) / previous * 100) if previous else None


def _render_kpis(
    current: dict[str, float], previous: dict[str, float],
    health: dict[str, Any] | None,
) -> None:
    metrics = (
        ("Klik", f"{current['clicks']:,.0f}", _percent(_change(
            current["clicks"], previous["clicks"]
        ))),
        ("Visninger", f"{current['impressions']:,.0f}", _percent(_change(
            current["impressions"], previous["impressions"]
        ))),
        ("CTR", f"{current['ctr']*100:.2f}%",
         f"{(current['ctr']-previous['ctr'])*100:+.2f} procentpoint"),
        ("Gennemsnitlig placering", f"{current['position']:.2f}",
         f"{current['position']-previous['position']:+.2f} "
         + ("dårligere" if current["position"] > previous["position"] else "bedre")),
        ("SEO Health score", f"{float((health or {}).get('score', 0)):.1f}", ""),
        ("Trend", (health or {}).get("trend", "Ingen data"), ""),
    )
    for start in (0, 3):
        for column, (label, value, delta) in zip(
            st.columns(3), metrics[start:start + 3]
        ):
            column.metric(label, value, delta or None)


def _render_history(
    rows: list[dict[str, Any]], health: list[dict[str, Any]]
) -> None:
    if not rows:
        st.info("Historik oprettes, når Search Console-data er importeret.")
        return
    for label, field in (
        ("Klik", "clicks"), ("Visninger", "impressions"),
        ("CTR", "ctr"), ("Gennemsnitlig placering", "average_position"),
    ):
        st.write(f"**{label}**")
        st.line_chart({
            format_date(item["metric_date"], item["metric_date"]): item[field]
            for item in rows
        })
    st.write("**SEO Health score**")
    if health:
        st.line_chart({
            format_date(item["date"], item["date"]): item["score"]
            for item in health
        })
    else:
        st.info("SEO Health-historik er endnu ikke beregnet.")


def _render_opportunities(
    current: dict[str, float], previous: dict[str, float],
    website: dict[str, Any], source: dict[str, Any],
) -> None:
    opportunities = []
    ctr_change = current["ctr"] - previous["ctr"]
    position_change = current["position"] - previous["position"]
    if ctr_change < 0 and abs(position_change) < 1:
        opportunities.append((
            "Faldende CTR med stabil placering",
            f"CTR ændret {ctr_change*100:+.2f} procentpoint; placering "
            f"{position_change:+.2f}.",
            "Gennemgå title og meta description på vigtige sider.",
            90, "SEO Manager",
        ))
    if current["impressions"] > previous["impressions"] and (
        current["clicks"] <= previous["clicks"]
    ):
        opportunities.append((
            "Flere visninger uden flere klik",
            "Visninger stiger, men klik følger ikke med.",
            "Find sider med høje visninger og lav CTR.", 60, "SEO Manager",
        ))
    if _change(current["clicks"], previous["clicks"]) not in {None} and (
        _change(current["clicks"], previous["clicks"]) or 0
    ) < -10 and website.get("priority") == "high":
        opportunities.append((
            "Klikfald på website med høj prioritet",
            f"Klik ændret {_change(current['clicks'], previous['clicks']):.1f}%.",
            "Afgræns årsagen i Search Console-historikken.", 90, "AI Analyst",
        ))
    commission = float((source.get("partner_ads") or {}).get(
        "commission", 0
    ) or 0)
    if commission > 0 and current["clicks"] < previous["clicks"]:
        opportunities.append((
            "Historisk indtjening med faldende trafik",
            f"Gemte provisionsdata: {commission:.2f}.",
            "Prioritér SEO recovery på de kommercielle landingssider.",
            120, "SEO Manager",
        ))
    if not opportunities:
        st.info(
            "Ingen regelbaserede muligheder blev udløst af de tilgængelige data."
        )
    for problem, evidence, action, minutes, agent in opportunities:
        with st.container(border=True):
            st.write(f"**Problem eller mulighed:** {problem}")
            st.write(f"**Datagrundlag:** {evidence}")
            st.write(f"**Næste handling:** {action}")
            st.write(f"**Forventet tid:** {minutes} minutter")
            st.write(f"**Ansvarlig agent:** {agent}")


def _render_concrete_opportunities(
    pages: list[dict[str, Any]], queries: list[dict[str, Any]],
) -> None:
    """Show directly actionable opportunities backed by dimensional data."""
    opportunities: list[dict[str, Any]] = []
    for item in pages:
        position_change = (
            item["current_position"] - item["previous_position"]
        )
        if item["click_change"] < 0 and abs(position_change) < 1:
            opportunities.append({
                "title": "Side med klikfald og stabil placering",
                "target": item["page_url"],
                "evidence": (
                    f"Klik {item['previous_clicks']} → "
                    f"{item['current_clicks']}; placering "
                    f"{item['previous_position']:.1f} → "
                    f"{item['current_position']:.1f}."
                ),
                "cause": "Søgeresultatets title eller beskrivelse kan være svækket.",
                "action": f"Opdater title og metabeskrivelse på {item['page_url']}.",
                "minutes": 60, "agent": "SEO Manager",
                "measurement": "Sammenlign klik og CTR efter 28 dage.",
            })
        if item["current_impressions"] >= 100 and item["current_ctr"] < .03:
            opportunities.append({
                "title": "Side med mange visninger og lav CTR",
                "target": item["page_url"],
                "evidence": (
                    f"{item['current_impressions']} visninger og "
                    f"{item['current_ctr'] * 100:.2f}% CTR."
                ),
                "cause": "Søgeresultatet matcher muligvis ikke søgeintentionen.",
                "action": f"Skriv tre nye title-forslag til {item['page_url']}.",
                "minutes": 45, "agent": "SEO Manager",
                "measurement": "Sammenlign CTR efter 28 dage.",
            })
    for item in queries:
        if 4 <= item["current_position"] <= 15:
            opportunities.append({
                "title": "Søgeord tæt på side ét",
                "target": item["query"],
                "evidence": (
                    f"Placering {item['current_position']:.1f} og "
                    f"{item['current_impressions']} visninger."
                ),
                "cause": "Indholdet mangler muligvis dybde eller interne links.",
                "action": f"Styrk en relevant side for “{item['query']}”.",
                "minutes": 90, "agent": "Content Agent",
                "measurement": "Sammenlign placering og klik efter 28 dage.",
            })
    if not opportunities:
        st.info(
            "Ingen konkrete muligheder opfylder reglerne i de importerede "
            "side- og søgeordsdata."
        )
    for opportunity in opportunities[:20]:
        with st.container(border=True):
            st.write(f"**Mulighed:** {opportunity['title']}")
            st.write(f"**URL eller søgeord:** {opportunity['target']}")
            st.write(f"**Før- og eftertal:** {opportunity['evidence']}")
            st.write(f"**Sandsynlig årsag:** {opportunity['cause']}")
            st.write(f"**Anbefalet handling:** {opportunity['action']}")
            st.write(f"**Estimeret tid:** {opportunity['minutes']} minutter")
            st.write(f"**Ansvarlig agent:** {opportunity['agent']}")
            st.write(f"**Målemetode:** {opportunity['measurement']}")


def _render_raw_data(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.info("Rå data vises, når Search Console-data er importeret.")
        return
    dates = sorted(item["metric_date"] for item in rows)
    start, end = st.date_input(
        "Datofilter", value=(date.fromisoformat(dates[0]),
                             date.fromisoformat(dates[-1]))
    )
    sort = st.selectbox("Sortering", ["Nyeste først", "Ældste først"])
    limit = st.selectbox("Antal rækker", [25, 50, 100, 250], index=1)
    filtered = [
        item for item in rows
        if start.isoformat() <= item["metric_date"] <= end.isoformat()
    ]
    filtered.sort(
        key=lambda item: item["metric_date"],
        reverse=sort == "Nyeste først",
    )
    render_table(filtered[:limit], columns={
        "metric_date": "Dato", "website_id": "Website", "clicks": "Klik",
        "impressions": "Visninger", "ctr": "CTR",
        "average_position": "Placering",
    })


def _percent(value: float | None) -> str:
    return "Ingen sammenligning" if value is None else f"{value:+.1f} procent"


if __name__ == "__main__":
    main()
