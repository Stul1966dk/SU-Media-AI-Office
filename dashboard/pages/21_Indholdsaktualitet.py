"""Explainable overview of content that may require freshness review."""

import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.content_freshness import STATUS_LABELS, audit_content
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
    finally:
        database.close()
    audited = [
        {**row, "freshness": audit_content(row)}
        for row in rows
        if str(row.get("content_type") or "").casefold() in {"post", "page"}
    ]
    counts = {
        key: sum(item["freshness"]["status"] == key for item in audited)
        for key in STATUS_LABELS
    }
    columns = st.columns(4)
    for column, key in zip(columns, STATUS_LABELS):
        column.metric(STATUS_LABELS[key], counts[key])
    findings = [
        item for item in audited
        if item["freshness"]["status"] != "current"
    ]
    st.subheader("Tekster til kontrol")
    if not findings:
        st.success(
            "Der er ingen tekster med tydelige aktualitetssignaler i det "
            "lagrede indhold."
        )
        return
    findings.sort(
        key=lambda item: (
            -int(item["freshness"]["score"]),
            str(item.get("title") or ""),
        )
    )
    for item in findings:
        with st.container(border=True):
            st.write(
                f"**{item.get('title') or item.get('url')}** · "
                f"{item['freshness']['status_label']}"
            )
            st.markdown(f"[Åbn siden]({item.get('url')})")
            for signal in item["freshness"]["signals"]:
                st.write(f"- {signal['label']}")
                if signal.get("passage"):
                    st.code(signal["passage"], language=None)
            st.caption(
                "Kontrollér fundet mod en aktuel, officiel kilde, før teksten "
                "ændres eller fjernes."
            )


if __name__ == "__main__":
    main()
