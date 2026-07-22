"""Website-filtered projects."""
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
    st.set_page_config(page_title="Projekter", page_icon="📁", layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Projekter")
    render_help_panel(
        purpose="Se projekter for det website, du arbejder med.",
        requirements="Et website og mindst ét projekt skal være oprettet.",
        actions="Filtrér på det valgte website eller vis alle projekter.",
        limitations="Siden ændrer ikke projekter automatisk.",
    )
    show_all = st.checkbox("Vis alle websites")
    selected = get_selected_website_id()
    database = open_database()
    try:
        rows = database.get_projects(None if show_all else selected)
    finally:
        database.close()
    if not selected and not show_all:
        st.info("Vælg et aktivt website i sidepanelet for at se projekter.")
    elif not rows:
        st.info("Der er ingen projekter for dette valg. Opret et projekt fra en anbefaling.")
    else:
        render_table(rows, columns={
            "website_id": "Website", "title": "Projekt", "status": "Status",
            "priority": "Prioritet", "expected_effect": "Forventet effekt",
            "created_at": "Oprettet",
        })


if __name__ == "__main__":
    main()
