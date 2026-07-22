"""User-triggered AI Analyst with explicit prerequisites and error states."""

import sys
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.ai_analyst import AIAnalyst
from agents.project_manager import ProjectManager
from agents.website_intelligence import WebsiteIntelligenceAgent
from core.ai_service import AIService, AIServiceError
from core.knowledge_engine import KnowledgeEngine
from core.seo_history import SEOHistory
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry
from dashboard.components.database import open_database
from dashboard.components.errors import safe_error_detail
from dashboard.components.formatting import format_ai_assessment, format_datetime
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_sidebar
from dashboard.components.website_selector import (
    get_selected_website_id,
    set_selected_website,
)


def build_analyst(database: Any) -> AIAnalyst:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    registry = WebsiteRegistry(database)
    tasks = TaskEngine(database)
    projects = ProjectManager(tasks, registry, database)
    knowledge = KnowledgeEngine(PROJECT_ROOT / "knowledge")
    knowledge.initialize()
    intelligence = WebsiteIntelligenceAgent(database, registry)
    return AIAnalyst(
        ai_service=AIService(), database=database, knowledge_engine=knowledge,
        website_intelligence=intelligence, seo_history=SEOHistory(database),
        project_manager=projects, task_engine=tasks,
    )


def main() -> None:
    st.set_page_config(page_title="AI Analyst", page_icon="🧠", layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("AI Analyst")
    render_help_panel(
        purpose="Analysér ét website ud fra de data AI Office allerede kender.",
        requirements="Et aktivt website og en Website Intelligence-profil.",
        actions="Vælg et website, se datakilderne og start analysen.",
        limitations="Analysen foreslår handlinger, men udfører dem ikke.",
    )
    database = open_database()
    try:
        websites = [
            item for item in database.get_all_websites()
            if item["active"] and item["status"] not in
            {"phasing_out", "archived", "cancelled"}
        ]
        options = [item["website"] for item in websites]
        current = get_selected_website_id()
        website_id = st.selectbox(
            "Vælg website", options,
            index=options.index(current) if current in options else 0,
        ) if options else None
        if website_id:
            set_selected_website(website_id)
            st.info(f"Analysen køres for: {website_id}")
        availability = _availability(database, website_id) if website_id else {}
        if website_id:
            st.subheader("Tilgængelige datakilder")
            for label, available in availability.items():
                st.write(f"{'✅' if available else '❌'} {label}")
        missing = [label for label, available in availability.items()
                   if not available and label in {"Websiteprofil", "Website Registry"}]
        if st.button("Kør analyse", disabled=not website_id or bool(missing),
                     type="primary"):
            try:
                result = build_analyst(database).analyze_site(website_id)
                if result["analysis_type"].endswith("_error"):
                    st.session_state["analyst_error"] = {
                        "kind": "Ugyldigt modelsvar",
                        "message": result["problem"],
                        "type": "ModelResponseValidationError",
                    }
                else:
                    st.session_state.pop("analyst_error", None)
                    st.success("Analysen er gennemført.")
                selected = database.get_latest_analysis(
                    website_id=website_id
                ) or result
            except AIServiceError as error:
                st.session_state["analyst_error"] = {
                    "kind": "Modelsvar eller AI-service",
                    "message": error.category,
                    "type": error.original_type or type(error).__name__,
                    "next": "Kontrollér OpenAI-status og prøv analysen igen.",
                }
                selected = None
            except ValueError as error:
                st.session_state["analyst_error"] = {
                    "kind": "Manglende eller ugyldige data",
                    "message": safe_error_detail(error),
                    "type": type(error).__name__,
                    "next": "Opdatér websiteprofilen og de manglende datakilder.",
                }
                selected = None
            except Exception as error:
                st.session_state["analyst_error"] = {
                    "kind": "Programfejl",
                    "message": safe_error_detail(error),
                    "type": type(error).__name__,
                    "next": "Kontrollér loggen og ret programfejlen før ny kørsel.",
                }
                selected = None
        else:
            selected = database.get_latest_analysis(
                website_id=website_id
            ) if website_id else None
    finally:
        database.close()
    if missing:
        st.warning(
            "Analysen kan ikke køres endnu. Mangler: " + ", ".join(missing)
            + ". Kør Website Intelligence via Website Profile."
        )
    error = st.session_state.get("analyst_error")
    if error:
        st.error(f"{error['kind']}: {error['message']}")
        st.info(f"Næste handling: {error.get('next', 'Prøv igen.')}")
        with st.expander("Tekniske detaljer"):
            st.code(error["type"])
    if selected:
        timestamp = (
            selected.get("created_at")
            or selected.get("updated_at")
            or selected.get("timestamp")
            or "Tidspunkt ikke gemt"
        )
        st.caption(f"Seneste analyse: {format_datetime(timestamp, str(timestamp))}")
        _render_full_report(selected)
    elif website_id and not missing and not error:
        st.info(
            "Der findes endnu ingen analyse for dette website. "
            "Klik Kør analyse for at oprette den første."
        )
    elif not website_id:
        st.info(
            "Vælg et website for at se datagrundlaget og den seneste analyse."
        )


def _availability(database: Any, website_id: str) -> dict[str, bool]:
    source = database.get_website_intelligence_source(website_id)
    return {
        "Website Registry": database.get_website(website_id) is not None,
        "Websiteprofil": database.get_website_profile_detail(website_id) is not None,
        "Search Console": bool(database.get_search_console_daily_metrics(
            website_id=website_id
        )),
        "SEO Health": bool((source or {}).get("seo_health")),
        "Salgshistorik": bool((source or {}).get("partner_ads", {}).get("sales")),
        "Projekter og opgaver": bool(
            (source or {}).get("active_projects") or
            (source or {}).get("active_tasks")
        ),
    }


def _render_full_report(analysis: dict[str, Any]) -> None:
    st.subheader("Analyse")
    for column, (label, value) in zip(st.columns(3), (
        ("Prioritet", analysis["priority"]),
        ("AI-vurdering", format_ai_assessment(
            analysis["confidence"], include_percent=True
        )),
        ("Model", analysis["model"]),
    )):
        column.metric(label, value)
    for label, key in (
        ("Opsummering", "summary"), ("Problem", "problem"),
        ("Rodårsag", "root_cause"),
        ("Anbefalet handling", "recommended_action"),
        ("Forventet effekt", "expected_effect"),
    ):
        st.markdown(f"**{label}:** {analysis[key]}")
    for label, key in (
        ("Begrundelse", "reasoning"),
        ("Nødvendige agenter", "required_agents"),
        ("Foreslåede opgaver", "suggested_tasks"),
    ):
        st.markdown(f"**{label}**")
        if analysis[key]:
            for item in analysis[key]:
                st.markdown(f"- {item}")
        else:
            st.caption("Ingen elementer blev foreslået.")


if __name__ == "__main__":
    main()
