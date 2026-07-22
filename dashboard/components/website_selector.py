"""Shared active-website state for all Streamlit pages."""

from typing import Any

import streamlit as st

from dashboard.components.database import open_database


SESSION_KEY = "selected_website_id"
IGNORED_STATUSES = {"phasing_out", "archived", "cancelled"}


def get_selected_website_id() -> str | None:
    """Return the globally selected website ID."""
    value = st.session_state.get(SESSION_KEY)
    return str(value) if value else None


def set_selected_website(website: str | dict[str, Any] | None) -> None:
    """Store the global choice from an ID or website record."""
    if website is None:
        st.session_state.pop(SESSION_KEY, None)
        return
    website_id = website.get("website") if isinstance(website, dict) else website
    st.session_state[SESSION_KEY] = str(website_id)


def get_selected_website(database: Any | None = None) -> dict[str, Any] | None:
    """Return the selected website record through Database methods."""
    website_id = get_selected_website_id()
    if not website_id:
        return None
    owned = database is None
    database = database or open_database()
    try:
        return database.get_website(website_id)
    finally:
        if owned:
            database.close()


def render_website_selector(
    database: Any | None = None,
    *,
    label: str = "Aktivt website",
    key: str = "global_website_selector",
) -> str | None:
    """Render active websites and persist selection across page changes."""
    owned = database is None
    database = database or open_database()
    try:
        websites = [
            item for item in database.get_all_websites()
            if item["active"] and item["status"] not in IGNORED_STATUSES
        ]
    finally:
        if owned:
            database.close()
    options = [item["website"] for item in websites]
    current = get_selected_website_id()
    if current not in options:
        current = options[0] if options else None
        set_selected_website(current)
    if not options:
        st.sidebar.markdown("Aktivt website: **Ingen aktive websites**")
        return None
    selected = st.sidebar.selectbox(
        label, options, index=options.index(current), key=key
    )
    if selected != current:
        set_selected_website(selected)
    st.sidebar.caption(f"Du arbejder med: **{selected}**")
    return selected
