"""Central operational feature status."""
import sys
from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from dashboard.components.feature_status import build_feature_status
from dashboard.components.formatting import format_rows
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_sidebar


def main() -> None:
    st.set_page_config(page_title="Systemstatus", page_icon="🩺", layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Systemstatus")
    render_help_panel(
        purpose="Vis hvad der virker, mangler data eller ikke er implementeret.",
        requirements="Adgang til den lokale database og projektets konfiguration.",
        actions="Find næste nødvendige trin for hver central funktion.",
        limitations="Siden starter ingen importer, analyser eller monitorprocesser.",
    )
    database = open_database()
    try:
        rows = build_feature_status(database, PROJECT_ROOT)
    finally:
        database.close()
    st.dataframe(format_rows(rows), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
