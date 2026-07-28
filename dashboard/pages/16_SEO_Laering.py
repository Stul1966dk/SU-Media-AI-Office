"""Measured SEO learning playbook."""

import sys
from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_next_step, render_sidebar


def main() -> None:
    st.set_page_config(page_title="SEO-læring", page_icon="school", layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("SEO-læring")
    render_help_panel(
        purpose="Hjælp ældre bogmærker videre til det samlede resultatoverblik.",
        requirements="Ingen.",
        actions="Åbn Resultater for målinger og dokumenteret læring.",
        limitations="Denne ældre side viser ikke længere et separat overblik.",
    )
    st.info(
        "SEO-læring er nu en del af Resultater, så konklusionen og den "
        "genbrugelige læring altid ses i samme sammenhæng."
    )
    render_next_step(
        text=(
            "Fortsæt til Resultater for at se aktive målinger, afsluttede "
            "konklusioner og dokumenterede mønstre."
        ),
        path="pages/13_Eksperimenter.py",
        label="Åbn Resultater",
    )


if __name__ == "__main__":
    main()
