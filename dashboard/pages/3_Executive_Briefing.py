"""Executive briefing generation and database-backed presentation."""

import sys
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.ai_analyst import AIAnalyst
from agents.ai_executive import AIExecutive, BriefingValidationError
from agents.decision_engine import DecisionEngine
from agents.project_manager import ProjectManager
from agents.seo_manager import SEOManager
from agents.website_intelligence import WebsiteIntelligenceAgent
from core.agent_orchestrator import AgentOrchestrator
from core.ai_service import AIService, AIServiceError
from core.knowledge_engine import KnowledgeEngine
from core.executive_intelligence import ExecutiveIntelligence
from core.decision_engine import DecisionEngine as SingleDecisionEngine
from core.seo_experiment_engine import SEOExperimentEngine
from core.seo_history import SEOHistory
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry
from dashboard.components.database import open_database
from dashboard.components.briefing_readiness import get_website_briefing_readiness
from dashboard.components.errors import safe_error_detail
from dashboard.components.formatting import (
    format_ai_assessment, format_date, format_datetime,
)
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_sidebar
from dashboard.components.website_selector import get_selected_website_id


def build_executive(database: Any) -> AIExecutive:
    """Compose the existing office services without running any agent."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    registry = WebsiteRegistry(database)
    tasks = TaskEngine(database)
    projects = ProjectManager(tasks, registry, database)
    knowledge = KnowledgeEngine(PROJECT_ROOT / "knowledge")
    knowledge.initialize()
    seo_history = SEOHistory(database)
    intelligence = WebsiteIntelligenceAgent(database, registry)
    orchestrator = AgentOrchestrator(
        DecisionEngine(registry, database, projects), projects, tasks,
        knowledge, database, registry,
    )
    orchestrator.initialize()
    seo_manager = SEOManager(
        database=database, seo_history=seo_history, website_registry=registry,
        project_manager=projects, task_engine=tasks, knowledge_engine=knowledge,
        agent_orchestrator=orchestrator,
    )
    service = AIService()
    analyst = AIAnalyst(
        ai_service=service, database=database, knowledge_engine=knowledge,
        website_intelligence=intelligence, seo_history=seo_history,
        project_manager=projects, task_engine=tasks,
    )
    return AIExecutive(
        ai_service=service, ai_analyst=analyst, database=database,
        website_registry=registry, website_intelligence=intelligence,
        seo_history=seo_history, seo_manager=seo_manager,
        project_manager=projects, task_engine=tasks,
        knowledge_engine=knowledge, agent_orchestrator=orchestrator,
    )


def main() -> None:
    st.set_page_config(page_title="Executive Briefing", page_icon="🎯",
                       layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Executive Briefing")
    render_help_panel(
        purpose="Prioritér højst tre konkrete fokusområder for virksomheden.",
        requirements="Aktive websites og helst profiler, SEO-, salgs- og analysedata.",
        actions="Generér en briefing og gennemgå anbefalingerne.",
        limitations="Siden opretter ikke projekter, opgaver eller websiteændringer.",
    )
    database = open_database()
    try:
        executive = build_executive(database)
        scope = st.radio(
            "Briefingens omfang",
            ["Hele virksomheden", "Det aktive website"],
            horizontal=True,
        )
        website_id = (
            get_selected_website_id()
            if scope == "Det aktive website" else None
        )
        _render_single_decision(database, website_id)
        readiness = (
            get_website_briefing_readiness(database, website_id)
            if scope == "Det aktive website" else None
        )
        if scope == "Det aktive website":
            _render_readiness(readiness, website_id)
        context = executive.collect_company_context(website_id=website_id)
        missing = executive.missing_data(context)
        can_generate = (
            scope == "Hele virksomheden"
            or bool(readiness and readiness["status"] != "Ikke klar")
        )
        if st.button(
            "Generér briefing", type="primary", disabled=not can_generate
        ):
            with st.spinner("Analyserer gemte virksomhedsdata…"):
                try:
                    executive.generate_daily_briefing(website_id=website_id)
                    st.session_state.pop("briefing_error", None)
                    st.success("Briefingen er genereret.")
                except BriefingValidationError as error:
                    st.session_state["briefing_error"] = {
                        "kind": "Ugyldigt modelsvar",
                        "message": "Briefingen kunne ikke valideres efter reparation.",
                        "detail": str(error),
                        "type": type(error).__name__,
                    }
                except AIServiceError as error:
                    st.session_state["briefing_error"] = {
                        "kind": "Teknisk fejl", "message": error.category,
                        "type": error.original_type or type(error).__name__,
                    }
                except Exception as error:
                    st.session_state["briefing_error"] = {
                        "kind": "Teknisk fejl",
                        "message": safe_error_detail(error),
                        "type": type(error).__name__,
                    }
        briefing = executive.get_latest_briefing()
        if briefing:
            briefing = ExecutiveIntelligence(
                database, executive.knowledge_engine.get_company_rules()
            ).enrich_briefing(briefing, website_id=website_id)
        eligible = [w for w in context["websites"] if w["active"] and
                    w["status"] not in {"phasing_out", "archived", "cancelled"}]
    finally:
        database.close()
    error = st.session_state.get("briefing_error")
    if error:
        st.error(f"{error['kind']}: {error['message']}")
        with st.expander("Tekniske detaljer"):
            st.code(error["type"])
            if error.get("detail"):
                st.code(error["detail"])
        if briefing:
            st.info("Den seneste gyldige briefing vises fortsat nedenfor.")
    if missing:
        st.warning("Manglende eller tomme datakilder: " + ", ".join(missing) + ".")
    if not briefing:
        st.info(
            "Der er ikke tilstrækkelige data til en sikker prioritering. "
            "Brug Kom godt i gang til at oprette de manglende data."
        )
        return
    if scope == "Det aktive website":
        st.info(
            "Analysen bygger på website-niveau. Data om konkrete sider og "
            "søgeord er endnu ikke importeret."
        )
    st.caption(
        "Seneste vellykkede briefing: "
        + format_datetime(briefing["updated_at"])
    )
    st.subheader(briefing["company_status"])
    counts = context["counts"]
    for column, (label, value) in zip(st.columns(3), (
        ("Analyserede websites", len(eligible)),
        ("Aktive projekter", counts["active_projects"]),
        ("Åbne opgaver", counts["open_tasks"]),
    )):
        column.metric(label, value)
    if not briefing["focus_areas"]:
        st.info("Der er ikke tilstrækkelige data til en sikker prioritering.")
    for index, focus in enumerate(briefing["focus_areas"][:1]):
        heading = "Dagens beslutning"
        with st.container(border=True):
            st.subheader(f"{heading}: {focus['title']}")
            for column, (label, value) in zip(st.columns(4), (
                ("Prioritet", focus.get("priority_label", "Ukendt")),
                ("Score", focus["priority_score"]),
                ("AI-vurdering", format_ai_assessment(
                    focus['confidence'], include_percent=True
                )),
                ("Tid", f"{focus['estimated_minutes']} min."),
            )):
                column.metric(label, value)
            st.write(f"**Website:** {focus['website']}")
            st.write(
                "**Problem eller mulighed:** "
                + focus.get("problem_or_opportunity", focus["title"])
            )
            st.write(
                "**Hvorfor det er vigtigt:** "
                + focus.get("why_it_matters", focus["reason"])
            )
            st.write(
                f"**Sandsynlig forklaring:** {focus.get('likely_cause', 'Ukendt')}"
            )
            st.write(f"**Næste konkrete handling:** {focus['recommended_action']}")
            if focus.get("target_url"):
                st.write(f"**URL:** {focus['target_url']}")
            if focus.get("target_query"):
                st.write(f"**Søgeord:** {focus['target_query']}")
            if focus.get("exact_steps"):
                st.write("**Konkrete trin:**")
                for step_number, step in enumerate(
                    focus["exact_steps"][:5], start=1
                ):
                    st.write(f"{step_number}. {step}")
            if focus.get("completion_criteria"):
                st.write(
                    f"**Færdigkriterium:** {focus['completion_criteria']}"
                )
            st.write(f"**Ansvarlig agent:** {focus['assigned_agent']}")
            st.write(
                f"**Forventet effekt:** {focus['expected_effect']} — "
                + focus.get("expected_effect_reason", "")
            )
            st.write(
                f"**Målemetode:** {focus.get('measurement_method', 'Ikke angivet')}"
            )
            st.subheader("Derfor blev dette valgt")
            for evidence in focus["evidence"]:
                st.markdown(f"- {evidence}")
            st.write(f"**Prioritetsforklaring:** {focus.get('priority_reason', '')}")
            st.write("**Datagrundlag**")
            for source in focus.get("data_sources", []):
                st.write(f"**{source['source']}:** {source['status']}")
            limitations = focus.get("limitations", [])
            if limitations:
                st.write("**Begrænsninger:** " + " ".join(limitations))
            st.subheader("Næste trin")
            st.info(focus["recommended_action"])
            if any(
                item in focus["recommended_action"].lower()
                for item in ("url-", "søgeordsniveau")
            ):
                st.page_link(
                    "pages/9_SEO.py",
                    label="Se krav til URL- og søgeordsdata",
                )
            elif st.button(
                "Send til Project Manager", key=f"draft-{index}"
            ):
                try:
                    project_id = _create_project_draft(focus)
                    st.success(f"Projektkladde #{project_id} er oprettet.")
                except Exception as error:
                    st.error("Kladde kunne ikke oprettes.")
                    with st.expander("Tekniske detaljer"):
                        st.code(type(error).__name__)
            st.subheader("Det skal du ikke gøre endnu")
            rejected = focus.get("why_not_other_tasks") or [
                "Opdater ikke H1 endnu.",
                "Tilføj ikke nyt indhold endnu.",
                "Ændr ikke interne links endnu.",
            ]
            for item in rejected[:3]:
                st.write(f"- {item}")
            st.caption(
                "Siden skal kun have én målelig ændring ad gangen."
            )
    _render_risks(briefing["risks"])
    _render_opportunities(briefing["opportunities"])
    st.caption(f"Samlet estimeret tid: {briefing['total_estimated_minutes']} min. "
               f"· Model: {briefing['model']}")


def _render_readiness(
    readiness: dict[str, Any] | None, website_id: str | None
) -> None:
    if not website_id:
        st.error("Vælg et aktivt website i sidepanelet.")
        return
    readiness = readiness or {}
    status = readiness.get("status", "Ikke klar")
    if status == "Klar":
        st.success(f"Dataklarhed for {website_id}: Klar")
    elif status == "Delvist klar":
        st.warning(f"Dataklarhed for {website_id}: Delvist klar")
        st.info(
            "Analysen bygger på website-niveau. Data om konkrete sider og "
            "søgeord er endnu ikke importeret."
        )
    else:
        st.error(f"Dataklarhed for {website_id}: Ikke klar")
    for title, values in (
        ("Basale krav", readiness.get("required", {})),
        ("Anbefalede data", readiness.get("recommended", {})),
    ):
        with st.expander(title):
            for label, available in values.items():
                st.write(f"{'✅' if available else '❌'} {label}")


def _create_project_draft(focus: dict[str, Any]) -> int:
    database = open_database()
    try:
        registry = WebsiteRegistry(database)
        tasks = TaskEngine(database)
        manager = ProjectManager(tasks, registry, database)
        return manager.create_draft_from_focus(focus)
    finally:
        database.close()


def _render_single_decision(
    database: Any, website_id: str | None
) -> None:
    """Render the persisted single-decision and experiment lifecycle."""
    registry = WebsiteRegistry(database)
    experiments = SEOExperimentEngine(database)
    engine = SingleDecisionEngine(
        database, registry, experiment_engine=experiments
    )
    drafts = database.get_title_optimization_drafts(website_id)
    awaiting = next((
        item for item in drafts if item["status"] == "awaiting_approval"
    ), None)
    if awaiting:
        titles = awaiting["title_proposals"]
        metas = awaiting["meta_proposals"]
        title_index = min(
            awaiting["recommended_title_index"], len(titles) - 1
        )
        meta_index = min(
            awaiting["recommended_meta_index"], len(metas) - 1
        )
        page_name = awaiting["current_title"] or awaiting["target_url"]
        st.subheader("Dagens opgave")
        st.info(
            "Gennemgå title-forslaget for " + page_name
        )
        st.write(
            "**Hvorfor siden er valgt:** Den bliver vist i Google, men får "
            "færre klik end forventet. En tydeligere title kan forbedre "
            "resultatet uden at ændre sideindholdet."
        )
        st.write(f"**Anbefalet title:** {titles[title_index]['text']}")
        st.write(
            f"**Anbefalet metabeskrivelse:** {metas[meta_index]['text']}"
        )
        st.write("**Forventet tid:** 10 minutter")
        st.page_link(
            "pages/14_Title_Optimering.py",
            label="Gennemgå og godkend forslaget",
        )
        return
    active = experiments.get_active_experiment(website_id)
    if active:
        st.subheader("Aktivt eksperiment")
        st.warning(
            "Denne side indgår i et aktivt eksperiment. Andre ændringer er "
            "sat på pause indtil "
            + format_datetime(active["planned_evaluation_date"],
                              active["planned_evaluation_date"] or "ukendt")
            + "."
        )
        st.write(f"**Ændring:** {active['change_description']}")
        if active["status"] == "waiting_for_data":
            st.info(
                "Vent på måleperioden. Foretag ingen andre ændringer på siden."
            )
        st.write(
            f"**Start:** {format_datetime(active['started_at']) if active['started_at'] else 'Ikke startet'}"
        )
        st.write(
            f"**Evaluering:** {format_datetime(active['planned_evaluation_date'], active['planned_evaluation_date'] or 'Ikke planlagt')}"
        )
        st.page_link("pages/13_Eksperimenter.py", label="Se eksperiment")
        return
    current = engine.get_current_decision(website_id)
    if not current and st.button("Vælg dagens beslutning"):
        engine.select_single_decision(website_id)
        st.rerun()
    if not current:
        st.info(
            "Der er ingen aktiv beslutning. Importér to Search Console-perioder "
            "eller vælg dagens beslutning."
        )
        return
    decision = current["decision"]
    st.subheader("Dagens beslutning")
    st.write(f"**Opgave:** {decision['task_title']}")
    st.write(f"**URL:** {decision['target_url']}")
    st.write(f"**Søgeord:** {decision.get('target_query') or 'Ikke angivet'}")
    st.write(f"**Begrundelse:** {decision['why_selected']}")
    st.write(
        f"**Baselinekrav:** mindst 14 hele dage og én dokumenteret visning."
    )
    st.write(f"**Venteperiode:** {decision['waiting_period_days']} dage")
    col1, col2 = st.columns(2)
    if col1.button("Send til Project Manager", type="primary"):
        result = engine.send_decision_to_project_manager(current["id"])
        st.success(
            f"Projekt #{result['project_id']}, opgave #{result['task_id']} "
            f"og eksperiment #{result['experiment_id']} afventer godkendelse."
        )
    if col2.button("Afvis beslutning"):
        engine.dismiss_decision(current["id"])
        st.rerun()


def _render_risks(items: list[dict[str, Any]]) -> None:
    st.subheader("Risici")
    if not items:
        st.info("Ingen konkrete risici blev identificeret.")
    for item in items:
        if not isinstance(item, dict):
            item = {
                "title": "Databegrænsning", "description": str(item),
                "consequence": "Prioriteringen er mindre sikker.",
                "mitigation": "Indlæs flere data.",
            }
        with st.container(border=True):
            st.write(f"**{item.get('title', 'Risiko')}**")
            st.write(item.get("description", "Ingen beskrivelse."))
            st.write(f"**Konsekvens:** {item.get('consequence', 'Ukendt')}")
            st.write(f"**Håndtering:** {item.get('mitigation', 'Indsaml flere data.')}")


def _render_opportunities(items: list[dict[str, Any]]) -> None:
    st.subheader("Muligheder")
    if not items:
        st.info("Ingen konkrete muligheder blev identificeret.")
    for item in items:
        if not isinstance(item, dict):
            item = {"title": "Mulighed", "reason": str(item)}
        with st.container(border=True):
            st.write(f"**{item.get('title', 'Mulighed')}**")
            st.write(f"**Website:** {item.get('website', 'Ikke angivet')}")
            st.write(f"**Begrundelse:** {item.get('reason', 'Ikke angivet')}")
            for evidence in item.get("evidence", []):
                st.markdown(f"- {evidence}")
            st.write(f"**Næste handling:** {item.get('recommended_action', '')}")
            st.write(
                f"**Agent og tid:** {item.get('assigned_agent', '')} · "
                f"{item.get('estimated_minutes', 0)} min."
            )
            st.write(
                f"**Effekt:** {item.get('expected_effect', 'Ukendt')} · "
                f"**Score:** {item.get('priority_score', 0)} · "
                f"**AI-vurdering:** {format_ai_assessment(item.get('confidence', 0), include_percent=True)}"
            )
            st.write(
                f"**Målemetode:** {item.get('measurement_method', 'Ikke angivet')}"
            )


def _render_daily_task(
    database: Any, engine: SingleDecisionEngine
) -> None:
    """Render exactly one recommended action, never an alternative list."""
    drafts = database.get_title_optimization_drafts()
    awaiting = next(
        (item for item in drafts if item["status"] == "awaiting_approval"),
        None,
    )
    if awaiting:
        titles = awaiting["title_proposals"]
        metas = awaiting["meta_proposals"]
        title_index = min(awaiting["recommended_title_index"], len(titles) - 1)
        meta_index = min(awaiting["recommended_meta_index"], len(metas) - 1)
        page_name = awaiting["current_title"] or awaiting["target_url"]
        st.subheader("Hvad er den vigtigste opgave i dag?")
        with st.container(border=True):
            st.subheader("Gennemgå title-forslaget for " + page_name)
            st.write(f"**Website:** {awaiting['website_id']}")
            st.write(f"**URL:** {awaiting['target_url']}")
            st.write(f"**Anbefalet title:** {titles[title_index]['text']}")
            st.write(
                "**Anbefalet metabeskrivelse:** "
                + metas[meta_index]["text"]
            )
            st.write("**Forventet tid:** 10 minutter")
            st.page_link(
                "pages/14_Title_Optimering.py",
                label="Gennemgå og godkend forslaget",
            )
        return

    current = engine.get_current_decision()
    if not current:
        selected = engine.select_single_decision()
        current = engine.get_current_decision() if selected else None
    st.subheader("Hvad er den vigtigste opgave i dag?")
    if not current:
        st.info(
            "Der anbefales ingen nye SEO-ændringer i dag. Systemet afventer "
            "resultater fra aktive eksperimenter."
        )
        return
    decision = current["decision"]
    with st.container(border=True):
        st.subheader(decision["task_title"])
        st.write(f"**Website:** {decision['website']}")
        st.write(f"**URL:** {decision['target_url']}")
        if decision.get("target_query"):
            st.write(f"**Primært søgeord:** {decision['target_query']}")
        st.write(f"**Hvorfor nu:** {decision['why_selected']}")
        st.write(f"**Forventet tid:** {decision['estimated_minutes']} minutter")
        st.write(f"**Forventet effekt:** {decision['expected_effect']}")
        if st.button("Godkend dagens opgave", type="primary"):
            result = engine.send_decision_to_project_manager(current["id"])
            st.success(
                "Opgaven er godkendt. Der er oprettet ét projekt, én opgave, "
                "ét eksperiment og én baseline. Intet er publiceret."
            )
            st.caption(
                f"Projekt #{result['project_id']} · Opgave #{result['task_id']} "
                f"· Eksperiment #{result['experiment_id']}"
            )
            st.rerun()


def main() -> None:
    """Daily SEO work leader with one decision at a time."""
    st.set_page_config(
        page_title="Executive Briefing", page_icon="🎯", layout="wide"
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Dagens opgave")
    st.caption("Én prioriteret SEO-opgave ad gangen.")
    render_help_panel(
        purpose="Besvar ét spørgsmål: Hvad er den vigtigste opgave i dag?",
        requirements="Search Console-data for mindst to perioder.",
        actions="Godkend dagens opgave eller afvent et aktivt eksperiment.",
        limitations="AI Office publicerer aldrig ændringer på websites.",
    )
    database = open_database()
    try:
        registry = WebsiteRegistry(database)
        experiments = SEOExperimentEngine(database)
        engine = SingleDecisionEngine(
            database, registry, experiment_engine=experiments
        )
        overview = engine.daily_overview()
        next_evaluation = (
            format_date(overview["next_evaluation"])
            if overview["next_evaluation"] else "Ikke planlagt"
        )
        columns = st.columns(4)
        columns[0].metric("Dagens opgave", "1" if (
            engine.get_current_decision()
            or any(
                item["status"] == "awaiting_approval"
                for item in database.get_title_optimization_drafts()
            )
            or overview["candidate_count"]
        ) else "0")
        columns[1].metric("Næste evaluering", next_evaluation)
        columns[2].metric(
            "Aktive eksperimenter", overview["active_experiments"]
        )
        columns[3].metric(
            "Websites i kø", len(overview["queued_websites"])
        )
        if overview["queued_websites"]:
            st.caption(
                "Kø: " + ", ".join(overview["queued_websites"])
            )
        _render_daily_task(database, engine)
    finally:
        database.close()


if __name__ == "__main__":
    main()
