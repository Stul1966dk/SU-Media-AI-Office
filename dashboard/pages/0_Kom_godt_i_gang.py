"""Deterministic onboarding workflow for AI Office."""

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import (
    load_styles, render_next_step, render_page_link, render_sidebar,
)


def main() -> None:
    st.set_page_config(page_title="Kom godt i gang", page_icon="🧭",
                       layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Kom godt i gang")
    render_help_panel(
        purpose="Vis den korteste vej fra opsætning til din første opgave.",
        requirements="Adgang til de websites og datakilder, du vil bruge.",
        actions="Start ved det første ufærdige trin og følg næste link.",
        limitations="AI Office ændrer aldrig et website automatisk.",
    )
    database = open_database()
    try:
        websites = database.get_all_websites()
        search = database.get_search_console_summary()
        experiments = database.get_seo_experiments()
    finally:
        database.close()
    active_websites = [
        item for item in websites
        if item.get("active") and item.get("status") not in
        {"phasing_out", "archived", "cancelled"}
    ]
    steps = [
        (
            "Vælg websites", bool(active_websites),
            "Vælg de få websites, AI Office skal prioritere.",
            "Vælg aktive websites.", "pages/11_Websites.py",
        ),
        (
            "Forbind data", bool(search["stored_metrics"]),
            "Forbind Search Console og Plausible, så anbefalinger bygger på data.",
            "Kontrollér integrationerne.", "pages/18_Integrationer.py",
        ),
        (
            "Arbejd fra I dag", bool(search["stored_metrics"]),
            "Få én konkret anbefaling og gennemfør hele opgaven samme sted.",
            "Åbn din aktuelle opgave.", "app.py",
        ),
        (
            "Følg resultater", bool(experiments),
            "Se om gennemførte ændringer skaber en målbar forbedring.",
            "Følg aktive og afsluttede målinger.", "pages/13_Eksperimenter.py",
        ),
    ]
    dependency_ready = True
    for number, (title, complete, purpose, action, target) in enumerate(steps, 1):
        status = "Klar" if complete else ("Ikke kørt" if dependency_ready else "Mangler data")
        with st.container(border=True):
            st.subheader(f"{number}. {title}")
            st.write(f"**Status:** {status}")
            st.write(f"**Formål:** {purpose}")
            st.write(f"**Næste handling:** {action}")
            render_page_link(target, f"Gå til {title}")
        dependency_ready = dependency_ready and complete
    render_next_step(
        text="Når opsætningen er klar, starter og slutter dit daglige arbejde på I dag.",
        path="app.py",
        label="Gå til I dag",
    )


if __name__ == "__main__":
    main()
