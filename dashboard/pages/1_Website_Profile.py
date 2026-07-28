"""Read-only Website Intelligence profile page."""

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from dashboard.components.help_panel import render_help_panel
from dashboard.components.formatting import format_currency, format_status
from dashboard.components.ui import (
    load_styles, render_next_step, render_sidebar, render_table,
)
from dashboard.components.website_selector import (
    get_selected_website_id,
    set_selected_website,
)


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
    st.write(
        "Her ser du status og udvikling for ét website. Selve arbejdet "
        "udføres fra I dag."
    )
    render_help_panel(
        purpose="Se status og udvikling for ét website.",
        requirements="Website Registry og helst Discovery, Search Console og Intelligence.",
        actions="Vælg et website, kontrollér status og fortsæt til I dag.",
        limitations="Siden er read-only og ændrer ikke websitet.",
    )

    database = open_database()
    try:
        active_ids = {
            item["website"] for item in database.get_all_websites()
            if item["active"] and item["status"] not in
            {"phasing_out", "archived", "cancelled"}
        }
        profiles = [
            item for item in database.get_website_profiles()
            if item["website_id"] in active_ids
        ]
        if not profiles:
            st.caption("Ingen data.")
            st.info(
                "Der findes ingen websiteprofiler. Registrér websites og kør "
                "Website Discovery og Website Intelligence først."
            )
            return
        labels = {
            item["website_id"]: (
                f"{item['display_name']} · Health {item['website_health']:.1f}"
            )
            for item in profiles
        }
        options = list(labels)
        current = get_selected_website_id()
        website_id = st.selectbox(
            "Vælg website",
            options=options,
            index=options.index(current) if current in options else 0,
            format_func=labels.get,
            help="Skifter alle oplysninger på siden til det valgte website.",
        )
        set_selected_website(website_id)
        detail = database.get_website_profile_detail(website_id)
        if detail:
            detail["discovery"] = database.get_website_discovery_profile(
                website_id
            )
            detail["content"] = database.get_content(website_id)
            detail["plausible"] = database.get_plausible_daily_metrics(
                website_id=website_id
            )
    finally:
        database.close()

    if detail is None:
        st.info("Websiteprofilen kunne ikke findes. Kør Website Intelligence.")
        return
    st.success(f"Du ser nu data for {website_id}")
    _render_profile(detail)
    _render_revenue(detail)
    _render_plausible(detail)
    _render_seo(detail)
    render_next_step(
        text=(
            "Status er samlet. Fortsæt til I dag for at se den vigtigste "
            "konkrete opgave for websitet."
        ),
        path="app.py",
        label="Gå til I dag",
    )
    with st.expander("Se tekniske og historiske detaljer"):
        st.caption(
            "Disse oplysninger er dokumentation og behøver normalt ikke "
            "kontrolleres i det daglige."
        )
        _render_technical(detail)
        _render_content(detail)
        _render_projects(detail)
        _render_tasks(detail)
        _render_recommendations(detail)


def _render_profile(detail: dict[str, Any]) -> None:
    profile = detail["profile"]
    st.subheader("Overblik")
    health, status, niche = st.columns(3)
    health.metric("Website health", f"{profile['website_health']:.1f}")
    status.metric("Status", format_status(profile["status"]))
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
        st.info(
            "Ingen SEO-data endnu. Hent Search Console-data og kør Website Intelligence."
        )
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
    st.subheader("Indtjening")
    statistics = detail["statistics"]
    if not statistics:
        st.info(
            "Ingen indtjeningsdata endnu. Importér Partner Ads-salg og kør "
            "Website Intelligence."
        )
        return
    sales, revenue, commission = st.columns(3)
    sales.metric("Antal salg", statistics["sales_count"])
    revenue.metric("Omsætning", _currency(statistics["revenue"]))
    commission.metric("Provision", _currency(statistics["commission"]))


def _render_plausible(detail: dict[str, Any]) -> None:
    st.subheader("Trafik (Plausible)")
    metrics = summarize_plausible_visitors(detail.get("plausible") or [])
    if metrics is None:
        st.info("Ingen Plausible-data fundet.")
        return
    yesterday, seven_days, thirty_days = st.columns(3)
    yesterday.metric("Besøgende i går", metrics["yesterday"])
    seven_days.metric("Besøgende seneste 7 dage", metrics["last_7_days"])
    thirty_days.metric("Besøgende seneste 30 dage", metrics["last_30_days"])
    change_7, change_30 = st.columns(2)
    change_7.metric(
        "Ændring mod foregående 7 dage",
        format_plausible_change(metrics["change_7_days"]),
    )
    change_30.metric(
        "Ændring mod foregående 30 dage",
        format_plausible_change(metrics["change_30_days"]),
    )


