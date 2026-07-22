"""User-triggered website discovery and stored fact browser."""

import sys
from pathlib import Path
from typing import Any

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.decision_engine import DecisionEngine
from agents.project_manager import ProjectManager
from agents.website_discovery import WebsiteDiscoveryAgent
from agents.website_intelligence import WebsiteIntelligenceAgent
from core.agent_orchestrator import AgentOrchestrator
from core.knowledge_engine import KnowledgeEngine
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry
from dashboard.components.database import open_database
from dashboard.components.help_panel import render_help_panel
from dashboard.components.formatting import format_datetime
from dashboard.components.ui import load_styles, render_sidebar, render_table
from dashboard.components.website_selector import (
    get_selected_website_id,
    set_selected_website,
)


def build_agent(database: Any) -> WebsiteDiscoveryAgent:
    registry = WebsiteRegistry(database)
    tasks = TaskEngine(database)
    projects = ProjectManager(tasks, registry, database)
    knowledge = KnowledgeEngine(PROJECT_ROOT / "knowledge")
    knowledge.initialize()
    intelligence = WebsiteIntelligenceAgent(database, registry)
    orchestrator = AgentOrchestrator(
        DecisionEngine(registry, database, projects), projects, tasks,
        knowledge, database, registry,
    )
    orchestrator.initialize()
    return WebsiteDiscoveryAgent(
        database=database, website_registry=registry,
        website_intelligence=intelligence, knowledge_engine=knowledge,
        agent_orchestrator=orchestrator,
    )


def main() -> None:
    st.set_page_config(page_title="Website Discovery", page_icon="🔎",
                       layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Website Discovery")
    st.write(
        "Siden bruger kun offentligt tilgængelige oplysninger. Den logger "
        "aldrig ind og ændrer ikke websitet."
    )
    render_help_panel(
        purpose="Find dokumenterede tekniske fakta om aktive websites.",
        requirements="Websitet skal findes i Website Registry og være offentligt tilgængeligt.",
        actions="Scan ét website eller alle aktive websites.",
        limitations="Siden logger ikke ind, scanner ikke sårbarheder og skriver ikke til websites.",
    )
    database = open_database()
    try:
        agent = build_agent(database)
        websites = [item for item in agent.website_registry.get_all()
                    if item["active"] and item["status"] not in
                    {"phasing_out", "archived", "cancelled"}]
        options = [item["website"] for item in websites]
        current = get_selected_website_id()
        selected = st.selectbox(
            "Website", options,
            index=options.index(current) if current in options else 0,
        ) if options else None
        if selected:
            set_selected_website(selected)
        one, all_sites = st.columns(2)
        if one.button("Scan valgte website", disabled=not selected,
                      use_container_width=True):
            with st.spinner(f"Scanner {selected}…"):
                result = agent.scan_site(selected)
            st.success("Website-scanningen er gennemført.")
        if all_sites.button("Scan alle aktive websites",
                            use_container_width=True):
            with st.spinner("Scanner aktive websites…"):
                result = agent.scan_all_sites()
            st.success(f"{result['websites_scanned']} websites behandlet; "
                       f"{result['failed']} fejl.")
        summary = database.get_website_discovery_summary()
        profiles = database.get_website_discovery_profiles()
        profile = agent.get_profile(selected) if selected else None
        changes = agent.get_changes(selected) if selected else []
    finally:
        database.close()

    values = (
        ("Scannede websites", summary["scanned"]),
        ("WordPress-sites", summary["wordpress"]),
        ("Ukendt CMS", summary["unknown"]),
        ("Robots-fejl", summary["robots_errors"]),
        ("Sitemap-fejl", summary["sitemap_errors"]),
        ("HTTPS-fejl", summary["https_errors"]),
    )
    for start in (0, 3):
        for column, (label, value) in zip(st.columns(3), values[start:start+3]):
            column.metric(label, value)
    st.caption(
        "Seneste scanning: "
        + (
            format_datetime(summary["latest_scan"])
            if summary["latest_scan"] else "Ingen scanninger"
        )
    )
    render_table(profiles, columns={
        "website_id": "Website", "cms": "CMS", "theme": "Tema",
        "page_builder": "Page builder", "http_status": "HTTP-status",
        "robots_status": "Robots", "sitemap_status": "Sitemap",
        "sitemap_url_count": "Sitemap-URL'er", "scanned_at": "Seneste scanning",
        "scan_status": "Status",
    })
    if profile:
        st.subheader(f"Dokumenterede fakta: {profile['website_id']}")
        for column, (label, value) in zip(st.columns(3), (
            ("AI-vurdering af CMS", profile["cms_confidence"]),
            ("AI-vurdering af tema", profile["theme_confidence"]),
            ("AI-vurdering af builder", profile["page_builder_confidence"]),
        )):
            column.metric(label, value)
        for label, key in (
            ("Canonical", "canonical_url"), ("Title", "title"),
            ("Meta description", "meta_description"), ("H1", "h1"),
            ("Schema", "schema_types"), ("Sitemap-typer", "sitemap_types"),
            ("Fejl", "error_message"),
        ):
            st.write(f"**{label}:** {profile[key] or 'Ingen data'}")
        st.write("**Dokumenterede signaler:**")
        for signal in profile["detected_signals"]:
            explanation = _signal_explanation(signal)
            st.markdown(f"- {explanation}")
            with st.expander("Vis teknisk signal"):
                st.code(_technical_signal(signal))
        st.write("**Ændringer siden tidligere scanninger:**")
        if len(changes) < 2:
            st.caption("Ingen dokumenterede ændringer.")
        for item in changes[1:]:
            st.markdown(
                f"- {format_datetime(item['scanned_at'])}: gemt ændret profil"
            )


def _signal_explanation(signal: str) -> str:
    if signal == "wordpress:wp-content":
        return (
            "WordPress blev fundet, fordi websitet indlæser filer fra wp-content."
        )
    if signal == "wordpress:wp-includes":
        return (
            "WordPress blev fundet, fordi websitet indlæser systemfiler fra wp-includes."
        )
    if signal == "wordpress:generator":
        return "WordPress er angivet i sidens offentlige generator-felt."
    if signal.startswith("theme:documented:"):
        return (
            f"Temaet {signal.rsplit(':', 1)[-1]} fremgår af en offentlig asset-URL."
        )
    if signal.startswith("builder:asset:"):
        return (
            f"Page builderen {signal.rsplit(':', 1)[-1]} fremgår af en offentlig asset-URL."
        )
    return "Et offentligt teknisk signal blev fundet."


def _technical_signal(signal: str) -> str:
    return {
        "wordpress:wp-content": "asset path contains /wp-content/",
        "wordpress:wp-includes": "asset path contains /wp-includes/",
        "wordpress:generator": "meta[name=generator] contains WordPress",
    }.get(signal, signal)


if __name__ == "__main__":
    main()
