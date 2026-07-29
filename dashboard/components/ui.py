"""Reusable Streamlit presentation helpers."""

from html import escape
import inspect
from pathlib import Path
from typing import Any

import streamlit as st

from dashboard.components.formatting import format_dashboard_value, format_datetime


def load_styles(path: Path) -> None:
    """Load the local dashboard stylesheet."""
    css = path.read_text(encoding="utf-8")
    st.markdown(
        f"<style>\n[data-testid='stSidebarNav']{{display:none;}}\n{css}\n</style>",
        unsafe_allow_html=True,
    )


def render_sidebar(*, show_website_selector: bool = True) -> None:
    """Render the persistent, grouped Danish navigation menu."""
    from dashboard.components.startup_sync import ensure_startup_sync
    ensure_startup_sync()
    primary_pages = (
        ("app.py", "I dag", ":material/today:"),
        ("pages/11_Websites.py", "Websites", ":material/public:"),
        ("pages/13_Eksperimenter.py", "Resultater", ":material/science:"),
        ("pages/19_Portefolje.py", "Portefølje", ":material/dashboard:"),
    )
    groups = (
        (
            "Værktøjer", "tools", ":material/build:",
            (
                (
                    "pages/1_Website_Profile.py", "Websiteprofil",
                    ":material/language:",
                ),
                ("pages/9_SEO.py", "SEO-analyse", ":material/query_stats:"),
                (
                    "pages/14_Title_Optimering.py", "Title-optimering",
                    ":material/title:",
                ),
                (
                    "pages/6_AI_Analyst.py", "AI-analyse",
                    ":material/psychology:",
                ),
                (
                    "pages/4_Website_Discovery.py", "Website Discovery",
                    ":material/travel_explore:",
                ),
                (
                    "pages/5_Content_Explorer.py", "Content Explorer",
                    ":material/article:",
                ),
            ),
        ),
        (
            "Indstillinger", "settings", ":material/settings:",
            (
                (
                    "pages/7_Indstillinger.py", "Oversigt",
                    ":material/settings:",
                ),
                (
                    "pages/18_Integrationer.py", "Integrationer",
                    ":material/cable:",
                ),
                (
                    "pages/20_AI_Retningslinjer.py", "AI-retningslinjer",
                    ":material/psychology:",
                ),
                (
                    "pages/12_Systemstatus.py", "Systemstatus",
                    ":material/monitor_heart:",
                ),
            ),
        ),
    )
    help_pages = (
        (
            "pages/0_Kom_godt_i_gang.py", "Kom godt i gang",
            ":material/route:",
        ),
    )
    active_page = _active_page_filename()
    try:
        if show_website_selector:
            from dashboard.components.website_selector import render_website_selector
            render_website_selector()
            st.sidebar.divider()
        for path, label, icon in primary_pages:
            st.sidebar.page_link(path, label=label, icon=icon)

        for label, key, icon, pages in groups:
            state_key = f"nav_group_open:{key}"
            is_active = active_page in {
                Path(path).name for path, _label, _icon in pages
            }
            if state_key not in st.session_state:
                saved_state = _load_navigation_group_state(key)
                st.session_state[state_key] = (
                    is_active if saved_state is None else saved_state
                )
            elif is_active:
                st.session_state[state_key] = True
            is_open = st.sidebar.toggle(
                label,
                key=state_key,
                on_change=_save_navigation_group_state,
                args=(key, state_key),
            )
            if is_open:
                for path, sublabel, subicon in pages:
                    st.sidebar.page_link(
                        path, label=sublabel, icon=subicon
                    )

        st.sidebar.divider()
        st.sidebar.caption("Hjælp")
        for path, label, icon in help_pages:
            st.sidebar.page_link(path, label=label, icon=icon)
    except KeyError:
        all_pages = [
            *primary_pages,
            *[
                page
                for _label, _key, _icon, pages in groups
                for page in pages
            ],
            *help_pages,
        ]
        st.sidebar.markdown(
            "\n".join(
                f"- [{label}]({path})" for path, label, _ in all_pages
            )
        )


