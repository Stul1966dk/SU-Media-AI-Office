"""Reusable Streamlit presentation helpers."""

from pathlib import Path
from typing import Any

import streamlit as st


def load_styles(path: Path) -> None:
    """Load the local dashboard stylesheet."""
    st.markdown(
        f"<style>{path.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    """Render the fixed Sprint 17 navigation menu."""
    pages = (
        ("app.py", "Dashboard", ":material/home:"),
        (
            "pages/1_Website_Profile.py",
            "Website Profile",
            ":material/language:",
        ),
        ("pages/2_Projekter.py", "Projekter", ":material/folder:"),
        ("pages/3_Opgaver.py", "Opgaver", ":material/checklist:"),
        ("pages/4_SEO.py", "SEO", ":material/query_stats:"),
        ("pages/5_Partner_Ads.py", "Partner Ads", ":material/payments:"),
        (
            "pages/6_Indstillinger.py",
            "Indstillinger",
            ":material/settings:",
        ),
    )
    try:
        for path, label, icon in pages:
            st.sidebar.page_link(path, label=label, icon=icon)
    except KeyError:
        st.sidebar.markdown(
            "\n".join(
                f"- [{label}]({path})" for path, label, _ in pages
            )
        )


def render_status(label: str, is_ok: bool) -> None:
    """Render one accessible system status card."""
    state = "OK" if is_ok else "Fejl"
    css_class = "status-ok" if is_ok else "status-error"
    st.markdown(
        (
            f'<div class="status-card {css_class}">'
            f'<span class="status-dot" aria-hidden="true"></span>'
            f"<div><strong>{label}</strong><small>{state}</small></div>"
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
        {label: row.get(field, "") for field, label in columns.items()}
        for row in rows
    ]
    st.dataframe(
        prepared,
        use_container_width=True,
        hide_index=True,
    )


def render_placeholder(title: str) -> None:
    """Render an intentionally empty future dashboard page."""
    st.set_page_config(
        page_title=f"{title} · SU Media AI Office",
        page_icon="🏢",
        layout="wide",
    )
    render_sidebar()
    st.title(title)
    st.caption("Ingen data.")
