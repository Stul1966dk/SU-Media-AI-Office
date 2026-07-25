"""Settings overview for operational and external services."""

import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_page_link, render_sidebar
from dashboard.components.database import open_database
from dashboard.components.startup_sync import SETTING_NAME


def main() -> None:
    st.set_page_config(
        page_title="Indstillinger",
        page_icon="⚙️",
        layout="wide",
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar(show_website_selector=False)
    st.title("Indstillinger")
    render_help_panel(
        purpose="Saml appens forbindelser, driftsstatus og datakilder.",
        requirements="Vælg det område, du vil administrere.",
        actions="Åbn integrationer, Partner Ads eller systemstatus.",
        limitations="Oversigten ændrer ikke konfiguration eller eksterne data.",
    )
    st.subheader("Synkronisering")
    database = open_database()
    try:
        saved_auto_sync = database.get_app_setting(SETTING_NAME, False)
        auto_sync = st.toggle(
            "Synkroniser automatisk ved app-start",
            value=saved_auto_sync,
            help=(
                "Kører Opdater alle data én gang i baggrunden ved starten "
                "af en ny Streamlit-session og bruger alle aktive websites."
            ),
        )
        if auto_sync != saved_auto_sync:
            database.set_app_setting(SETTING_NAME, auto_sync)
            st.success("Indstillingen er gemt.")
    finally:
        database.close()
    st.subheader("Administration")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### Integrationer")
        st.caption("Forbindelser, API-nøgler og tilknyttede konti.")
        render_page_link("pages/18_Integrationer.py", "Åbn Integrationer")
    with col2:
        st.markdown("### Partner Ads")
        st.caption("Import og kontrol af Partner Ads-data.")
        render_page_link("pages/10_Partner_Ads.py", "Åbn Partner Ads")
    with col3:
        st.markdown("### Systemstatus")
        st.caption("Driftsstatus for appens services og datakilder.")
        render_page_link("pages/12_Systemstatus.py", "Åbn Systemstatus")


if __name__ == "__main__":
    main()
