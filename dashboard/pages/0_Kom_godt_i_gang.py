"""Deterministic onboarding workflow for AI Office."""

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_page_link, render_sidebar


def main() -> None:
    st.set_page_config(page_title="Kom godt i gang", page_icon="🧭",
                       layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Kom godt i gang")
    render_help_panel(
        purpose="Siden viser den anbefalede tekniske rækkefølge i AI Office.",
        requirements="Adgang til den lokale database og de relevante datakilder.",
        actions="Følg trinene oppefra og brug linket ved det første ufærdige trin.",
        limitations="Rækkefølgen beregnes med faste regler og starter ikke analyser automatisk.",
    )
    database = open_database()
    try:
        websites = database.get_all_websites()
        search = database.get_search_console_summary()
        discovery = database.get_website_discovery_summary()
        content = database.get_recently_updated(limit=1)
        profiles = database.get_website_profiles()
        analyses = database.get_analysis_history(limit=1)
        briefing = database.get_latest_executive_briefing()
        projects = database.get_active_project_count()
        tasks = database.get_open_task_count()
    finally:
        database.close()
    steps = [
        ("Website Registry", bool(websites), "Registrér de websites AI Office skal arbejde med.",
         "Ingen", "Importér eller kontrollér website-registret.", "pages/11_Websites.py"),
        ("Search Console", bool(search["stored_metrics"]), "Hent søgedata og udvikling.",
         "Website Registry", "Hent Search Console-data.", "pages/9_SEO.py"),
        ("Website Discovery", discovery["scanned"] > 0, "Find offentlige tekniske fakta.",
         "Website Registry", "Scan de aktive websites.", "pages/4_Website_Discovery.py"),
        ("Content import", bool(content), "Hent offentligt WordPress-indhold.",
         "Website Discovery med WordPress", "Hent indhold via Content Explorer.",
         "pages/5_Content_Explorer.py"),
        ("Website Intelligence", bool(profiles), "Saml kendte data i websiteprofiler.",
         "Registry og relevante datakilder", "Kør Website Intelligence.",
         "pages/1_Website_Profile.py"),
        ("AI Analyst", bool(analyses), "Lav en begrundet analyse af et website.",
         "Website Intelligence", "Vælg website og kør analysen.",
         "pages/6_AI_Analyst.py"),
        ("Executive Briefing", briefing is not None, "Prioritér dagens vigtigste fokus.",
         "Website- og analysedata", "Generér dagens briefing.",
         "pages/3_Executive_Briefing.py"),
        ("Projekter og opgaver", projects + tasks > 0, "Omsæt godkendte anbefalinger til arbejde.",
         "En godkendt anbefaling", "Gennemgå projekter og opgaver.",
         "pages/2_Projekter.py"),
    ]
    dependency_ready = True
    for number, (title, complete, purpose, dependency, action, target) in enumerate(steps, 1):
        status = "Klar" if complete else ("Ikke kørt" if dependency_ready else "Mangler data")
        with st.container(border=True):
            st.subheader(f"{number}. {title}")
            st.write(f"**Status:** {status}")
            st.write(f"**Formål:** {purpose}")
            st.write(f"**Afhængigheder:** {dependency}")
            st.write(f"**Næste handling:** {action}")
            render_page_link(target, f"Gå til {title}")
        dependency_ready = dependency_ready and complete
    st.markdown("### Kommende funktioner")
    st.warning(
        "Automation Engine og Supabase er ikke implementeret endnu og kan "
        "derfor ikke startes fra dashboardet."
    )
    render_page_link(
        "pages/12_Systemstatus.py",
        "Se samlet status og næste nødvendige trin",
    )


if __name__ == "__main__":
    main()
