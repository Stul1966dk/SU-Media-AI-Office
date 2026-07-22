"""Consistent user guidance for every dashboard page."""

import streamlit as st


def render_help_panel(
    *,
    purpose: str,
    requirements: str,
    actions: str,
    limitations: str,
) -> None:
    """Explain a page in four predictable, plain-language sections."""
    with st.expander("Hjælp til denne side", expanded=False):
        st.markdown(f"**Hvad bruges siden til?**  \n{purpose}")
        st.markdown(f"**Hvad kræves for at siden virker?**  \n{requirements}")
        st.markdown(f"**Hvad kan du gøre her?**  \n{actions}")
        st.markdown(f"**Hvad gør siden ikke?**  \n{limitations}")