def _active_page_filename() -> str:
    """Identify the Streamlit entrypoint currently rendering the sidebar."""
    dashboard_root = Path(__file__).resolve().parents[1]
    for frame in inspect.stack():
        candidate = Path(frame.filename).resolve()
        if candidate.parent == dashboard_root / "pages":
            return candidate.name
        if candidate == dashboard_root / "app.py":
            return "app.py"
    return ""


def _load_navigation_group_state(group: str) -> bool | None:
    """Load a durable group preference for the local single-user app."""
    try:
        from dashboard.components.database import open_database
        database = open_database()
        try:
            return database.get_navigation_group_state(group)
        finally:
            database.close()
    except Exception:
        return None


def _save_navigation_group_state(group: str, state_key: str) -> None:
    """Persist a changed group preference across browser visits."""
    try:
        from dashboard.components.database import open_database
        database = open_database()
        try:
            database.set_navigation_group_state(
                group, bool(st.session_state.get(state_key))
            )
        finally:
            database.close()
    except Exception:
        return


def render_status(
    label: str, is_ok: bool, detail: str = "",
    checked_at: str = "",
) -> None:
    """Render one accessible system status card."""
    state = "OK" if is_ok else "Fejl"
    css_class = "status-ok" if is_ok else "status-error"
    safe_label = escape(label)
    safe_detail = escape(detail)
    safe_checked_at = escape(
        format_datetime(checked_at, checked_at) if checked_at else ""
    )
    st.markdown(
        (
            f'<div class="status-card {css_class}">'
            f'<span class="status-dot" aria-hidden="true"></span>'
            f"<div><strong>{safe_label}</strong><small>{state}</small>"
            f"<small>{safe_detail}</small>"
            f"<small>Kontrolleret: {safe_checked_at or 'Aldrig'}</small></div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_table(
    rows: list[dict[str, Any]],
    *,
    columns: dict[str, str],
) -> None:
    """Render a database result table or the required empty state."""
    if not rows:
        st.caption("Ingen data.")
        return
    prepared = [
        {
            label: format_dashboard_value(field, row.get(field, ""))
            for field, label in columns.items()
        }
        for row in rows
    ]
    st.dataframe(
        prepared,
        width="stretch",
        hide_index=True,
    )


def render_page_link(path: str, label: str) -> None:
    """Render an internal page link in app and bare Streamlit tests."""
    try:
        st.page_link(path, label=label)
    except KeyError:
        st.markdown(f"[{label}]({path})")


def render_next_step(*, text: str, path: str, label: str) -> None:
    """Keep the user's next meaningful action visible on core pages."""
    st.info(f"**Næste trin:** {text}")
    try:
        st.page_link(
            path,
            label=label,
            icon=":material/arrow_forward:",
        )
    except KeyError:
        st.markdown(f"[{label}]({path})")


def render_placeholder(title: str) -> None:
    """Render an intentionally empty future dashboard page."""
    st.set_page_config(
        page_title=f"{title} · SU Media AI Office",
        page_icon="🏢",
        layout="wide",
    )
    load_styles(Path(__file__).resolve().parents[1] / "assets" / "styles.css")
    render_sidebar()
    st.title(title)
    from dashboard.components.help_panel import render_help_panel
    render_help_panel(
        purpose=f"Her får du overblik over {title.lower()}.",
        requirements="Siden kræver relevante data fra de tidligere arbejdstrin.",
        actions="Brug navigationen til at gennemføre de nødvendige forberedelser.",
        limitations="Siden udfører ikke ændringer uden din udtrykkelige handling.",
    )
    st.info(
        "Denne funktion har endnu ingen data at vise. Følg Kom godt i gang "
        "for at se det næste relevante trin."
    )
