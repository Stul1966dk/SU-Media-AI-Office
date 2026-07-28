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
from dashboard.components.website_selector import (
    get_selected_website_id,
    set_selected_website,
)


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
        actions=(
            "Vælg et website for at aktivere eller deaktivere det, eller klik "
            "på en række for at åbne Website Profile."
        ),
        limitations=(
            "Statusændringer kræver bekræftelse og sletter ingen historiske data."
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
            rows.append({
                "Website": website_id,
                "Status": "active" if website["active"] else "inactive",
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
    options = [website["website"] for website in websites]
    current = get_selected_website_id()
    managed_id = st.selectbox(
        "Administrér website",
        options,
        index=options.index(current) if current in options else 0,
    )
    managed = next(
        website for website in websites if website["website"] == managed_id
    )
    is_active = bool(managed["active"])
    st.write(f"**Aktuel status:** {'Aktiv' if is_active else 'Inaktiv'}")
    pending = st.session_state.get("website_status_confirmation")
    if pending and pending["website"] == managed_id:
        target_active = bool(pending["active"])
        target_label = "aktivere" if target_active else "deaktivere"
        st.warning(
            f"Bekræft, at du vil {target_label} {managed_id}. "
            "Historiske data bliver bevaret."
        )
        confirm, cancel = st.columns(2)
        if confirm.button(
            "Bekræft aktivering" if target_active
            else "Bekræft deaktivering",
            type="primary",
        ):
            database = open_database()
            try:
                changed = database.set_website_active(
                    managed_id, target_active
                )
            finally:
                database.close()
            st.session_state.pop("website_status_confirmation", None)
            if not changed:
                st.error("Websitet kunne ikke findes.")
            else:
                st.success(
                    f"{managed_id} er nu "
                    f"{'aktivt' if target_active else 'inaktivt'}."
                )
                st.rerun()
        if cancel.button("Annuller"):
            st.session_state.pop("website_status_confirmation", None)
            st.rerun()
    elif st.button(
        "Deaktivér website" if is_active else "Aktivér website",
        type="secondary",
    ):
        st.session_state["website_status_confirmation"] = {
            "website": managed_id,
            "active": not is_active,
        }
        st.rerun()

    st.subheader("Vælg de websites AI Office skal arbejde med")
    manageable = [
        website for website in websites
        if website.get("status") in {"active", "inactive"}
    ]
    manageable_ids = [website["website"] for website in manageable]
    active_ids = [
        website["website"] for website in manageable if website["active"]
    ]
    selected_active_ids = st.multiselect(
        "Aktive websites",
        manageable_ids,
        default=active_ids,
        help=(
            "Kun valgte websites bruges ved fremtidige synkroniseringer, "
            "analyser og nye anbefalinger. Historiske data bevares."
        ),
    )
    st.caption(
        f"{len(selected_active_ids)} af {len(manageable_ids)} websites valgt. "
        "Websites under udfasning administreres ikke her."
    )
    if st.button("Bekræft og gem aktive websites", type="primary"):
        database = open_database()
        try:
            changed_count = database.set_active_website_ids(
                set(selected_active_ids)
            )
        finally:
            database.close()
        st.session_state.pop("website_status_confirmation", None)
        st.success(
            f"Aktivt udvalg er gemt. {changed_count} websites blev ændret."
        )
        st.rerun()

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
