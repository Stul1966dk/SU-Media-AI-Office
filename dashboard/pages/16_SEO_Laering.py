"""Measured SEO learning playbook."""

import sys
from pathlib import Path
from statistics import mean

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_sidebar


def main() -> None:
    st.set_page_config(page_title="SEO-læring", page_icon="school", layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("SEO-læring")
    render_help_panel(
        purpose="Vis læring fra afsluttede og målte SEO-eksperimenter.",
        requirements="Mindst ét afsluttet eksperiment med resultatdata.",
        actions="Filtrér dokumenterede observationer og foreløbige mønstre.",
        limitations=(
            "Brugerens valg bliver aldrig en SEO-regel uden et målt resultat."
        ),
    )
    database = open_database()
    try:
        entries = database.get_seo_learning_entries()
    finally:
        database.close()
    if not entries:
        st.info(
            "Der er endnu ingen målte SEO-resultater. Læring oprettes først, "
            "når et eksperiment er afsluttet."
        )
        return
    website = st.selectbox(
        "Website", ["Alle"] + sorted({item["website_id"] for item in entries})
    )
    change_type = st.selectbox(
        "Ændringstype",
        ["Alle"] + sorted({item["change_type"] for item in entries}),
    )
    quality = st.selectbox(
        "Datakvalitet",
        ["Alle"] + sorted({item["data_quality"] for item in entries}),
    )
    filtered = [
        item for item in entries
        if (website == "Alle" or item["website_id"] == website)
        and (change_type == "Alle" or item["change_type"] == change_type)
        and (quality == "Alle" or item["data_quality"] == quality)
    ]
    improved = {
        "Tydeligt forbedret", "Forbedret", "Delvist forbedret"
    }
    columns = st.columns(5)
    columns[0].metric("Afsluttede", len(filtered))
    columns[1].metric(
        "Forbedrede",
        sum(item["classification"] in improved for item in filtered),
    )
    columns[2].metric(
        "Uændrede",
        sum(item["classification"] == "Uændret" for item in filtered),
    )
    columns[3].metric(
        "Forværrede",
        sum(item["classification"] == "Forværret" for item in filtered),
    )
    columns[4].metric(
        "Gennemsnitlig effekt",
        f"{mean(item['effect_size'] for item in filtered):+.1f}%"
        if filtered else "Ingen data",
    )
    st.subheader("Mønstre")
    grouped = {}
    for item in filtered:
        key = (item["change_type"], item["page_type"])
        grouped.setdefault(key, []).append(item)
    for (kind, page_type), rows in grouped.items():
        with st.container(border=True):
            count = len(rows)
            improved_count = sum(
                item["classification"] in improved for item in rows
            )
            effect = mean(item["effect_size"] for item in rows)
            level = (
                "Understøttet mønster" if count >= 10
                else "Foreløbigt mønster" if count >= 3
                else "Enkelt observation"
            )
            qualities = ", ".join(sorted({
                item["data_quality"] for item in rows
            }))
            st.write(f"**{kind} på {page_type}**")
            st.write(f"Eksperimenter: {count}")
            st.write(f"Forbedrede: {improved_count}")
            st.write(f"Gennemsnitlig effekt: {effect:+.1f}%")
            st.write(f"Datakvalitet: {qualities}")
            st.write(f"Vurdering: {level}")


if __name__ == "__main__":
    main()
