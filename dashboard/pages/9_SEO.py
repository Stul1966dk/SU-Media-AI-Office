"""Website-scoped SEO dashboard and explicit Search Console import."""

import importlib
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
from core.current_diagnosis_reader import read_latest_diagnosis
from core.priority_scoring import score_priority_item
import core.traffic_recommendations as traffic_recommendations_module
from core.traffic_recommendation_store import get_decision
from dashboard.components.database import open_database
from dashboard.components.errors import safe_error_detail
from dashboard.components.formatting import format_date
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import (
    load_styles, render_next_step, render_page_link, render_sidebar,
    render_table,
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
SEO_TABS = [
    "Oversigt", "Årsagsanalyse", "Historik", "Top sider", "Top søgeord",
    "Muligheder", "AI analyse", "Rå data",
]


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
    render_next_step(
        text=(
            "Brug SEO til at undersøge datagrundlaget. Når du er klar til at "
            "handle, fortsætter du altid på I dag."
        ),
        path="app.py",
        label="Gå til I dag",
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
        search_diagnosis = _latest_diagnosis(
            database, website_id, kind="search"
        )
        plausible_diagnosis = _latest_diagnosis(
            database, website_id, kind="plausible"
        )
        traffic_recommendation = _current_traffic_recommendation(
            search_diagnosis, plausible_diagnosis
        )
        recommendation_decision = (
            get_decision(database, traffic_recommendation["task_key"])
            if traffic_recommendation else None
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
    requested_tab = st.session_state.pop("seo_requested_tab", "Oversigt")
    tabs = st.tabs(
        SEO_TABS,
        default=requested_tab if requested_tab in SEO_TABS else "Oversigt",
    )
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
        _render_search_console_diagnosis(search_diagnosis)
        st.divider()
        _render_plausible_diagnosis(plausible_diagnosis)
        st.divider()
        _render_traffic_recommendation(
            traffic_recommendation, recommendation_decision
        )
    with tabs[2]:
        _render_history(current_rows, health)
    with tabs[3]:
        selected_page = _render_dimension_table(
            page_comparisons, "page_url", "side"
        )
        if selected_page:
            st.subheader("Søgeord for den valgte side")
            _render_dimension_table([
                row for row in page_query_comparisons
                if row.get("page_url") == selected_page
            ], "query", "søgeord", filters=False)
    with tabs[4]:
        _render_dimension_table(query_comparisons, "query", "søgeord")
    with tabs[5]:
        _render_concrete_opportunities(page_comparisons, query_comparisons)
    with tabs[6]:
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
    with tabs[7]:
        _render_raw_data(current_rows)


def _current_traffic_recommendation(
    search_diagnosis: dict[str, Any] | None,
    plausible_diagnosis: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build the current concrete plan instead of reading a stale snapshot."""
    if not search_diagnosis or not plausible_diagnosis:
        return None
    current_module = importlib.reload(traffic_recommendations_module)
    recommendations = current_module.build_traffic_recommendations(
        [search_diagnosis], [plausible_diagnosis]
    )
    if not recommendations:
        return None
    item = recommendations[0]
    item = {
        "task_key": "|".join((
            str(item["task_type"]),
            str(item["website"]),
            str(item["description"]),
            "pages/9_SEO.py",
        )),
        "target": "pages/9_SEO.py",
        "link_label": "Åbn årsagsanalyse",
        **item,
    }
    return score_priority_item(item)


def _latest_diagnosis(
    database: Any,
    website_id: str,
    *,
    kind: str,
) -> dict[str, Any] | None:
    """Read the current diagnosis across hot-reloaded Database versions."""
    return read_latest_diagnosis(database, website_id, kind=kind)


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


def _render_search_console_diagnosis(
    diagnosis: dict[str, Any] | None,
) -> None:
    """Render the latest persisted, evidence-only traffic diagnosis."""
    st.subheader("Dokumenteret årsag til trafikfald")
    if not diagnosis:
        st.info(
            "Der er endnu ingen gemt årsagsanalyse. Kør Opdater alle data, "
            "så de seneste to 28-dages perioder bliver analyseret."
        )
        return
    status = diagnosis.get("status")
    if status == "missing_periods":
        st.warning("Der mangler to sammenlignelige 28-dages perioder.")
        return
    previous = int(diagnosis.get("previous_clicks", 0))
    current = int(diagnosis.get("current_clicks", 0))
    loss = int(diagnosis.get("click_loss", 0))
    for column, (label, value) in zip(
        st.columns(4),
        (
            ("Klik før", previous),
            ("Klik nu", current),
            ("Dokumenteret kliktab", loss),
            (
                "Forklaret af viste sider",
                f"{float(diagnosis.get('explained_loss_share', 0)):.1f} %",
            ),
        ),
    ):
        column.metric(label, value)
    st.caption(
        f"Periode {diagnosis.get('period_start')}–"
        f"{diagnosis.get('period_end')} sammenlignet med "
        f"{diagnosis.get('previous_period_start')}–"
        f"{diagnosis.get('previous_period_end')}."
    )
    if status == "insufficient_data":
        st.warning(str(diagnosis.get("reason", "Datagrundlaget er for lille.")))
        return
    if status == "no_decline":
        st.success("Det samlede antal organiske klik er ikke faldet.")
        return
    if status == "minor_decline":
        st.info(str(diagnosis.get(
            "reason", "Faldet er under den fastsatte støjgrænse."
        )))
        return
    loss_pages = diagnosis.get("loss_pages") or []
    if not loss_pages:
        st.info(str(diagnosis.get("reason", "Ingen tydelig sideårsag fundet.")))
        return
    st.write(
        "Årsagerne nedenfor er klassificeret ud fra målte ændringer i "
        "placering, CTR og visninger – ikke ud fra en AI-vurdering."
    )
    st.dataframe(
        [
            {
                "Nr.": index,
                "Side": page["page_url"],
                "Klik før": page["previous_clicks"],
                "Klik nu": page["current_clicks"],
                "Kliktab": page["click_loss"],
                "Målt signal": page["cause"],
                "Placering": (
                    f"{page['previous_position']:.1f} → "
                    f"{page['current_position']:.1f}"
                ),
                "CTR": (
                    f"{page['previous_ctr'] * 100:.1f} % → "
                    f"{page['current_ctr'] * 100:.1f} %"
                ),
                "Berørte søgeord": ", ".join(
                    f"{item['query']} (−{item['click_loss']})"
                    for item in page.get("queries", [])
                ) or "Ingen tydeligt faldende søgeord",
            }
            for index, page in enumerate(loss_pages, start=1)
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "Side": st.column_config.LinkColumn("Side"),
        },
    )


def _render_plausible_diagnosis(
    diagnosis: dict[str, Any] | None,
) -> None:
    """Render the latest persisted Plausible traffic comparison."""
    st.subheader("Plausible-trafikudvikling")
    if not diagnosis:
        st.info(
            "Der er endnu ingen gemt Plausible-analyse. Aktivér Plausible "
            "for websitet og kør Opdater alle data."
        )
        return
    status = str(diagnosis.get("status", ""))
    previous = int(diagnosis.get("previous_visitors", 0))
    current = int(diagnosis.get("current_visitors", 0))
    change = int(diagnosis.get("visitor_change", 0))
    percent = diagnosis.get("visitor_change_percent")
    for column, (label, value) in zip(
        st.columns(3),
        (
            ("Besøgende før", previous),
            ("Besøgende nu", current),
            (
                "Ændring",
                f"{change:+d} ({float(percent):+.1f} %)"
                if percent is not None else f"{change:+d}",
            ),
        ),
    ):
        column.metric(label, value)
    if diagnosis.get("period_start"):
        st.caption(
            f"Periode {diagnosis.get('period_start')}–"
            f"{diagnosis.get('period_end')} sammenlignet med "
            f"{diagnosis.get('previous_period_start')}–"
            f"{diagnosis.get('previous_period_end')}."
        )
    reason = str(diagnosis.get("reason", ""))
    if status == "missing_periods":
        st.warning(reason)
    elif status == "insufficient_data":
        st.warning(reason)
    elif status == "significant_decline":
        st.error(reason)
    elif status == "minor_decline":
        st.info(reason)
    elif status == "growth":
        st.success(reason)
    else:
        st.success(reason or "Besøgstallet er stabilt.")
    st.caption(
        "Klassifikationen er beregnet ud fra gemte besøgstal og bruger ikke AI."
    )

def _render_traffic_recommendation(
    recommendation: dict[str, Any] | None,
    decision: dict[str, Any] | None,
) -> None:
    """Show the approval-gated path from recommendation to experiment."""
    st.subheader("Samlet opgaveanbefaling")
    if not recommendation:
        st.info(
            "Der er ingen kvalificeret anbefaling fra begge datakilder endnu."
        )
        return
    st.write(
        f"**Anbefalet handling:** "
        f"{recommendation.get('recommended_action') or recommendation['description']}"
    )
    for index, step in enumerate(
        recommendation.get("action_steps") or [], start=1
    ):
        st.write(f"{index}. {step}")
    if recommendation.get("completion_criterion"):
        st.write(f"**Færdig når:** {recommendation['completion_criterion']}")
    if recommendation.get("measurement_method"):
        st.write(f"**Måling:** {recommendation['measurement_method']}")
    st.markdown("**Datagrundlag**")
    st.write(str(recommendation.get("explanation", "")))
    columns = st.columns(3)
    columns[0].metric("Prioritet", recommendation.get("priority", "Ukendt"))
    columns[1].metric(
        "Search Console",
        f"{float(recommendation.get('click_change') or 0):+.1f} %",
    )
    columns[2].metric(
        "Plausible",
        f"{float(recommendation.get('plausible_change') or 0):+.1f} %",
    )
    if recommendation.get("target_url"):
        st.link_button(
            "Åbn berørt side", str(recommendation["target_url"])
        )
    st.caption(
        "Denne side forklarer datagrundlaget. Beslutninger og udførelse "
        "samles på I dag."
    )
    if decision:
        labels = {
            "draft": "Opgavekladde gemt",
            "approved": "Opgavekladden er godkendt og afventer implementering",
            "experiment_running": "Ændringen er registreret og under måling",
            "snoozed": "Anbefaling udsat",
            "rejected": "Anbefaling afvist",
        }
        message = labels.get(decision["status"], decision["status"])
        if decision["status"] == "snoozed":
            message += f" til {decision.get('snoozed_until')}"
        if decision["status"] == "experiment_running":
            st.success(message)
            experiment_id = (decision.get("evidence") or {}).get(
                "experiment_id"
            )
            due = (decision.get("evidence") or {}).get(
                "planned_evaluation_date"
            )
            st.write(
                f"Eksperiment #{experiment_id} evalueres tidligst {due}."
            )
            st.page_link(
                "pages/13_Eksperimenter.py",
                label="Følg eksperimentet",
                icon="🧪",
            )
            return
        st.info(message)
    render_next_step(
        text=(
            "Gå til I dag for at godkende, redigere, udsætte eller udføre "
            "den anbefalede opgave."
        ),
        path="app.py",
        label="Fortsæt opgaven på I dag",
    )


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
