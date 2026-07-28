"""Operational overview and activation control for registered websites."""

import sys
from datetime import date
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from dashboard.components.formatting import format_rows
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_sidebar


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
        purpose="Giv et samlet drifts- og resultatblik på registrerede websites.",
        requirements=(
            "Websites skal være registreret; øvrige kolonner udfyldes af "
            "importer."
        ),
        actions=(
            "Sæt eller fjern fluebenet i kolonnen Aktiv, og gem derefter "
            "ændringerne."
        ),
        limitations=(
            "Deaktivering stopper fremtidig behandling, men sletter ingen "
            "historiske data."
        ),
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
            manageable = website.get("status") in {"active", "inactive"}
            rows.append({
                "Aktiv": bool(website["active"]) and manageable,
                "Website": website_id,
                "Status": website.get("status", "inactive"),
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
                    discoveries.get(website_id, {}).get(
                        "scanned_at", "Ikke kørt"
                    )
                ),
            })
    finally:
        database.close()

    if not rows:
        st.info(
            "Ingen websites er registreret. Tilføj først et website i registry."
        )
        return

    st.subheader("Vælg de websites AI Office skal arbejde med")
    st.caption(
        "Sæt flueben ved de websites, der skal indgå i fremtidige "
        "synkroniseringer, analyser og anbefalinger. Du kan altid sætte "
        "fluebenet igen senere."
    )
    manageable_rows = [
        row for row, website in zip(rows, websites)
        if website.get("status") in {"active", "inactive"}
    ]
    formatted_rows = format_rows(manageable_rows)
    edited_rows = st.data_editor(
        formatted_rows,
        width="stretch",
        hide_index=True,
        disabled=[
            column for column in formatted_rows[0] if column != "Aktiv"
        ],
        column_config={
            "Aktiv": st.column_config.CheckboxColumn(
                "Aktiv",
                help="Slå behandling af websitet til eller fra.",
                default=False,
            ),
        },
        key="website_active_editor",
    )
    active_count = sum(bool(row["Aktiv"]) for row in edited_rows)
    st.caption(f"{active_count} af {len(edited_rows)} websites er valgt.")

    if st.button("Gem aktive websites", type="primary"):
        selected_active_ids = {
            str(row["Website"])
            for row in edited_rows
            if bool(row["Aktiv"])
        }
        current_active = {
            str(website["website"]): bool(website["active"])
            for website in websites
            if website.get("status") in {"active", "inactive"}
        }
        database = open_database()
        try:
            changed_count = 0
            for website_id, was_active in current_active.items():
                should_be_active = website_id in selected_active_ids
                if was_active != should_be_active:
                    changed_count += int(database.set_website_active(
                        website_id, should_be_active
                    ))
        finally:
            database.close()
        st.success(
            f"Aktivt udvalg er gemt. {changed_count} websites blev ændret."
        )
        st.rerun()

    excluded_rows = [
        row for row, website in zip(rows, websites)
        if website.get("status") not in {"active", "inactive"}
    ]
    if excluded_rows:
        with st.expander(
            f"Websites under udfasning eller arkiveret ({len(excluded_rows)})"
        ):
            st.dataframe(
                format_rows(excluded_rows),
                width="stretch",
                hide_index=True,
            )


if __name__ == "__main__":
    main()
