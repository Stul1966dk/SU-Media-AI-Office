"""Operational overview of every registered website."""

import sys
from datetime import date
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from dashboard.components.help_panel import render_help_panel
from dashboard.components.formatting import format_rows
from dashboard.components.ui import load_styles, render_sidebar
from dashboard.components.website_selector import set_selected_website


def _year_commission(sales: list[dict]) -> float:
    year = str(date.today().year)
    return float(sum(
        sale.get("provision", 0) or 0 for sale in sales
        if year in str(sale.get("dato", ""))
    ))


def main() -> None:
    st.set_page_config(page_title="Websites", page_icon="🌐", layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Websites")
    render_help_panel(
        purpose="Giv et samlet drifts- og resultatblik på alle registrerede websites.",
        requirements="Websites skal være registreret; øvrige kolonner udfyldes af importer.",
        actions="Klik på en række for at vælge websitet og åbne Website Profile.",
        limitations="Oversigten ændrer ikke websites eller eksterne systemer.",
    )
    database = open_database()
    try:
        websites = database.get_all_websites()
        properties = {
            row.get("website_id"): row
            for row in database.get_search_console_properties()
            if row.get("website_id")
        }
        discoveries = {
            row["website_id"]: row
            for row in database.get_website_discovery_profiles()
        }
        rows = []
        for website in websites:
            website_id = website["website"]
            source = database.get_website_intelligence_source(website_id) or {}
            seo = source.get("seo_health") or {}
            partner = source.get("partner_ads") or {}
            rows.append({
                "Website": website_id,
                "Status": website.get("status", ""),
                "Monetiseret": "Ja" if website.get("monetized") else "Nej",
                "Prioritet": website.get("priority", ""),
                "Niche": website.get("niche", ""),
                "Search Console": (
                    "Forbundet" if website_id in properties else "Mangler"
                ),
                "SEO Health": seo.get("score", ""),
                "Trend": seo.get("trend", "Ingen data"),
                f"Provision {date.today().year}": _year_commission(
                    partner.get("sales", [])
                ),
                "Aktive projekter": len(source.get("active_projects", [])),
                "Åbne opgaver": len(source.get("active_tasks", [])),
                "Seneste scanning": (
                    discoveries.get(website_id, {}).get("scanned_at", "Ikke kørt")
                ),
            })
    finally:
        database.close()
    if not rows:
        st.info("Ingen websites er registreret. Tilføj først et website i registry.")
        return
    event = st.dataframe(
        format_rows(rows), use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
    )
    selected_rows = getattr(getattr(event, "selection", None), "rows", [])
    if selected_rows:
        set_selected_website(rows[selected_rows[0]]["Website"])
        st.switch_page("pages/1_Website_Profile.py")


if __name__ == "__main__":
    main()
