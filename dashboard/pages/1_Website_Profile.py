"""Read-only Website Intelligence profile page."""

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from dashboard.components.ui import load_styles, render_sidebar, render_table


def main() -> None:
    """Render one selected website's unified intelligence profile."""
    st.set_page_config(
        page_title="Website Profile · SU Media AI Office",
        page_icon="🌐",
        layout="wide",
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Website Profile")

    database = open_database()
    try:
        profiles = database.get_website_profiles()
        if not profiles:
            st.caption("Ingen data.")
            return
        labels = {
            item["website_id"]: (
                f"{item['display_name']} · Health {item['website_health']:.1f}"
            )
            for item in profiles
        }
        website_id = st.selectbox(
            "Vælg website",
            options=list(labels),
            format_func=labels.get,
        )
        detail = database.get_website_profile_detail(website_id)
    finally:
        database.close()

    if detail is None:
        st.caption("Ingen data.")
        return
    _render_profile(detail)
    _render_seo(detail)
    _render_revenue(detail)
    _render_history(detail)
    _render_projects(detail)
    _render_tasks(detail)
    _render_recommendations(detail)


def _render_profile(detail: dict[str, Any]) -> None:
    profile = detail["profile"]
    st.subheader("Profil")
    health, status, niche = st.columns(3)
    health.metric("Website health", f"{profile['website_health']:.1f}")
    status.metric("Status", profile["status"])
    niche.metric("Niche", profile["niche"])
    left, right = st.columns(2)
    with left:
        st.write(f"**CMS:** {profile['cms']}")
        st.write(f"**Tema:** {profile['theme']}")
        st.write(f"**Monetization:** {profile['monetization']}")
    with right:
        st.write("**Stærke områder**")
        _render_list(profile["strong_areas"])
        st.write("**Svage områder**")
        _render_list(profile["weak_areas"])
    st.write("**Vigtigste kategorier**")
    render_table(
        detail["categories"],
        columns={
            "category": "Kategori",
            "category_type": "Type",
            "rank": "Prioritet",
        },
    )


def _render_seo(detail: dict[str, Any]) -> None:
    st.subheader("SEO")
    statistics = detail["statistics"]
    if not statistics:
        st.caption("Ingen data.")
        return
    values = (
        ("Klik", statistics["search_clicks"]),
        ("Visninger", statistics["search_impressions"]),
        ("CTR", f"{statistics['search_ctr'] * 100:.2f}%"),
        ("Placering", _number(statistics["average_position"])),
        ("SEO-score", _number(statistics["seo_score"])),
        ("Trend", statistics["seo_trend"] or "Ingen data."),
    )
    for start in (0, 3):
        for column, (label, value) in zip(
            st.columns(3),
            values[start : start + 3],
        ):
            column.metric(label, value)


def _render_revenue(detail: dict[str, Any]) -> None:
    st.subheader("Provision")
    statistics = detail["statistics"]
    if not statistics:
        st.caption("Ingen data.")
        return
    sales, revenue, commission = st.columns(3)
    sales.metric("Antal salg", statistics["sales_count"])
    revenue.metric("Omsætning", _currency(statistics["revenue"]))
    commission.metric("Provision", _currency(statistics["commission"]))


def _render_history(detail: dict[str, Any]) -> None:
    st.subheader("Historik")
    rows = [
        {
            "history_date": item["history_date"],
            "changed_fields": ", ".join(item["changed_fields"]),
            "updated_at": item["updated_at"],
        }
        for item in detail["history"]
    ]
    render_table(
        rows,
        columns={
            "history_date": "Dato",
            "changed_fields": "Ændringer",
            "updated_at": "Opdateret",
        },
    )


def _render_projects(detail: dict[str, Any]) -> None:
    st.subheader("Aktive projekter")
    render_table(
        detail["active_projects"],
        columns={
            "title": "Projekt",
            "status": "Status",
            "priority": "Prioritet",
            "expected_effect": "Forventet effekt",
        },
    )


def _render_tasks(detail: dict[str, Any]) -> None:
    st.subheader("Aktive opgaver")
    render_table(
        detail["active_tasks"],
        columns={
            "project": "Projekt",
            "title": "Opgave",
            "assigned_agent": "Ansvarlig agent",
            "priority_score": "Prioritet",
            "estimated_minutes": "Tid",
            "status": "Status",
        },
    )


def _render_recommendations(detail: dict[str, Any]) -> None:
    st.subheader("AI-anbefalinger")
    _render_list(detail["profile"]["ai_recommendations"])


def _render_list(items: list[str]) -> None:
    if not items:
        st.caption("Ingen data.")
        return
    for item in items:
        st.markdown(f"- {item}")


def _currency(value: Any) -> str:
    amount = Decimal(str(value))
    formatted = f"{amount:,.2f}".translate(
        str.maketrans({",": ".", ".": ","})
    )
    return f"{formatted} kr."


def _number(value: Any) -> str:
    return "Ingen data." if value is None else f"{float(value):.2f}"


if __name__ == "__main__":
    main()
