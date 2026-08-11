"""Revenue-versus-goal overview grounded in Partner Ads commission."""

import sys
from datetime import date
from pathlib import Path

import altair as alt
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.goal_overview import build_goal_overview
from dashboard.components.database import open_database
from dashboard.components.formatting import format_currency
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import (
    load_styles,
    render_next_step,
    render_sidebar,
    render_table,
)

MONTH_LABELS_DA = (
    "", "jan", "feb", "mar", "apr", "maj", "jun",
    "jul", "aug", "sep", "okt", "nov", "dec",
)

STATUS_TONE = {
    "under": "warning",
    "in_band": "success",
    "over": "success",
    "no_data": "info",
}


def _month_label(year: int, month: int) -> str:
    return f"{MONTH_LABELS_DA[month]} {year}"


def _thousands(value) -> str:
    """Format a whole-krone amount with Danish thousands separators."""
    return f"{int(value):,}".replace(",", ".")


def render_overview_page() -> None:
    st.set_page_config(
        page_title="Overblik",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()

    st.title("Overblik")
    render_help_panel(
        purpose=(
            "Følg indtægten mod målet og se, hvilke websites der driver den."
        ),
        requirements="Gemte Partner Ads-salg i den lokale database.",
        actions="Se udviklingen og fortsæt til den vigtigste opgave på I dag.",
        limitations=(
            "Viser kun Partner Ads-provision i DKK. Andre indtægtskilder "
            "(AdSense, PriceRunner, betalte artikler) er ikke medregnet."
        ),
    )

    database = open_database()
    try:
        records = database.get_commission_records()
    finally:
        database.close()

    overview = build_goal_overview(records, today=date.today())

    if not records:
        st.info(
            "Der er endnu ingen registrerede Partner Ads-salg at vise. "
            "Kør et salgstjek, så udfyldes overblikket automatisk."
        )
        render_next_step(
            text="Fortsæt til I dag for den vigtigste opgave.",
            path="app.py",
            label="Gå til I dag",
        )
        return

    _render_goal(overview)
    _render_history(overview)
    _render_by_website(overview)

    render_next_step(
        text="Fortsæt til I dag for at arbejde på det, der flytter tallet.",
        path="app.py",
        label="Gå til I dag",
    )


def _render_goal(overview) -> None:
    st.subheader("Indtægt mod mål")
    average, this_month = st.columns(2)
    average.metric(
        f"Snit/md. ({overview.months_with_data} mdr.)",
        format_currency(overview.rolling_average),
    )
    this_month.metric(
        "Denne måned",
        format_currency(overview.current_month.total),
        help=f"{overview.current_month.sales} salg i denne måned.",
    )
    st.caption(
        f"Mål: {_thousands(overview.target_low)}–"
        f"{_thousands(overview.target_high)} kr. i gennemsnit pr. måned."
    )

    tone = STATUS_TONE.get(overview.status, "info")
    message = f"**{overview.status_label}.**"
    if overview.status == "no_data":
        message += (
            " Der er endnu ikke nok afsluttede måneder til et pålideligt "
            "gennemsnit."
        )
    else:
        pct = round(overview.progress_to_low * 100)
        months = overview.months_with_data
        period = (
            "den seneste måned"
            if months == 1
            else f"de seneste {months} måneder"
        )
        message += (
            f" Gennemsnittet {period} er {pct}% af målets nedre grænse "
            f"({format_currency(overview.target_low)})."
        )
        st.progress(min(1.0, overview.progress_to_low))
    getattr(st, tone)(message)


def _render_history(overview) -> None:
    st.subheader("Månedlig provision")
    rows = [
        {
            "maaned": _month_label(month.year, month.month),
            "order": index,
            "provision": float(month.total),
            "belob": format_currency(month.total),
        }
        for index, month in enumerate(overview.history)
    ]
    if not any(row["provision"] for row in rows):
        st.caption("Ingen provision i den viste periode.")
        return
    chart = (
        alt.Chart(alt.Data(values=rows))
        .mark_bar()
        .encode(
            x=alt.X(
                "maaned:N",
                sort=alt.SortField(field="order", order="ascending"),
                title="Måned",
            ),
            y=alt.Y(
                "provision:Q",
                title="Provision",
                axis=alt.Axis(format="~s"),
            ),
            tooltip=[
                alt.Tooltip("maaned:N", title="Måned"),
                alt.Tooltip("belob:N", title="Provision"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(chart, use_container_width=True)


def _render_by_website(overview) -> None:
    st.subheader(
        f"Indtægt pr. website (seneste {overview.website_period_months} mdr.)"
    )
    if not overview.by_website:
        st.caption("Ingen salg med kildewebsite i perioden.")
        return
    st.caption(
        "Kilden er url-feltet i hvert Partner Ads-salg. Salg kan stamme fra "
        "både aktive og udfasede websites."
    )
    render_table(
        [
            {
                "website": item.website,
                "provision": item.total,
                "salg": item.sales,
                "andel": f"{round(item.share * 100)} %",
            }
            for item in overview.by_website
        ],
        columns={
            "website": "Website",
            "provision": "Provision",
            "salg": "Salg",
            "andel": "Andel",
        },
    )


if __name__ == "__main__":
    render_overview_page()