def summarize_plausible_visitors(
    rows: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> dict[str, int | float | None] | None:
    """Summarize stored daily visitors through yesterday."""
    if not rows:
        return None
    reference = today or date.today()
    yesterday = reference - timedelta(days=1)
    visitors_by_date: dict[date, int] = {}
    for row in rows:
        try:
            metric_date = date.fromisoformat(str(row["metric_date"])[:10])
            visitors_by_date[metric_date] = int(row["visitors"])
        except (KeyError, TypeError, ValueError):
            continue
    return {
        "yesterday": visitors_by_date.get(yesterday, 0),
        "last_7_days": sum(
            visitors_by_date.get(yesterday - timedelta(days=offset), 0)
            for offset in range(7)
        ),
        "last_30_days": sum(
            visitors_by_date.get(yesterday - timedelta(days=offset), 0)
            for offset in range(30)
        ),
        "change_7_days": _plausible_period_change(
            visitors_by_date, yesterday, 7
        ),
        "change_30_days": _plausible_period_change(
            visitors_by_date, yesterday, 30
        ),
    }


def _plausible_period_change(
    visitors_by_date: dict[date, int],
    period_end: date,
    days: int,
) -> float | None:
    """Compare two complete, adjacent periods without overlap."""
    current_dates = {
        period_end - timedelta(days=offset) for offset in range(days)
    }
    previous_dates = {
        period_end - timedelta(days=offset)
        for offset in range(days, days * 2)
    }
    if not current_dates.issubset(visitors_by_date):
        return None
    if not previous_dates.issubset(visitors_by_date):
        return None
    current = sum(visitors_by_date[item] for item in current_dates)
    previous = sum(visitors_by_date[item] for item in previous_dates)
    if previous == 0:
        return None
    return (current - previous) / previous * 100


def format_plausible_change(value: float | None) -> str:
    """Format a period change with one decimal and a neutral zero label."""
    if value is None:
        return "Ikke nok data"
    if round(value, 1) == 0:
        return "0,0 % · Uændret"
    return f"{value:+.1f} %".replace(".", ",")


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


def _render_technical(detail: dict[str, Any]) -> None:
    st.subheader("Teknisk profil")
    profile = detail.get("discovery")
    if not profile:
        st.info(
            "Ingen teknisk profil endnu. Gå til Website Discovery og scan websitet."
        )
        return
    st.write(f"**CMS:** {profile['cms']}")
    st.write(f"**Tema:** {profile['theme']}")
    st.write(f"**HTTPS:** {'Ja' if profile['https_enabled'] else 'Nej'}")
    st.write(f"**Sitemap:** {format_status(profile['sitemap_status'])}")


def _render_content(detail: dict[str, Any]) -> None:
    st.subheader("Indhold")
    content = detail.get("content") or []
    if not content:
        st.info(
            "Intet indhold er importeret. Brug Content Explorer til at hente "
            "offentligt indhold."
        )
        return
    st.metric("Importerede indholdselementer", len(content))


def _render_projects(detail: dict[str, Any]) -> None:
    st.subheader("Aktive projekter")
    if not detail["active_projects"]:
        st.info(
            "Der er ingen aktive projekter. Opret først et projekt efter "
            "godkendelse af en anbefaling."
        )
        return
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
    st.subheader("Åbne opgaver")
    if not detail["active_tasks"]:
        st.info(
            "Der er ingen åbne opgaver. Opgaver oprettes under et godkendt projekt."
        )
        return
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
    st.subheader("Seneste AI-anbefalinger")
    _render_list(detail["profile"]["ai_recommendations"])


def _render_list(items: list[str]) -> None:
    if not items:
        st.info("Ingen anbefalinger endnu. Kør AI Analyst for websitet.")
        return
    for item in items:
        st.markdown(f"- {item}")


def _currency(value: Any) -> str:
    return format_currency(value)


def _number(value: Any) -> str:
    return "Ingen data." if value is None else f"{float(value):.2f}"


if __name__ == "__main__":
    main()
