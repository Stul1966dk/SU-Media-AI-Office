"""Central integration settings and connection tests."""

import sys
import os
from pathlib import Path
from typing import Callable

import streamlit as st
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from dashboard.components.formatting import format_datetime
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_sidebar
from core.sync_status import load_sync_status
from core.integration_retry import (
    FailedIntegrationRetryService, retry_plan,
)
from core.refresh_status import result_status, status_label
from integrations.search_console import SearchConsoleAuthenticationError
from integrations.plausible_integration import PlausibleIntegration
from integrations.search_console_integration import SearchConsoleIntegration


def main() -> None:
    st.set_page_config(
        page_title="Integrationer · Indstillinger",
        page_icon="🔌",
        layout="wide",
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar(show_website_selector=False)
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    st.title("Integrationer")
    render_help_panel(
        purpose="Administrér appens fælles forbindelser til eksterne tjenester.",
        requirements="De relevante lokale API- og OAuth-oplysninger.",
        actions="Forbind, forny, afbryd eller test en integration.",
        limitations="Afbrydelse sletter ikke allerede importerede data.",
    )
    st.header("Integrationer")
    database = open_database()
    try:
        _render_search_console(SearchConsoleIntegration(PROJECT_ROOT, database))
        _render_plausible(PlausibleIntegration(database))
        _render_failed_retry(database)
        _render_sync_status(load_sync_status(database))
    finally:
        database.close()


def _render_plausible(integration: PlausibleIntegration) -> None:
    st.subheader("Plausible-forbindelse")
    st.caption(
        "Kontrollerer automatisk Stats API-adgang for alle aktive websites. "
        "Testen læser kun gårsdagens samlede besøgstal."
    )
    configured_token = bool(
        os.getenv("PLAUSIBLE_API_KEY", "").strip()
        or os.getenv("PLAUSIBLE_API_TOKEN", "").strip()
    )
    active_count = len([
        item for item in integration.database.get_all_websites()
        if item.get("active") and item.get("status") not in
        {"phasing_out", "archived", "cancelled"}
    ])
    token_col, websites_col = st.columns(2)
    token_col.metric(
        "API-token", "Konfigureret" if configured_token else "Mangler"
    )
    websites_col.metric("Aktive websites", active_count)
    if not active_count:
        st.warning("Der er ingen aktive websites at teste med.")
    if st.button(
        "Test alle websites i Plausible",
        disabled=not configured_token or not active_count,
    ):
        st.session_state["plausible_stats_test"] = (
            integration.test_active_websites()
        )
        st.rerun()

    result = st.session_state.get("plausible_stats_test")
    if result and "results" not in result:
        st.session_state.pop("plausible_stats_test", None)
        result = None
    if not result:
        st.info("Forbindelsen er ikke testet endnu.")
        return
    if result["ok"]:
        st.success(f"Alle {result['tested']} websites har forbindelse.")
    else:
        st.error(
            f"{result['failed']} af {result['tested']} websites fejlede."
        )
    st.dataframe(
        [
            {
                "Website": item["website"],
                "Status": "OK" if item["ok"] else "Fejl",
                "Besked": item["message"],
                "Besøgende i går": (
                    item["visitors"] if item["visitors"] is not None else ""
                ),
            }
            for item in result["results"]
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"Kontrolleret dato: {result['date']}")


def _render_search_console(integration: SearchConsoleIntegration) -> None:
    st.subheader("Google Search Console")
    st.caption(
        "Properties, der er slettet i Google Search Console, markeres "
        "automatisk inaktive ved næste dataopdatering. Historiske data "
        "bevares og de inaktive properties synkroniseres ikke."
    )
    status = integration.status(validate=False)
    if status["connected"] and status["last_error"]:
        state_label = "Kræver ny forbindelse"
    elif status["connected"]:
        state_label = "Forbundet"
    else:
        state_label = "Ikke forbundet"

    status_col, account_col, sync_col = st.columns(3)
    status_col.metric("Status", state_label)
    account_col.metric(
        "Tilknyttet konto",
        status["account"] or (
            "Forbind igen for at vise konto"
            if status["connected"] else "Ingen"
        ),
    )
    sync_col.metric(
        "Seneste synkronisering",
        format_datetime(status["latest_sync"])
        if status["latest_sync"] else "Aldrig",
    )
    if status["last_error"]:
        st.error("Google-forbindelsen skal godkendes igen.")
        st.caption(status["last_error"])

    connect_col, reconnect_col, disconnect_col, test_col = st.columns(4)
    if connect_col.button(
        "Forbind", type="primary", disabled=status["connected"],
        use_container_width=True,
    ):
        _run_connection_action(integration.connect)
    if reconnect_col.button(
        "Forbind igen", disabled=not status["connected"],
        use_container_width=True,
    ):
        _run_connection_action(integration.reconnect)
    if disconnect_col.button(
        "Afbryd", disabled=not status["connected"],
        use_container_width=True,
    ):
        try:
            integration.disconnect()
        except SearchConsoleAuthenticationError as error:
            message = ("error", str(error))
        else:
            message = ("success", "Google Search Console er afbrudt.")
        st.session_state["search_console_connection_message"] = message
        st.rerun()
    if test_col.button(
        "Test alle websites",
        disabled=not status["connected"],
        use_container_width=True,
    ):
        st.session_state["search_console_connection_test"] = (
            integration.test_active_websites()
        )
        st.rerun()

    message = st.session_state.pop(
        "search_console_connection_message", None
    )
    if message:
        getattr(st, message[0])(message[1])
    test_result = st.session_state.get("search_console_connection_test")
    if test_result:
        if test_result["ok"]:
            st.success(
                f"Alle {test_result['tested']} websites har adgang."
            )
        else:
            st.error(
                f"{test_result['failed']} af {test_result['tested']} "
                "websites fejlede."
            )
        st.dataframe(
            [
                {
                    "Website": item["website"],
                    "Status": "OK" if item["ok"] else "Fejl",
                    "Besked": item["message"],
                }
                for item in test_result["results"]
            ],
            use_container_width=True,
            hide_index=True,
        )
    properties = integration.database.get_search_console_properties()
    if properties:
        with st.expander("Lokale Search Console-properties"):
            st.dataframe(
                [
                    {
                        "Property": item["site_url"],
                        "Website": item.get("website_id") or "Ikke matchet",
                        "Status": (
                            "Aktiv" if item.get("active") else "Fjernet i Google"
                        ),
                    }
                    for item in properties
                ],
                use_container_width=True,
                hide_index=True,
            )
    st.divider()


def _render_sync_status(model: dict) -> None:
    st.header("Synkroniseringsstatus")
    overall = model["overall_status"]
    if overall == "Alle integrationer fungerer":
        st.success(overall)
    elif overall == "Ingen synkronisering er kørt endnu":
        st.info(overall)
    elif overall == "Synkronisering gennemført med advarsler":
        st.warning(overall)
    else:
        st.error(overall)
    st.caption(
        "Status læses fra seneste gemte synkronisering. Manuel opdatering "
        "foretages fra Dashboard under Opdater alle data."
    )
    for item in model["items"]:
        with st.container(border=True):
            st.subheader(item["label"])
            st.write(f"Status: **{item['status']}**")
            fields = (
                ("Seneste forsøg", item.get("last_attempt")),
                ("Seneste succes", item.get("last_success")),
                ("Importtype", item.get("import_type")),
                ("Startdato", item.get("start_date")),
                ("Slutdato", item.get("end_date")),
                ("Behandlede websites/properties", item.get("processed")),
                ("Websites/properties med fejl", item.get("failed")),
                ("Oprettede rækker", item.get("rows_created")),
                ("Opdaterede rækker", item.get("rows_updated")),
                ("Oversprungne elementer", item.get("skipped")),
                ("Næste nødvendige opdatering", item.get("next_update")),
            )
            columns = st.columns(3)
            for index, (label, value) in enumerate(fields):
                if value is not None:
                    columns[index % 3].metric(label, value)
            if item.get("message"):
                st.warning(str(item["message"]))
            details = item.get("details") or []
            if details and item["key"] in {
                "search_console_daily",
                "search_console_dimensions",
                "plausible",
            }:
                with st.expander(
                    f"Detaljer pr. "
                    f"{'website' if item['key'] == 'plausible' else 'property'}"
                ):
                    st.dataframe(
                        [_detail_row(detail) for detail in details],
                        use_container_width=True,
                        hide_index=True,
                    )


def _render_failed_retry(database) -> None:
    previous = database.get_last_data_refresh_result()
    plan = retry_plan(previous)
    stored_result = st.session_state.get("integration_retry_result")
    if plan["has_concrete_failures"]:
        if st.button(
            "Genkør fejlede integrationer",
            type="primary",
            use_container_width=True,
        ):
            with st.spinner("Genkører kun konkrete fejl…"):
                stored_result = FailedIntegrationRetryService(
                    database, project_root=PROJECT_ROOT
                ).retry()
            st.session_state["integration_retry_result"] = stored_result
            st.rerun()
    elif result_status(previous) in {"warning", "error"}:
        st.info("Ingen konkrete fejl kan genkøres automatisk")

    if not stored_result:
        return
    status = stored_result.get("status", "skipped")
    message = status_label(status)
    if status == "success":
        st.success(f"Genkørsel: {message}")
    elif status == "warning":
        st.warning(f"Genkørsel: {message}")
    elif status == "error":
        st.error(f"Genkørsel: {message}")
    else:
        st.info(stored_result.get(
            "message", "Ingen konkrete fejl kan genkøres automatisk"
        ))
    st.caption(
        "Kørt: " + format_datetime(stored_result.get("completed_at"))
    )
    rows = []
    for item in stored_result.get("integrations", []):
        targets = item.get("properties") or item.get("websites") or []
        rows.append({
            "Integration": item.get("step"),
            "Behandlede websites/properties": ", ".join(targets)
            if targets else "Fælles integration",
            "Status": status_label(item.get("status", "skipped")),
            "Fejl": item.get("error_message") or "",
        })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)


def _detail_row(detail: dict) -> dict:
    return {
        "Website/property": (
            detail.get("website_id") or detail.get("website")
            or detail.get("property") or "Ikke registreret"
        ),
        "Status": detail.get("status") or "Ikke registreret",
        "Startdato": (
            detail.get("start_date") or "Ikke registreret"
        ),
        "Slutdato": detail.get("end_date") or "Ikke registreret",
        "Oprettede rækker": detail.get("rows_created", "Ikke registreret"),
        "Opdaterede rækker": detail.get("rows_updated", "Ikke registreret"),
        "Fejl/årsag": (
            detail.get("error") or detail.get("reason")
            or "Ikke registreret"
        ),
    }


def _run_connection_action(action: Callable[[], object]) -> None:
    try:
        action()
    except SearchConsoleAuthenticationError as error:
        message = ("error", str(error))
    else:
        message = ("success", "Google Search Console er nu forbundet.")
    st.session_state["search_console_connection_message"] = message
    st.rerun()


if __name__ == "__main__":
    main()
