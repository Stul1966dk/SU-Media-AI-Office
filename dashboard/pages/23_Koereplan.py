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
    finally:
        database.close()
    st.subheader(website_id)
    _render_summary(roadmap["summary"])
    st.write(roadmap["narrative"])
    st.subheader("Mål")
    if not roadmap["goals"]:
        st.info(
            "Der er endnu ikke nok målte signaler til at sætte mål for dette "
            "website. Importér mere Search Console- og salgsdata først."
        )
    for goal in roadmap["goals"]:
        _render_goal(goal)
    st.subheader("Anbefalet rækkefølge")
    _render_sequence(roadmap["recommended_sequence"])


def _render_summary(summary: dict[str, Any]) -> None:
    columns = st.columns(5)
    columns[0].metric("Visninger", f"{summary['impressions']:,}".replace(",", "."))
    columns[1].metric("Klik", f"{summary['clicks']:,}".replace(",", "."))
    columns[2].metric("Provision", format_currency(summary["commission"]))
    columns[3].metric("Gns. placering", f"{summary['avg_position']:.1f}")
    columns[4].metric(
        "Besøg (Plausible)", f"{summary['visitors_28d']:,}".replace(",", ".")
    )


def _render_goal(goal: dict[str, Any]) -> None:
    icon = GOAL_ICONS.get(goal["type"], "•")
    with st.container(border=True):
        st.markdown(f"#### {icon} {goal['title']}")
        st.write(f"**Mål:** {goal['target']}")
        rows = [_goal_row(goal["type"], item) for item in goal["items"]]
        if rows:
            st.table(rows)


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
