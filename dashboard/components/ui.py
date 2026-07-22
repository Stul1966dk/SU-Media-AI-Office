"""Reusable Streamlit presentation helpers."""

from html import escape
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
    """Render the one fixed, Danish navigation menu on every page."""
    pages = (
        ("pages/15_Dagens_Arbejde.py", "Aktuel opgave", ":material/today:"),
        ("app.py", "Dashboard", ":material/dashboard:"),
        ("pages/3_Executive_Briefing.py", "Executive Briefing", ":material/strategy:"),
        ("pages/6_AI_Analyst.py", "AI Analyst", ":material/psychology:"),
        ("pages/11_Websites.py", "Websites", ":material/public:"),
        (
            "pages/1_Website_Profile.py",
            "Website Profile",
            ":material/language:",
        ),
        ("pages/4_Website_Discovery.py", "Website Discovery", ":material/travel_explore:"),
        ("pages/5_Content_Explorer.py", "Content Explorer", ":material/article:"),
        ("pages/9_SEO.py", "SEO", ":material/query_stats:"),
        ("pages/13_Eksperimenter.py", "Eksperimenter", ":material/science:"),
        ("pages/16_SEO_Laering.py", "SEO-læring", ":material/school:"),
        ("pages/14_Title_Optimering.py", "Title optimering", ":material/title:"),
        ("pages/2_Projekter.py", "Projekter", ":material/folder:"),
        ("pages/8_Opgaver.py", "Opgaver", ":material/checklist:"),
        ("pages/10_Partner_Ads.py", "Partner Ads", ":material/payments:"),
        ("pages/0_Kom_godt_i_gang.py", "Kom godt i gang", ":material/route:"),
        ("pages/12_Systemstatus.py", "Systemstatus", ":material/monitor_heart:"),
        (
            "pages/7_Indstillinger.py",
            "Indstillinger",
            ":material/settings:",
        ),
    )
    try:
        if show_website_selector:
            from dashboard.components.website_selector import render_website_selector
            render_website_selector()
            st.sidebar.divider()
        for path, label, icon in pages:
            st.sidebar.page_link(path, label=label, icon=icon)
    except KeyError:
        st.sidebar.markdown(
            "\n".join(
                f"- [{label}]({path})" for path, label, _ in pages
            )
        )


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
        use_container_width=True,
        hide_index=True,
    )


def render_page_link(path: str, label: str) -> None:
    """Render an internal page link in app and bare Streamlit tests."""
    try:
        st.page_link(path, label=label)
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
