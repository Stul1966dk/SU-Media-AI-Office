"""Per-website SEO roadmap: goals and the income-first experiment sequence."""
import sys
from pathlib import Path
from typing import Any

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.seo_roadmap import build_website_roadmap
from dashboard.components.database import open_database
from dashboard.components.formatting import format_currency
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_sidebar
from dashboard.components.website_selector import get_selected_website_id


GOAL_ICONS = {
    "monetization_gap": "💰",
    "striking_distance": "🎯",
    "earner_growth": "📈",
}
EXPERIMENT_LABELS = {
    "monetization": "Monetisering",
    "content_update": "Indhold / placering",
    "title_meta": "Title & meta",
    "internal_links": "Interne links",
    "schema": "Strukturerede data",
    "technical_fix": "Teknisk",
}


def main() -> None:
    st.set_page_config(page_title="Køreplan", page_icon="🗺️", layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("SEO-køreplan")
    render_help_panel(
        purpose=(
            "Se en samlet køreplan pr. website: hvor pengene er, hvilke mål "
            "der er sat, og hvilke eksperimenter der bør køres først."
        ),
        requirements=(
            "Search Console-, Partner Ads- og Plausible-data skal være "
            "importeret for det aktive website."
        ),
        actions=(
            "Brug målene til at prioritere, og start den øverste anbefaling "
            "som et målt 28-dages eksperiment."
        ),
        limitations="Køreplanen ændrer intet automatisk; alt godkendes manuelt.",
    )
    website_id = get_selected_website_id()
    if not website_id:
        st.info("Vælg et aktivt website i menuen for at se dets køreplan.")
        return
    database = open_database()
    try:
        roadmap = build_website_roadmap(database, website_id)
        st.subheader(website_id)
        _render_summary(roadmap["summary"])
        st.write(roadmap["narrative"])
        _render_active_projects(database, website_id)
        st.subheader("Mål")
        if not roadmap["goals"]:
            st.info(
                "Der er endnu ikke nok målte signaler til at sætte mål for dette "
                "website. Importér mere Search Console- og salgsdata først."
            )
        for goal in roadmap["goals"]:
            _render_goal(database, website_id, goal)
        st.subheader("Anbefalet rækkefølge")
        _render_sequence(roadmap["recommended_sequence"])
    finally:
        database.close()


def _render_summary(summary: dict[str, Any]) -> None:
    columns = st.columns(5)
    columns[0].metric("Visninger", f"{summary['impressions']:,}".replace(",", "."))
    columns[1].metric("Klik", f"{summary['clicks']:,}".replace(",", "."))
    columns[2].metric("Provision", format_currency(summary["commission"]))
    columns[3].metric("Gns. placering", f"{summary['avg_position']:.1f}")
    columns[4].metric(
        "Besøg (Plausible)", f"{summary['visitors_28d']:,}".replace(",", ".")
    )


def _render_goal(
    database: Any, website_id: str, goal: dict[str, Any]
) -> None:
    icon = GOAL_ICONS.get(goal["type"], "•")
    with st.container(border=True):
        st.markdown(f"#### {icon} {goal['title']}")
        st.write(f"**Mål:** {goal['target']}")
        rows = [_goal_row(goal["type"], item) for item in goal["items"]]
        if rows:
            st.table(rows)
        _render_goal_project_control(database, website_id, goal)


def _render_goal_project_control(
    database: Any, website_id: str, goal: dict[str, Any]
) -> None:
    """Let the user turn one page from a goal into a multi-experiment project."""
    urls = list(dict.fromkeys(item["url"] for item in goal["items"]))
    active_urls = {
        project["target_url"]
        for project in database.get_seo_goal_projects()
        if project["status"] in {"active", "awaiting_confirmation"}
    }
    choices = [url for url in urls if url not in active_urls]
    if not choices:
        st.caption("Alle sider i dette mål har allerede et aktivt projekt.")
        return
    columns = st.columns([3, 1])
    selected_url = columns[0].selectbox(
        "Gør en side til et projekt", choices,
        key=f"project_url_{goal['type']}", format_func=_path,
    )
    if columns[1].button("Gør til projekt", key=f"project_btn_{goal['type']}"):
        try:
            _full_project_service(database).start_project(
                website_id, selected_url, goal["metric"]
            )
            st.success(
                f"Projekt oprettet for {_path(selected_url)}. Første "
                "eksperiment er lagt i køen på 'I dag'."
            )
            st.rerun()
        except Exception as error:  # surface a friendly message
            st.error(f"Kunne ikke oprette projektet: {error}")


def _render_active_projects(database: Any, website_id: str) -> None:
    from core.seo_project import SEOProjectService

    projects = [
        project for project in database.get_seo_goal_projects()
        if project["website_id"] == website_id
        and project["status"] in {"active", "awaiting_confirmation"}
    ]
    if not projects:
        return
    st.subheader("Aktive projekter")
    service = SEOProjectService(database)
    for project in projects:
        progress = service.project_progress(project["id"])
        with st.container(border=True):
            st.markdown(
                f"#### 🚩 {progress['goal_label']} — "
                f"{_path(progress['target_url'])}"
            )
            done = [
                item for item in progress["experiments"]
                if item["status"] == "completed"
            ]
            st.caption(
                f"Status: {progress['status']} · "
                f"{len(progress['experiments'])} eksperiment(er), "
                f"{len(done)} afsluttet"
            )
            if progress["experiments"]:
                st.table([
                    {
                        "Ændring": EXPERIMENT_LABELS.get(
                            item["experiment_type"], item["experiment_type"]
                        ),
                        "Status": item["status"],
                        "Resultat": item.get("result") or "—",
                    }
                    for item in progress["experiments"]
                ])
            if project["status"] == "awaiting_confirmation":
                reason = (
                    "Målet ser ud til at være nået."
                    if progress["goal_reached"]
                    else "Siden er udtømt for oplagte ændringer."
                )
                st.info(f"{reason} Skal projektet markeres som fuldført?")
                confirm, abandon = st.columns(2)
                if confirm.button(
                    "Bekræft fuldført", key=f"confirm_{project['id']}",
                    type="primary",
                ):
                    service.confirm_completion(project["id"])
                    st.rerun()
                if abandon.button(
                    "Afbryd projekt", key=f"abandon_{project['id']}"
                ):
                    service.abandon(project["id"])
                    st.rerun()
            _render_project_dialog(database, project["id"])


def _render_project_dialog(database: Any, project_id: int) -> None:
    """A small AI dialog scoped to one project, grounded in its measured data."""
    with st.expander("Spørg AI om projektet"):
        quick = None
        columns = st.columns(3)
        if columns[0].button("Forklar baggrunden", key=f"q_bg_{project_id}"):
            quick = "Forklar baggrunden for dette projekt."
        if columns[1].button("Status", key=f"q_st_{project_id}"):
            quick = "Hvad er status på projektet lige nu?"
        if columns[2].button("Næste skridt", key=f"q_ns_{project_id}"):
            quick = "Hvad er næste skridt i projektet?"
        typed = st.text_input(
            "Eller skriv et spørgsmål", key=f"q_in_{project_id}"
        )
        asked = st.button("Spørg", key=f"q_ask_{project_id}")
        question = quick or (typed.strip() if asked and typed.strip() else None)
        if question:
            from core.ai_service import AIService
            from core.seo_project import SEOProjectService

            answer = SEOProjectService(
                database, ai_service=AIService()
            ).answer_question(project_id, question)
            st.markdown(f"**Spørgsmål:** {question}")
            st.write(answer)


def _full_project_service(database: Any) -> Any:
    from agents.title_optimizer import TitleOptimizer
    from core.ai_service import AIService
    from core.daily_work_preparation import DailyWorkPreparationService
    from core.seo_experiment_engine import SEOExperimentEngine
    from core.seo_project import SEOProjectService
    from core.website_registry import WebsiteRegistry
    from core.work_queue_service import WorkQueueService

    registry = WebsiteRegistry(database)
    queue = WorkQueueService(
        database, registry,
        experiment_engine=SEOExperimentEngine(database),
    )
    preparation = DailyWorkPreparationService(
        database=database, queue=queue,
        title_optimizer=TitleOptimizer(
            database=database, website_registry=registry,
            ai_service=AIService(),
        ),
    )
    return SEOProjectService(
        database, preparation=preparation, ai_service=AIService()
    )


def _goal_row(goal_type: str, item: dict[str, Any]) -> dict[str, Any]:
    if goal_type == "striking_distance":
        return {
            "Søgeord": item["query"],
            "Side": _path(item["url"]),
            "Visninger": item["impressions"],
            "Placering": _position(item["position"]),
        }
    row = {
        "Side": _path(item["url"]),
        "Visninger": item.get("impressions", ""),
        "Placering": _position(item.get("position")),
    }
    if "commission" in item:
        row["Provision"] = format_currency(item["commission"])
    return row


def _render_sequence(sequence: list[dict[str, Any]]) -> None:
    if not sequence:
        st.info(
            "Ingen klare næste eksperimenter lige nu — der mangler enten data "
            "eller alle relevante sider er allerede under måling."
        )
        return
    st.table([
        {
            "Prioritet": item["priority_score"],
            "Type": EXPERIMENT_LABELS.get(
                item["experiment_type"], item["experiment_type"]
            ),
            "Måles på": item["goal_metric"],
            "Side": _path(item["target_url"]),
            "Visninger": item.get("impressions", ""),
            "Placering": _position(item.get("position")),
        }
        for item in sequence
    ])


def _position(value: Any) -> str:
    """Show one decimal so a table column does not pad to 15.4000."""
    if value in (None, ""):
        return ""
    return f"{float(value):.1f}"


def _path(url: str) -> str:
    """Show the page path only, so the table stays readable."""
    without_scheme = str(url).split("://", 1)[-1]
    slash = without_scheme.find("/")
    return without_scheme[slash:] if slash != -1 else "/"


if __name__ == "__main__":
    main()
