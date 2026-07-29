"""Read-only prompt library and editable AI guidelines."""

import inspect
import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.ai_analyst import AIAnalyst
from agents.ai_executive import AIExecutive
from agents.title_optimizer import TitleOptimizer
from core.experiment_evaluation import ExperimentEvaluationService
from core.prompt_guidelines import PromptGuidelines, TASK_TYPES
from core.task_deliverables import _prompt as task_deliverable_prompt
from dashboard.components.database import open_database
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_next_step, render_sidebar


PROMPTS = (
    ("SEO-arbejdsudkast", task_deliverable_prompt),
    ("Title og metabeskrivelse", TitleOptimizer._prompt),
    ("AI-analyse", AIAnalyst.generate_prompt),
    ("Executive Briefing", AIExecutive._prompt),
    ("Evaluering af eksperimenter", ExperimentEvaluationService._ai_conclusion),
)


def main() -> None:
    st.set_page_config(
        page_title="AI-prompts og retningslinjer",
        page_icon="🧠",
        layout="wide",
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar(show_website_selector=False)
    st.title("AI-prompts og retningslinjer")
    render_help_panel(
        purpose=(
            "Se appens aktuelle promptskabeloner og administrér regler uden "
            "at ændre kode."
        ),
        requirements="Retningslinjer skal være konkrete og må ikke være indbyrdes modstridende.",
        actions="Gem en overordnet regel eller en regel for én opgavetype.",
        limitations=(
            "Retningslinjer påvirker kommende AI-kald; allerede gemte forslag "
            "ændres ikke."
        ),
    )
    render_next_step(
        text="Når reglerne er gemt, kan du fortsætte med den næste opgave på I dag.",
        path="app.py",
        label="Fortsæt til I dag",
    )
    database = open_database()
    try:
        service = PromptGuidelines(database)
        state = service.get()
        st.subheader("Overordnede retningslinjer")
        global_text = st.text_area(
            "Gælder alle AI-funktioner",
            value=state["global"],
            height=180,
            placeholder=(
                "Eksempel: Brug aldrig priser. Skriv naturligt dansk. "
                "Undgå formuleringen “Få overblik over”."
            ),
        )
        st.subheader("Retningslinjer pr. opgavetype")
        task_type = st.selectbox(
            "Opgavetype",
            list(TASK_TYPES),
            format_func=TASK_TYPES.get,
        )
        task_key = f"prompt-guideline:{task_type}"
        if task_key not in st.session_state:
            st.session_state[task_key] = str(
                state["tasks"].get(task_type) or ""
            )
        task_text = st.text_area(
            "Regler for den valgte opgavetype",
            key=task_key,
            height=180,
        )
        if st.button("Gem retningslinjer", type="primary"):
            tasks = dict(state["tasks"])
            if task_text.strip():
                tasks[task_type] = task_text.strip()
            else:
                tasks.pop(task_type, None)
            service.save(global_text, tasks)
            st.success("Retningslinjerne er gemt og bruges ved næste AI-kald.")
            st.rerun()
    finally:
        database.close()

    st.subheader("Promptbibliotek")
    st.caption(
        "Visningen er skrivebeskyttet. Dynamiske website- og analysedata "
        "indsættes først, når prompten køres."
    )
    for label, function in PROMPTS:
        with st.expander(label):
            st.code(inspect.getsource(function), language="python")


if __name__ == "__main__":
    main()
