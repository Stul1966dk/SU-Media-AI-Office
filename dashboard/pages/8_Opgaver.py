"""Website-filtered tasks."""
import sys
from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_sidebar, render_table
from dashboard.components.website_selector import get_selected_website_id


def main() -> None:
    st.set_page_config(page_title="Opgaver", page_icon="✅", layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Opgaver")
    render_help_panel(
        purpose="Se planlagte og aktive opgaver for et website.",
        requirements="Opgaver oprettes som del af et projekt.",
        actions="Brug websitevalget eller vis opgaver på tværs af websites.",
        limitations="Siden udfører ikke opgaver og ændrer ikke deres status.",
    )
    show_all = st.checkbox("Vis alle websites")
    selected = get_selected_website_id()
    database = open_database()
    try:
        rows = database.get_task_records_for_project()
    finally:
        database.close()
    if not show_all:
        rows = [row for row in rows if row.get("website_id") == selected]
    if not selected and not show_all:
        st.info("Vælg et aktivt website i sidepanelet for at se opgaver.")
    elif not rows:
        st.info("Der er ingen opgaver for dette valg. Opgaver oprettes under projekter.")
    else:
        render_table(rows, columns={
            "website_id": "Website", "project_title": "Projekt",
            "title": "Opgave", "assigned_agent": "Ansvarlig",
            "estimated_minutes": "Minutter", "priority_score": "Prioritet",
            "status": "Status",
        })


if __name__ == "__main__":
    main()
