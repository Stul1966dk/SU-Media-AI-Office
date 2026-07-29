"""Explainable overview of content that may require freshness review."""

import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_next_step, render_sidebar
from dashboard.components.website_selector import get_selected_website_id


def main() -> None:
    st.set_page_config(
        page_title="Indholdsaktualitet", page_icon="🕒", layout="wide"
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Indholdsaktualitet")
    st.caption(
        "Kontrollen køres stille i baggrunden på det senest synkroniserede "
        "artikelindhold. Kun AI-bekræftede fund med en officiel kilde kan "
        "blive til en opgave på I dag."
    )
    render_help_panel(
        purpose=(
            "Find tekster, der kan omtale gamle årstal, versioner eller "
            "udgåede funktioner."
        ),
        requirements="Websiteindholdet skal være hentet i Content Explorer.",
        actions=(
            "Kontrollér den konkrete passage mod en aktuel, officiel kilde. "
            "Usikre fund bliver ikke automatisk ændret."
        ),
        limitations=(
            "Tekstens alder er kun et signal. Appen kan ikke alene konkludere, "
            "at en oplysning er faktuelt forkert."
        ),
    )
    render_next_step(
        text=(
            "Dokumenterede aktualitetsrisici kan automatisk blive prioriteret "
            "som en opgave på I dag."
        ),
        path="app.py",
        label="Gå til I dag",
    )
    website_id = get_selected_website_id()
    if not website_id:
        st.info("Vælg først et aktivt website i menuen.")
        return
    database = open_database(read_only=True)
    try:
        rows = database.get_content(website_id)
        reviews = database.get_content_freshness_reviews()
    finally:
        database.close()
    findings = [
        {
            **row,
            "review": reviews.get(
                str(row.get("url") or "").strip().rstrip("/").casefold(),
                {},
            ),
        }
        for row in rows
        if (
            str(row.get("content_type") or "").casefold() in {"post", "page"}
            and reviews.get(
                str(row.get("url") or "").strip().rstrip("/").casefold(),
                {},
            ).get("status") == "outdated"
            and reviews.get(
                str(row.get("url") or "").strip().rstrip("/").casefold(),
                {},
            ).get("content_hash") == str(row.get("raw_hash") or "")
        )
    ]
    st.metric("Bekræftet uaktuelle tekster", len(findings))
    st.subheader("Bekræftede fund")
    if not findings:
        st.success(
            "Baggrundskontrollen har endnu ikke bekræftet en uaktuel tekst "
            "med en officiel kilde."
        )
        return
    findings.sort(
        key=lambda item: (
            str(item["review"].get("checked_at") or ""),
            str(item.get("title") or ""),
        ),
        reverse=True,
    )
    for item in findings:
        with st.container(border=True):
            st.write(f"**{item.get('title') or item.get('url')}**")
            st.markdown(f"[Åbn siden]({item.get('url')})")
            st.write(str(item["review"].get("reason") or ""))
            with st.expander("Se officielle kilder"):
                for source in item["review"].get("official_sources", []):
                    st.markdown(f"- [{source}]({source})")


if __name__ == "__main__":
    main()
