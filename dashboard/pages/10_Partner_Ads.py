"""Partner Ads overview with optional website filter."""
import sys
from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.partner_ads_import import execute_partner_ads_check
from dashboard.components.database import open_database
from dashboard.components.errors import safe_error_detail
from dashboard.components.formatting import format_datetime
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_sidebar, render_table
from dashboard.components.website_selector import get_selected_website_id


def main() -> None:
    st.set_page_config(page_title="Partner Ads", page_icon="💳", layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Partner Ads")
    render_help_panel(
        purpose="Se registrerede Partner Ads-salg på tværs af websites.",
        requirements="Partner Ads-data skal være importeret.",
        actions="Vis alle salg eller afgræns dem til det aktive website.",
        limitations="Siden ændrer ikke data hos Partner Ads.",
    )
    st.info(
        "Automatisk overvågning kører kun, når monitorprocessen er startet med "
        "`python src/main.py`. Dashboardet starter ingen permanent løkke."
    )
    selected = get_selected_website_id()
    filter_selected = st.checkbox("Vis kun det aktive website", value=False)
    database = open_database()
    try:
        _render_import(database)
        rows = database.get_recent_sales(limit=500)
    finally:
        database.close()
    if filter_selected and selected:
        rows = [row for row in rows if row.get("website") == selected]
    if not rows:
        st.info("Ingen salg matcher valget. Importér Partner Ads-data eller skift filter.")
    else:
        render_table(rows, columns={
            "dato": "Dato", "tidspunkt": "Tid", "website": "Website",
            "omsaetning": "Omsætning", "provision": "Provision", "url": "URL",
        })


def _render_import(database) -> None:
    result = st.session_state.pop("partner_ads_import_result", None)
    error = st.session_state.pop("partner_ads_import_error", None)
    if result:
        st.success("Partner Ads-data er opdateret")
        columns = st.columns(4)
        columns[0].metric("Hentede salg", result["fetched"])
        columns[1].metric("Nye salg", result["new"])
        columns[2].metric("Allerede kendte salg", result["duplicates"])
        columns[3].metric(
            "Telegram-beskeder sendt", result["telegram_sent"]
        )
        st.caption(
            "Seneste opdatering: " + format_datetime(result["completed_at"])
        )
    if error:
        st.error(error["message"])
        with st.expander("Tekniske detaljer"):
            st.code(error["type"])
    if st.button("Hent Partner Ads-data", type="primary"):
        progress = st.progress(10, text="Forbereder Partner Ads-kontrol…")
        try:
            progress.progress(35, text="Henter de nyeste salg…")
            imported = execute_partner_ads_check(database)
            progress.progress(100, text="Kontrollen er færdig.")
            st.session_state["partner_ads_import_result"] = imported
        except Exception as exc:
            database.set_system_status("partner_ads", False)
            st.session_state["partner_ads_import_error"] = {
                "message": "Partner Ads-importen fejlede: " + safe_error_detail(exc),
                "type": type(exc).__name__,
            }
        st.rerun()


if __name__ == "__main__":
    main()
