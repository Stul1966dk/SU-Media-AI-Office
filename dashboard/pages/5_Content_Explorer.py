"""Read-only website content importer and explorer."""

import sys
from pathlib import Path
from typing import Any

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.decision_engine import DecisionEngine
from agents.project_manager import ProjectManager
from connectors.connector_factory import ConnectorFactory
from core.agent_orchestrator import AgentOrchestrator
from core.knowledge_engine import KnowledgeEngine
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry
from dashboard.components.database import open_database
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_sidebar, render_table
from dashboard.components.website_selector import (
    get_selected_website_id,
    set_selected_website,
)


TYPE_LABELS = {
    "post": "Indlæg", "page": "Sider", "category": "Kategorier",
    "tag": "Tags", "media": "Medier",
}


def build_orchestrator(database: Any) -> AgentOrchestrator:
    registry = WebsiteRegistry(database)
    tasks = TaskEngine(database)
    projects = ProjectManager(tasks, registry, database)
    knowledge = KnowledgeEngine(PROJECT_ROOT / "knowledge")
    knowledge.initialize()
    orchestrator = AgentOrchestrator(
        DecisionEngine(registry, database, projects), projects, tasks,
        knowledge, database, registry,
    )
    orchestrator.initialize()
    return orchestrator


def main() -> None:
    st.set_page_config(page_title="Content Explorer", page_icon="📚",
                       layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Content Explorer")
    render_help_panel(
        purpose="Hent og udforsk offentligt indhold fra dokumenterede WordPress-sites.",
        requirements="Website Discovery skal have identificeret WordPress.",
        actions="Hent indhold, filtrér, søg, sortér og se metadata.",
        limitations="Siden kan ikke redigere eller publicere indhold.",
    )
    database = open_database()
    try:
        factory = ConnectorFactory(database)
        websites = [
            item["website_id"] for item in database.get_website_discovery_profiles()
            if item["suggested_connector"] == "WordPressConnector"
        ]
        current = get_selected_website_id()
        filter_options = ["Alle websites", *websites]
        default = current if current in websites else "Alle websites"
        selected_filter = st.selectbox(
            "Website", filter_options, index=filter_options.index(default)
        )
        website = None if selected_filter == "Alle websites" else selected_filter
        if website:
            set_selected_website(website)
        suggestion = factory.suggested_connector(website) if website else None
        if suggestion:
            st.caption(f"Foreslået connector: {suggestion}")
        if st.button("Hent offentligt indhold", disabled=not suggestion,
                     type="primary"):
            connector = factory.create(
                website, agent_orchestrator=build_orchestrator(database)
            )
            with st.spinner("Henter offentligt websiteindhold…"):
                if connector is None or not connector.connect():
                    st.error("Der kunne ikke oprettes en offentlig forbindelse.")
                else:
                    result = connector.import_content()
                    connector.disconnect()
                    st.success(
                        f"{result['total']} elementer læst; "
                        f"{result['changed']} nye eller ændrede."
                    )
        content_type = st.selectbox(
            "Indholdstype", list(TYPE_LABELS),
            format_func=TYPE_LABELS.get,
        )
        search = st.text_input("Søg i titel eller slug")
        sort = st.selectbox(
            "Sortér efter", ["date", "words", "title"],
            format_func={"date": "Dato", "words": "Ord", "title": "Titel"}.get,
        )
        rows = (
            database.get_content_by_type(website, content_type)
            if website else [
                item for site in websites
                for item in database.get_content_by_type(site, content_type)
            ]
        )
        filtered = [
            item for item in rows
            if not search or search.casefold() in (
                item["title"] + " " + item["slug"]
            ).casefold()
        ]
        filtered.sort(key={
            "date": lambda x: x["published_at"],
            "words": lambda x: x["word_count"],
            "title": lambda x: x["title"].casefold(),
        }[sort], reverse=sort != "title")
        selected_id = st.selectbox(
            "Vælg række for detaljer",
            [item["content_id"] for item in filtered],
            index=None,
            format_func=lambda value: next(
                (item["title"] or item["slug"] or value for item in filtered
                 if item["content_id"] == value), value
            ),
        )
    finally:
        database.close()

    st.subheader(TYPE_LABELS[content_type])
    render_table(filtered, columns={
        "title": "Titel", "slug": "Slug", "status": "Status",
        "published_at": "Dato", "content_updated_at": "Opdateret",
        "word_count": "Ord", "url": "URL",
    })
    selected = next(
        (item for item in filtered if item["content_id"] == selected_id), None
    )
    if selected:
        st.subheader("Metadata")
        st.write(f"**Titel:** {selected['title'] or 'Ingen titel'}")
        st.write(f"**URL:** {selected['url']}")
        st.write(f"**Status:** {selected['status']}")
        st.write(f"**Interne links:** {selected['internal_link_count']}")
        st.write(f"**Eksterne links:** {selected['external_link_count']}")
        st.write(f"**Kategorier:** {', '.join(selected['categories']) or 'Ingen'}")
        st.write(f"**Tags:** {', '.join(selected['tags']) or 'Ingen'}")
        if selected["featured_image"]:
            st.image(selected["featured_image"], caption="Featured image")


if __name__ == "__main__":
    main()
