"""The single, focused surface for today's reviewed SEO change."""

import importlib
import sys
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALL_WEBSITES = "Alle websites"
FILTER_SESSION_KEY = "daily_work_website_filter"
FILTER_WIDGET_KEY = "daily_work_website_filter_widget"
CONCRETE_TRAFFIC_TASKS = {
    "combined_traffic_decline",
    "search_only_decline",
    "plausible_only_decline",
}
EXPERIMENT_TYPE_LABELS = {
    "Indholdsopdatering": "content_update",
    "Title og metabeskrivelse": "title_meta",
    "Interne links": "internal_links",
    "Teknisk forbedring": "technical_fix",
    "Strukturerede data": "schema",
}
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.title_optimizer import TitleOptimizer
from core.ai_service import AIService
from core.daily_work_preparation import DailyWorkPreparationService
from core.current_diagnosis_reader import read_latest_diagnoses
from core.seo_experiment_engine import SEOExperimentEngine
from core.website_registry import WebsiteRegistry
from core.work_queue_service import WorkQueueService
from dashboard.components.database import open_database
from dashboard.components.data import (
    _filter_decided_recommendations,
)
import dashboard.components.data as dashboard_data_module
import core.task_deliverables as task_deliverables_module
import core.traffic_recommendation_store as traffic_store_module
import core.traffic_recommendation_workflow as traffic_workflow_module
import core.traffic_recommendations as traffic_recommendations_module
import core.traffic_work_overview as traffic_work_module
from dashboard.components.ui import load_styles, render_sidebar
from dashboard.components.website_selector import set_selected_website

task_deliverables_module = importlib.reload(task_deliverables_module)
fallback_task_deliverable = task_deliverables_module.fallback_task_deliverable
format_deliverable = task_deliverables_module.format_deliverable
format_title_meta_option = task_deliverables_module.format_title_meta_option
generate_task_deliverable = task_deliverables_module.generate_task_deliverable
prefer_pipe_separator = task_deliverables_module.prefer_pipe_separator
split_title_meta_option = task_deliverables_module.split_title_meta_option
validate_content_change = task_deliverables_module.validate_content_change


def _optimizer(database: Any) -> TitleOptimizer:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return TitleOptimizer(
        database=database,
        website_registry=WebsiteRegistry(database),
        ai_service=AIService(),
    )


def main() -> None:
    st.set_page_config(
        page_title="I dag", page_icon="✓", layout="centered"
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    _load_daily_work_styles()
    render_sidebar(show_website_selector=False)
    st.title("I dag")
    st.caption(
        "Her får du ét tydeligt næste trin. Når det er udført, viser siden "
        "automatisk, hvad du skal gøre bagefter."
    )
    action_result = st.session_state.pop("daily_action_result", None)
    if action_result:
        st.success(action_result)

    database = open_database()
    try:
        registry = WebsiteRegistry(database)
        queue = WorkQueueService(
            database,
            registry,
            experiment_engine=SEOExperimentEngine(database),
        )
        websites = _active_websites(registry)
        active_ids = {str(item["website"]) for item in websites}
        selected = _render_website_filter(websites)
        website_id = None if selected == ALL_WEBSITES else selected
        decisions = _filter_active_site_rows(
            importlib.reload(traffic_store_module).get_decisions(database),
            active_ids,
            website_field="website_id",
        )
        experiments = _filter_active_site_rows(
            database.get_seo_experiments(),
            active_ids,
            website_field="website_id",
        )
        work_module = importlib.reload(traffic_work_module)
        work_overview = work_module.build_traffic_work_overview(
            decisions, experiments, website_id=website_id
        )
        _render_work_overview(database, work_overview)
        if work_module.next_actionable_work(work_overview):
            return
        context = database.get_dashboard_action_context()
        search_diagnoses = _current_diagnoses(
            database, websites, context,
            context_key="search_diagnoses",
            reader_name="get_latest_search_console_diagnosis",
        )
        plausible_diagnoses = _current_diagnoses(
            database, websites, context,
            context_key="plausible_diagnoses",
            reader_name="get_latest_plausible_diagnosis",
        )
        priority_tasks = _build_current_priority_tasks(
            system_status=database.get_dashboard_system_health(),
            seo_sites=context["seo_health"],
            project_tasks=database.get_priority_tasks(),
            experiments=context["experiments"],
            active_experiments=context["active_experiments"],
            coverage=context["coverage"],
            plausible_rows=context["plausible_daily"],
            search_diagnoses=search_diagnoses,
            plausible_diagnoses=plausible_diagnoses,
            limit=None,
        )
        priority_tasks = [
            item for item in priority_tasks
            if item.get("task_type") in CONCRETE_TRAFFIC_TASKS
        ]
        priority_tasks = _filter_active_site_rows(
            priority_tasks, active_ids, website_field="website"
        )
        priority_tasks = traffic_recommendations_module.apply_measured_learning(
            priority_tasks, database.get_seo_learning_entries()
        )
        priority_tasks = _filter_decided_recommendations(
            priority_tasks, decisions,
        )
        if website_id:
            priority_tasks = [
                item for item in priority_tasks
                if item["website"] in {website_id, "—"}
            ]
        if priority_tasks:
            _render_priority_task(database, priority_tasks[0])
            return
        optimizer = _optimizer(database)
        preparation = DailyWorkPreparationService(
            database=database, queue=queue, title_optimizer=optimizer
        )
        with st.spinner("Forbereder næste opgave..."):
            prepared = preparation.prepare_next(website_id)
            current = prepared.item
        if not current:
            _render_empty_state(
                queue, selected, websites,
                reason=prepared.reason,
                candidate_count=prepared.candidate_count,
            )
        elif current["status"] == "awaiting_implementation":
            _render_implementation(database, queue, current)
        else:
            _render_recommendation(database, queue, current)
    finally:
        database.close()


def _build_current_priority_tasks(**context: Any) -> list[dict[str, Any]]:
    """Use current pure recommendation code despite Streamlit module caching."""
    importlib.reload(traffic_recommendations_module)
    current_data = importlib.reload(dashboard_data_module)
    return current_data.build_dashboard_priority_tasks(**context)


def _filter_active_site_rows(
    rows: list[dict[str, Any]],
    active_ids: set[str],
    *,
    website_field: str,
) -> list[dict[str, Any]]:
    """Keep I dag strictly scoped to websites selected as active."""
    return [
        item for item in rows
        if str(item.get(website_field) or "") in active_ids
    ]


def _current_diagnoses(
    database: Any,
    websites: list[Any],
    context: dict[str, Any],
    *,
    context_key: str,
    reader_name: str,
) -> list[dict[str, Any]]:
    """Read diagnoses across both current and hot-reloaded Database classes."""
    website_ids = [
        str(item.get("website", ""))
        if isinstance(item, dict) else str(item)
        for item in websites
    ]
    kind = "search" if context_key == "search_diagnoses" else "plausible"
    result = read_latest_diagnoses(database, website_ids, kind=kind)
    if result:
        return result
    stored = context.get(context_key)
    if isinstance(stored, list) and stored:
        return stored
    reader = getattr(database, reader_name, None)
    if reader is None:
        return []
    return [
        diagnosis
        for website in website_ids
        if website
        if (diagnosis := reader(website)) is not None
    ]


def _render_work_overview(
    database: Any, items: list[dict[str, Any]]
) -> None:
    """Show only the one current action; status belongs on Resultater."""
    actionable = traffic_work_module.next_actionable_work(items)
    if actionable:
        st.markdown("### Næste trin")
        _render_workflow_card(database, actionable, primary=True)


def _render_workflow_card(
    database: Any, item: dict[str, Any], *, primary: bool
) -> None:
    with st.container(border=True):
        st.write(f"**{item['status_label']} · {item['website']}**")
        st.write(item["title"])
        if item.get("target_url"):
            st.caption(item["target_url"])
        st.write(f"**Det skal du gøre:** {item['next_action']}")
        if item.get("planned_evaluation_date"):
            st.write(
                "**Planlagt evaluering:** "
                f"{item['planned_evaluation_date']}"
            )
        if item["stage"] == "draft":
            _render_draft_decision(database, item, primary=primary)
        elif item["stage"] == "approved":
            _render_approved_decision(database, item)
        else:
            st.page_link(
                item["target"],
                label=item["link_label"],
                icon="🧪",
            )


def _workflow(database: Any) -> Any:
    module = importlib.reload(traffic_workflow_module)
    return module.TrafficRecommendationWorkflow(database)


def _finish_daily_action(message: str) -> None:
    st.session_state["daily_action_result"] = message
    st.switch_page("app.py")


def _render_draft_decision(
    database: Any, item: dict[str, Any], *, primary: bool
) -> None:
    key = str(item["recommendation_key"])
    if "Anbefalet løsning:" not in str(item.get("description") or ""):
        st.info(
            "Denne ældre kladde mangler en konkret leverance. AI Office "
            "skal først udarbejde selve forslaget."
        )
        _render_new_decision_actions(
            database, _recommendation_from_work_item(item)
        )
        return
    if st.button(
        "Godkend arbejdsudkast",
        type="primary" if primary else "secondary",
        key=f"approve-daily-{key}",
        help=(
            "Godkender arbejdsplanen. Appen ændrer ikke websitet og starter "
            "ingen måling endnu."
        ),
    ):
        try:
            _workflow(database).approve_draft(key)
        except ValueError as error:
            st.error(str(error))
        else:
            _finish_daily_action(
                "Opgaven er godkendt. Udfør nu ændringen på websitet."
            )
    with st.expander("Redigér arbejdsudkast før godkendelse"):
        with st.form(f"edit-daily-{key}"):
            title = st.text_input("Titel", value=str(item["title"]))
            description = st.text_area(
                "Arbejdsbeskrivelse",
                value=str(item.get("description") or ""),
                height=150,
            )
            save = st.form_submit_button("Gem ændringer")
        if save:
            recommendation = _recommendation_from_work_item(item)
            try:
                _workflow(database).create_draft(
                    recommendation,
                    title=title,
                    description=description,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                _finish_daily_action("Dine ændringer er gemt.")


def _render_approved_decision(
    database: Any, item: dict[str, Any]
) -> None:
    deliverable = _parse_approved_deliverable(item)
    if deliverable:
        _render_approved_instruction(deliverable)
    else:
        _render_legacy_approved_instruction(database, item)
        return

    if item.get("target_url"):
        st.link_button(
            "Åbn siden, der skal ændres",
            str(item["target_url"]),
            help="Åbner websitet i en ny fane. AI Office ændrer intet selv.",
        )

    st.markdown("### Når du har udført ændringen")
    st.caption(
        "Registrér først ændringen her, når den godkendte arbejdsinstruks "
        "er udført og gemt på websitet."
    )
    with st.form(
        f"implement-daily-{item['recommendation_key']}", border=True
    ):
        default_change_type = _approved_change_type(item)
        change_type = st.selectbox(
            "Hvilken type ændring udførte du?",
            list(EXPERIMENT_TYPE_LABELS),
            index=list(EXPERIMENT_TYPE_LABELS).index(default_change_type),
            help="Vælg den ene ændringstype, som 28-dages målingen skal følge.",
        )
        description = st.text_area(
            "Hvad ændrede du konkret?",
            value=_approved_solution(item),
            help=(
                "AI Office har indsat den godkendte løsning. Tilpas kun "
                "teksten, hvis du implementerede noget andet."
            ),
            height=140,
        )
        implemented = st.form_submit_button(
            "Registrér ændring og start 28-dages måling",
            type="primary",
        )
    if implemented:
        try:
            experiment = _workflow(database).mark_implemented(
                str(item["recommendation_key"]),
                change_description=description,
                experiment_type=EXPERIMENT_TYPE_LABELS[change_type],
            )
        except ValueError as error:
            st.error(str(error))
        else:
            due = experiment.get("planned_evaluation_date")
            _finish_daily_action(
                "Ændringen er registreret, og målingen er startet"
                + (f" frem til {due}." if due else ".")
            )


def _render_approved_instruction(deliverable: dict[str, Any]) -> None:
    st.markdown("### Godkendt arbejdsinstruks")
    st.write(deliverable["summary"])
    st.write("**Det skal du rette**")
    _render_deliverable_option(deliverable)
    st.write("**Sådan udfører du ændringen**")
    for index, step in enumerate(deliverable["implementation_steps"], 1):
        st.write(f"{index}. {step}")
    st.write("**Kontrollér før du registrerer ændringen**")
    for check in deliverable["validation_checks"]:
        st.write(f"- {check}")
    with st.expander("Se begrundelse og alternativer"):
        st.write(f"**Begrundelse:** {deliverable['rationale']}")
        if deliverable["alternatives"]:
            st.write("**Alternative løsninger:**")
            for index, alternative in enumerate(
                deliverable["alternatives"], 1
            ):
                st.write(f"{index}. {alternative}")


def _render_deliverable_option(deliverable: dict[str, Any]) -> None:
    if (
        deliverable.get("deliverable_type") == "content_update"
        and all(deliverable.get(field) for field in (
            "content_location", "current_content", "replacement_content",
            "search_intent",
        ))
    ):
        _render_content_update(deliverable)
        return
    if deliverable.get("deliverable_type") != "title_meta":
        st.success(deliverable["recommended_option"])
        st.caption("Teksten kan markeres og kopieres direkte.")
        return
    try:
        title, meta = split_title_meta_option(
            deliverable["recommended_option"]
        )
    except ValueError:
        st.warning(
            "Forslaget kunne ikke opdeles automatisk. Kontrollér teksten "
            "ekstra grundigt."
        )
        st.code(deliverable["recommended_option"], language=None)
        return
    st.write("**Title**")
    st.code(title, language=None, wrap_lines=True)
    st.caption("Brug kopiér-knappen i title-feltet.")
    st.write("**Metabeskrivelse**")
    st.code(meta, language=None, wrap_lines=True)
    st.caption("Brug kopiér-knappen i meta-feltet.")


def _render_content_update(deliverable: dict[str, Any]) -> None:
    st.write("**Placering på siden**")
    st.info(str(deliverable.get("content_location") or "Ikke angivet"))
    st.write("**Nuværende tekst**")
    st.code(
        str(deliverable.get("current_content") or "Ikke identificeret"),
        language=None,
        wrap_lines=True,
    )
    st.write("**Ny færdig tekst**")
    st.code(
        str(
            deliverable.get("replacement_content")
            or deliverable.get("recommended_option")
            or ""
        ),
        language=None,
        wrap_lines=True,
    )
    st.caption("Brug kopiér-knappen i feltet med den nye tekst.")
    st.write("**Søgeintention**")
    st.write(str(deliverable.get("search_intent") or "Ikke angivet"))


def _render_legacy_approved_instruction(
    database: Any, item: dict[str, Any]
) -> None:
    key = str(item["recommendation_key"])
    state_key = f"approved-deliverable:{key}"
    st.warning(
        "Denne opgave blev godkendt i en ældre version og mangler en "
        "konkret arbejdsinstruks. Generér instruktionen, før du ændrer siden."
    )
    with st.expander("Se den gamle, overordnede beskrivelse"):
        st.write(str(item.get("description") or "Ingen beskrivelse gemt."))
    if state_key not in st.session_state:
        if st.button(
            "Lav konkret arbejdsinstruks",
            type="primary",
            key=f"repair-approved-{key}",
            help=(
                "AI Office udarbejder det konkrete forslag. Intet ændres "
                "på websitet, før du selv udfører det."
            ),
        ):
            with st.spinner("AI Office udarbejder arbejdsinstruksen…"):
                deliverable, used_fallback = _generate_deliverable(
                    database, _recommendation_from_work_item(item)
                )
            st.session_state[state_key] = deliverable
            st.session_state[f"{state_key}:fallback"] = used_fallback
            st.rerun()
        return

    deliverable = st.session_state[state_key]
    if st.session_state.get(f"{state_key}:fallback"):
        st.warning(
            "AI-forbindelsen var ikke tilgængelig. Instruksen er lavet med "
            "faste regler og bør kontrolleres ekstra grundigt."
        )
    _render_approved_instruction(deliverable)
    if st.button(
        "Gem som godkendt arbejdsinstruks",
        type="primary",
        key=f"save-approved-plan-{key}",
    ):
        try:
            _workflow(database).update_approved_plan(
                key, description=format_deliverable(deliverable)
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.pop(state_key, None)
            st.session_state.pop(f"{state_key}:fallback", None)
            _finish_daily_action(
                "Arbejdsinstruksen er gemt. Du kan nu udføre ændringen."
            )
    if st.button(
        "Lav et nyt forslag",
        key=f"regenerate-approved-{key}",
    ):
        st.session_state.pop(state_key, None)
        st.session_state.pop(f"{state_key}:fallback", None)
        st.rerun()


def _approved_change_type(item: dict[str, Any]) -> str:
    description = str(item.get("description") or "")
    mappings = {
        "title_meta": "Title og metabeskrivelse",
        "internal_links": "Interne links",
        "technical_fix": "Teknisk forbedring",
        "schema": "Strukturerede data",
        "content_update": "Indholdsopdatering",
    }
    return next(
        (
            label for key, label in mappings.items()
            if f"Leverancetype: {key}" in description
        ),
        (
            "Title og metabeskrivelse"
            if "ctr" in str(item.get("measured_cause") or "").casefold()
            else "Indholdsopdatering"
        ),
    )


def _approved_solution(item: dict[str, Any]) -> str:
    deliverable = _parse_approved_deliverable(item)
    return deliverable["recommended_option"] if deliverable else ""


def _parse_approved_deliverable(
    item: dict[str, Any]
) -> dict[str, Any] | None:
    """Read the structured deliverable persisted in a task description."""
    description = str(item.get("description") or "").strip()
    headings = (
        "Anbefalet løsning:", "Begrundelse:", "Alternativer:",
        "Implementering:", "Kontrol før godkendelse:",
    )
    if not all(heading in description for heading in headings):
        return None

    def section(start: str, end: str | None) -> str:
        content = description.split(start, 1)[1]
        return content.split(end, 1)[0].strip() if end else content.strip()

    summary = description.split("Anbefalet løsning:", 1)[0]
    summary = summary.split("\n\n", 1)[-1].strip()
    alternatives = _strip_list_markers(section(
        "Alternativer:", "Implementering:"
    ))
    steps = _strip_list_markers(section(
        "Implementering:", "Kontrol før godkendelse:"
    ))
    checks = _strip_list_markers(section(
        "Kontrol før godkendelse:", None
    ))
    result = {
        "deliverable_type": section(
            "Leverancetype:", None
        ).splitlines()[0].strip()
        if "Leverancetype:" in description else "",
        "summary": summary,
        "recommended_option": section(
            "Anbefalet løsning:", "Begrundelse:"
        ),
        "rationale": section("Begrundelse:", "Alternativer:"),
        "alternatives": alternatives,
        "implementation_steps": steps,
        "validation_checks": checks,
    }
    if result["deliverable_type"] == "content_update":
        optional_headings = (
            "Placering:", "Nuværende tekst:", "Ny tekst:", "Søgeintention:",
        )
        if all(heading in description for heading in optional_headings):
            result.update({
                "recommended_option": section(
                    "Anbefalet løsning:", "Placering:"
                ),
                "content_location": section(
                    "Placering:", "Nuværende tekst:"
                ),
                "current_content": section(
                    "Nuværende tekst:", "Ny tekst:"
                ),
                "replacement_content": section(
                    "Ny tekst:", "Søgeintention:"
                ),
                "search_intent": section(
                    "Søgeintention:", "Begrundelse:"
                ),
            })
    return result


def _strip_list_markers(value: str) -> list[str]:
    rows = []
    for raw in value.splitlines():
        row = raw.strip()
        if not row:
            continue
        if row.startswith("- "):
            row = row[2:]
        else:
            prefix, separator, remainder = row.partition(". ")
            if separator and prefix.isdigit():
                row = remainder
        rows.append(row)
    return rows


def _recommendation_from_work_item(
    item: dict[str, Any]
) -> dict[str, Any]:
    evidence = item.get("evidence") or {}
    return {
        "task_key": item["recommendation_key"],
        "website": item["website"],
        "task_type": "combined_traffic_decline",
        "target_url": item.get("target_url", ""),
        "measured_cause": item.get("measured_cause", ""),
        "description": item["title"],
        "priority": "Kritisk",
        **evidence,
    }


def _render_combined_traffic_task(
    database: Any, item: dict[str, Any]
) -> None:
    with st.container(border=True):
        st.subheader(item["description"])
        st.write(f"**Prioritet:** {item['priority']}")
        st.write(f"**Website:** {item['website']}")
        st.markdown("### Det forbereder AI Office")
        st.write(item.get("recommended_action") or item["description"])
        st.info(
            "Du skal ikke selv udarbejde forslagene. AI Office producerer "
            "først et konkret arbejdsudkast, som du kan kontrollere, "
            "redigere og godkende."
        )
        if item.get("completion_criterion"):
            st.write(
                f"**Færdig når:** {item['completion_criterion']}"
            )
        if item.get("measurement_method"):
            st.write(f"**Måling:** {item['measurement_method']}")
        if item.get("estimated_minutes"):
            st.write(
                f"**Forventet tid:** {item['estimated_minutes']} minutter"
            )
        with st.expander("Se datagrundlag og forklaring"):
            st.write(
                "**Plausible-ændring:** "
                f"{float(item['plausible_change']):.1f} %".replace(".", ",")
            )
            st.write(
                f"**Search Console-ændring:** "
                f"{item['search_console_change']}"
            )
            st.write(item["explanation"])
            if item.get("measured_cause"):
                st.write(f"**Målt signal:** {item['measured_cause']}")
            if item.get("confidence"):
                st.write(f"**Sikkerhed:** {item['confidence']}")
            if item.get("learning_summary"):
                st.write(
                    f"**Læring fra tidligere målinger:** "
                    f"{item['learning_summary']}"
                )
        st.markdown("### Næste trin")
        _render_new_decision_actions(database, item)
    _render_priority_explanation(item)


def _render_new_decision_actions(
    database: Any, item: dict[str, Any]
) -> None:
    title = str(item["description"])
    key = str(item["task_key"])
    state_key = f"task-deliverable:{key}"
    if state_key not in st.session_state:
        if st.button(
            "Lav konkret arbejdsudkast",
            type="primary",
            key=f"generate-deliverable-{key}",
            help=(
                "AI Office producerer forslagene. Intet godkendes eller "
                "ændres på websitet endnu."
            ),
        ):
            with st.spinner("AI Office udarbejder det konkrete forslag…"):
                deliverable, used_fallback = _generate_deliverable(
                    database, item
                )
            st.session_state[state_key] = deliverable
            st.session_state[f"{state_key}:fallback"] = used_fallback
            st.rerun()
    else:
        deliverable = st.session_state[state_key]
        if st.session_state.get(f"{state_key}:fallback"):
            st.warning(
                "AI-forbindelsen var ikke tilgængelig. Udkastet er lavet "
                "med faste regler og bør kontrolleres ekstra grundigt."
            )
        _render_deliverable_for_approval(
            database, item, title, deliverable, state_key
        )
    snooze_column, reject_column = st.columns(2)
    if snooze_column.button(
        "Udsæt 14 dage",
        key=f"snooze-new-{key}",
        help="Skjuler anbefalingen i 14 dage uden at slette den.",
    ):
        try:
            _workflow(database).snooze(
                item, date.today() + timedelta(days=14)
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _finish_daily_action("Anbefalingen er udsat 14 dage.")
    if reject_column.button(
        "Afvis",
        key=f"reject-new-{key}",
        help="Afviser denne konkrete anbefaling, så den ikke foreslås igen.",
    ):
        _workflow(database).reject(item)
        _finish_daily_action("Anbefalingen er afvist.")


def _generate_deliverable(
    database: Any, item: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Generate from public context, with a safe usable fallback."""
    public_context = []
    if item.get("target_url"):
        try:
            current_page = _optimizer(database).analyze_current_snippet({
                "target_url": item["target_url"],
            })
            public_context.append({
                "relation": "berørt side",
                **current_page,
            })
        except Exception:
            pass
    try:
        for row in database.get_content(item["website"])[:8]:
            public_context.append({
                "relation": "mulig relateret side",
                "title": row.get("title", ""),
                "url": row.get("url") or row.get("link") or "",
                "excerpt": str(
                    row.get("excerpt") or row.get("content") or ""
                )[:500],
            })
    except Exception:
        pass
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    try:
        return generate_task_deliverable(
            item, ai_service=AIService(), public_context=public_context
        ), False
    except Exception:
        return fallback_task_deliverable(
            item, public_context=public_context
        ), True


def _render_deliverable_for_approval(
    database: Any,
    item: dict[str, Any],
    title: str,
    deliverable: dict[str, Any],
    state_key: str,
) -> None:
    """Show the actual output before allowing an approval."""
    st.subheader("Konkret arbejdsudkast")
    st.write(f"**AI Offices anbefaling:** {deliverable['summary']}")
    _render_deliverable_option(deliverable)
    st.write(f"**Hvorfor:** {deliverable['rationale']}")
    with st.expander("Se alternativer"):
        for index, alternative in enumerate(
            deliverable["alternatives"], start=1
        ):
            st.write(f"{index}. {alternative}")
    with st.expander("Se implementering og kontrol"):
        st.write("**Sådan implementeres den manuelt:**")
        for index, step in enumerate(
            deliverable["implementation_steps"], start=1
        ):
            st.write(f"{index}. {step}")
        st.write("**Kontrollér før godkendelse:**")
        for check in deliverable["validation_checks"]:
            st.write(f"- {check}")
    with st.form(f"approve-deliverable-{item['task_key']}"):
        edited_title = st.text_input("Opgavetitel", value=title)
        if deliverable["deliverable_type"] == "title_meta":
            proposed_title, proposed_meta = split_title_meta_option(
                deliverable["recommended_option"]
            )
            edited_snippet_title = st.text_input(
                "Godkendt title", value=proposed_title
            )
            edited_snippet_meta = st.text_area(
                "Godkendt metabeskrivelse",
                value=proposed_meta,
                height=100,
            )
            edited_solution = format_title_meta_option(
                edited_snippet_title, edited_snippet_meta
            )
            reviewed_fields = {}
        elif deliverable["deliverable_type"] == "content_update":
            edited_location = st.text_input(
                "Placering på siden",
                value=deliverable["content_location"],
                help="Angiv den præcise overskrift eller passage.",
            )
            edited_current = st.text_area(
                "Nuværende tekst",
                value=deliverable["current_content"],
                height=120,
            )
            edited_replacement = st.text_area(
                "Ny færdig tekst",
                value=deliverable["replacement_content"],
                height=260,
                help="Dette er teksten, der skal kunne kopieres direkte.",
            )
            edited_intent = st.text_area(
                "Søgeintention",
                value=deliverable["search_intent"],
                height=90,
            )
            edited_solution = edited_replacement
            reviewed_fields = {
                "content_location": edited_location,
                "current_content": edited_current,
                "replacement_content": edited_replacement,
                "search_intent": edited_intent,
            }
        else:
            edited_solution = st.text_area(
                "Anbefalet løsning",
                value=deliverable["recommended_option"],
                height=150,
                help=(
                    "Ret kun forslaget, hvis AI Office har misforstået siden "
                    "eller søgeintentionen."
                ),
            )
            reviewed_fields = {}
        approved = st.form_submit_button(
            "Godkend arbejdsudkast", type="primary"
        )
    if approved:
        reviewed = {
            **deliverable,
            **reviewed_fields,
            "recommended_option": edited_solution,
        }
        if reviewed["deliverable_type"] == "content_update":
            try:
                validate_content_change(reviewed)
            except ValueError as error:
                st.error(str(error))
                return
        _create_and_approve(
            database, item, edited_title, format_deliverable(reviewed)
        )
    if st.button(
        "Lav et nyt forslag",
        key=f"regenerate-{item['task_key']}",
        help="Kasserer det viste udkast og genererer et nyt.",
    ):
        st.session_state.pop(state_key, None)
        st.session_state.pop(f"{state_key}:fallback", None)
        st.rerun()


def _create_and_approve(
    database: Any,
    recommendation: dict[str, Any],
    title: str,
    description: str,
) -> None:
    try:
        workflow = _workflow(database)
        decision = workflow.create_draft(
            recommendation, title=title, description=description
        )
        workflow.approve_draft(str(decision["recommendation_key"]))
    except ValueError as error:
        st.error(str(error))
    else:
        _finish_daily_action(
            "Opgaven er godkendt. Udfør nu ændringen på websitet."
        )


def _render_priority_task(
    database: Any, item: dict[str, Any]
) -> None:
    """Render the highest persisted task without exposing internal scores."""
    if item.get("task_type") in {
        "combined_traffic_decline", "search_only_decline",
        "plausible_only_decline",
    }:
        _render_combined_traffic_task(database, item)
        return
    with st.container(border=True):
        st.subheader(item["description"])
        st.write(f"**Prioritet:** {item['priority']}")
        if item.get("website") and item["website"] != "—":
            st.write(f"**Website:** {item['website']}")
        if item.get("change"):
            st.write(f"**Ændring:** {item['change']}")
        _render_scoped_navigation(item, label=item["link_label"])
    _render_priority_explanation(item)


def _render_scoped_navigation(
    item: dict[str, Any], *, label: str
) -> None:
    """Open the target after selecting the task's website globally."""
    website = str(item.get("website") or "")
    target = str(item["target"])
    if website and website != "—":
        if st.button(
            label,
            type="primary",
            help=(
                "Åbner den relevante side med korrekt website og analyse "
                "valgt, så du kan fortsætte direkte."
            ),
            key=f"open-{item.get('task_key') or target}-{website}",
        ):
            set_selected_website(website)
            if target == "pages/9_SEO.py" and item.get("target_url"):
                st.session_state["seo_requested_tab"] = "Årsagsanalyse"
            st.switch_page(target)
        return
    if st.button(
        label,
        key=f"open-{item.get('task_key') or target}-global",
    ):
        st.switch_page(target)


def _render_priority_explanation(item: dict[str, Any]) -> None:
    """Show only persisted signals that contributed to the total score."""
    explanations = _priority_explanations(item)
    if not explanations:
        return
    with st.expander("Hvorfor er denne opgave valgt?"):
        for signal, explanation, score in explanations:
            st.markdown(f"**{signal}**")
            st.write(explanation)
            st.write(f"Score: +{_format_score(score)}")
        st.markdown(
            "**Samlet prioritetsscore: "
            f"{_format_score(float(item['total_score']))}**"
        )


def _priority_explanations(
    item: dict[str, Any],
) -> list[tuple[str, str, float]]:
    """Map positive persisted subscores to deterministic Danish copy."""
    signals = (
        (
            "plausible_score",
            "Plausible",
            (
                "Den samlede trafik er faldet "
                f"{_format_number(abs(float(item.get('plausible_change') or 0)))} %."
            ),
        ),
        (
            "search_console_click_score",
            "Search Console",
            (
                "Organiske klik er faldet "
                f"{_format_number(abs(float(item.get('click_change') or 0)))} %."
            ),
        ),
        (
            "ctr_score",
            "CTR",
            (
                "CTR er faldet "
                f"{_format_number(abs(float(item.get('ctr_change') or 0)))} "
                "procentpoint."
            ),
        ),
        (
            "position_score",
            "Placering",
            (
                "Den gennemsnitlige placering er blevet "
                f"{_format_number(abs(float(item.get('position_change') or 0)))} "
                "dårligere."
            ),
        ),
        (
            "seo_health_score",
            "SEO Health",
            (
                "SEO Health-status er "
                f"{_trend_label(item.get('seo_health_trend'))}."
            ),
        ),
        (
            "experiment_score",
            "SEO-eksperiment",
            (
                "Et SEO-eksperiment er klar til evaluering."
                if item.get("task_type") == "experiment_ready"
                else "Websitet har et aktivt SEO-eksperiment."
            ),
        ),
        (
            "missing_data_score",
            "Manglende data",
            (
                "Search Console-data mangler."
                if item.get("task_type") == "missing_search_console"
                else "Plausible-data mangler."
            ),
        ),
        (
            "system_score",
            "Systemstatus",
            "Systemstatus viser en fejl, der kræver handling.",
        ),
        (
            "existing_task_score",
            "Eksisterende opgave",
            "Opgaven har allerede en registreret prioritet.",
        ),
    )
    return [
        (name, explanation, score)
        for field, name, explanation in signals
        if (score := float(item.get(field) or 0)) > 0
    ]


def _trend_label(value: Any) -> str:
    return {
        "critical": "kritisk",
        "declining": "faldende",
        "stable": "stabil",
        "growing": "stigende",
    }.get(str(value or "").lower(), "ukendt")


def _format_score(value: float) -> str:
    rounded = round(float(value), 1)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.1f}".replace(".", ",")


def _format_number(value: float) -> str:
    return f"{float(value):.1f}".replace(".", ",")


def _render_recommendation(
    database: Any, queue: WorkQueueService, item: dict[str, Any]
) -> None:
    change = _recommended_change(item)
    if not _has_concrete_change(change):
        st.error("Opgaven er ikke komplet og kan derfor ikke vises endnu.")
        return

    _render_page_card(item, change)
    _render_search_intent(item)
    _render_change_card(item, change)
    _render_reason_card(item)

    accept_column, skip_column = st.columns(2)
    accept = accept_column.button(
        "🟢 Accepter opgave", type="primary", width="stretch"
    )
    skip = skip_column.button(
        "⚪ Spring over", width="stretch"
    )
    if accept:
        try:
            queue.approve(
                item["id"],
                title=prefer_pipe_separator(change["approved_title"]),
                meta=change["approved_meta"],
                title_optimizer=_optimizer(database),
            )
            st.rerun()
        except Exception:
            st.error("Opgaven kunne ikke accepteres. Prøv igen.")
    if skip:
        queue.skip(item["id"])
        st.rerun()


def _render_implementation(
    database: Any, queue: WorkQueueService, item: dict[str, Any]
) -> None:
    change = item.get("approved_change") or {}
    st.header("Implementér ændringen")
    if not _has_concrete_change(change):
        st.error("Den godkendte ændring er ufuldstændig og kan ikke implementeres.")
        return
    _render_search_intent(item)
    _render_change_card(item, change)
    with st.container(border=True):
        st.subheader("Det skal du gøre nu")
        st.markdown(
            "1. Åbn siden i WordPress.\n"
            "2. Indsæt den nye title.\n"
            "3. Indsæt den nye metabeskrivelse.\n"
            "4. Gem siden.\n"
            "5. Klik **Markér som implementeret**."
        )
    if st.button(
        "🟢 Markér som implementeret",
        type="primary",
        width="stretch",
    ):
        try:
            queue.mark_implemented(
                item["id"], title_optimizer=_optimizer(database)
            )
            st.rerun()
        except Exception:
            st.error("Implementeringen kunne ikke registreres. Prøv igen.")


def _render_page_card(
    item: dict[str, Any], change: dict[str, Any]
) -> None:
    with st.container(border=True):
        st.subheader("Website")
        st.write(f"**Website:** {item['website_id']}")
        st.markdown(f"### {escape(_page_title(item, change))}")
        st.markdown(f"[{escape(item['target_url'])}]({item['target_url']})")
        st.write(f"**Primært søgeord:** {item.get('target_query') or 'Ikke angivet'}")


def _render_change_card(
    item: dict[str, Any], change: dict[str, Any]
) -> None:
    with st.container(border=True):
        st.subheader("AI anbefaler")
        st.write("**Ny title**")
        st.code(
            prefer_pipe_separator(change["approved_title"]),
            language=None,
            wrap_lines=True,
        )
        st.caption("Kopiér title med kopiér-ikonet i feltet.")
        st.write("**Ny metabeskrivelse**")
        st.code(change["approved_meta"], language=None, wrap_lines=True)
        st.caption("Kopiér metabeskrivelse med kopiér-ikonet i feltet.")


def _render_search_intent(item: dict[str, Any]) -> None:
    intent = (
        (item.get("implementation") or {}).get("search_intent")
        or (item.get("candidate") or {}).get("search_intent")
        or {}
    )
    if not intent:
        return
    labels = {
        "guide": "Guide og vejledning",
        "comparison": "Sammenligning",
        "tool": "Beregner eller værktøj",
        "transactional": "Køb eller handling",
        "navigational": "Navigation",
        "informational": "Information",
    }
    with st.container(border=True):
        st.subheader("Vurderet søgeintention")
        st.write(
            f"**{labels.get(str(intent.get('type')), 'Ukendt intention')}**"
        )
        st.write(str(intent.get("summary") or "Ingen forklaring gemt."))
        confidence = int(intent.get("confidence") or 0)
        st.caption(f"Sikkerhed: {confidence} %")
        if intent.get("ambiguous") or confidence < 65:
            st.warning(
                "Søgeintentionen er tvetydig. Kontrollér vurderingen ekstra "
                "grundigt, før du godkender forslaget."
            )
        with st.expander("Se evidens for søgeintentionen"):
            for evidence in intent.get("evidence") or []:
                st.write(f"- {evidence}")


def _render_reason_card(item: dict[str, Any]) -> None:
    with st.container(border=True):
        st.subheader("Hvorfor denne opgave?")
        for sentence in _short_reason(item):
            st.write(sentence)


def _recommended_change(item: dict[str, Any]) -> dict[str, str]:
    approved = item.get("approved_change") or {}
    if approved:
        return approved
    implementation = item.get("implementation") or {}
    return {
        "change_type": "title_meta",
        "current_title": str(implementation.get("current_title") or ""),
        "approved_title": str(implementation.get("new_title") or ""),
        "current_meta": str(implementation.get("current_meta") or ""),
        "approved_meta": str(implementation.get("new_meta") or ""),
    }


def _page_title(item: dict[str, Any], change: dict[str, Any]) -> str:
    return str(
        change.get("current_title")
        or (item.get("candidate") or {}).get("task_title")
        or item["target_url"]
    )


def _short_reason(item: dict[str, Any]) -> list[str]:
    candidate = item.get("candidate") or {}
    raw = str(
        candidate.get("why_selected")
        or candidate.get("expected_effect_reason")
        or "Siden har synlighed i Google, men potentiale for flere klik."
    ).strip()
    sentences = [part.strip() for part in raw.replace("!", ".").split(".") if part.strip()]
    first = (sentences[0] + ".") if sentences else raw
    second = "En bedre title og metabeskrivelse vurderes at kunne give flere klik."
    return [first, second][:2]


def _has_concrete_change(content: dict[str, Any]) -> bool:
    return bool(
        content.get("change_type") == "title_meta"
        and str(content.get("approved_title", "")).strip()
        and str(content.get("approved_meta", "")).strip()
    )


def _load_daily_work_styles() -> None:
    st.markdown(
        """
        <style>
          [data-testid="stMainBlockContainer"] {max-width: 880px;}
          [data-testid="stVerticalBlockBorderWrapper"] {padding: .7rem; margin: 1.3rem 0;}
          .stButton button {min-height: 3.25rem; font-size: 1.05rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _active_websites(registry: WebsiteRegistry) -> list[dict[str, Any]]:
    return [
        item for item in registry.get_all()
        if item.get("active")
        and item.get("status") not in {"phasing_out", "archived", "cancelled"}
    ]


def _render_website_filter(websites: list[dict[str, Any]]) -> str:
    options = [ALL_WEBSITES] + [item["website"] for item in websites]
    query_value = st.query_params.get("website")
    current = st.session_state.get(
        FILTER_SESSION_KEY,
        query_value if query_value in options else ALL_WEBSITES,
    )
    if current not in options:
        current = ALL_WEBSITES
        st.session_state[FILTER_SESSION_KEY] = current
    if st.session_state.get(FILTER_WIDGET_KEY) not in options:
        st.session_state[FILTER_WIDGET_KEY] = current
    selected = st.selectbox(
        "Websitefilter",
        options,
        index=options.index(current),
        key=FILTER_WIDGET_KEY,
        on_change=_store_website_filter,
        help=(
            "Vælg Alle websites for at få den vigtigste opgave på tværs, "
            "eller afgræns til ét website."
        ),
    )
    st.session_state[FILTER_SESSION_KEY] = selected
    if selected == ALL_WEBSITES:
        if "website" in st.query_params:
            del st.query_params["website"]
    elif st.query_params.get("website") != selected:
        st.query_params["website"] = selected
    return selected


def _store_website_filter() -> None:
    st.session_state[FILTER_SESSION_KEY] = st.session_state[FILTER_WIDGET_KEY]


def _render_empty_state(
    queue: WorkQueueService,
    selected: str,
    websites: list[dict[str, Any]],
    *, reason: str | None = None, candidate_count: int = 0,
) -> None:
    messages = {
        "existing_draft_queue_failed": (
            "En færdig opgave blev fundet, men arbejdskøen kunne ikke opdateres."
        ),
        "candidates_require_generation": (
            f"{candidate_count} kandidater findes, men AI-forslaget kunne ikke genereres."
        ),
        "all_candidates_locked": (
            "Alle kandidater for dette website er låst af aktive eksperimenter."
        ),
        "generation_failed": "AI-genereringen fejlede. Prøv igen senere.",
        "reviewer_failed": (
            "AI-forslaget blev genereret, men kunne ikke reviewer-godkendes."
        ),
        "missing_search_console_data": (
            "Der mangler Search Console-data for dette website."
        ),
        "no_eligible_candidates": (
            "Ingen kandidat opfylder de aktuelle udvælgelseskriterier."
        ),
    }
    if reason in {
        "existing_draft_queue_failed", "generation_failed", "reviewer_failed"
    }:
        st.error(messages[reason])
        return
    if reason in messages:
        st.info(messages[reason])
        return
    if selected == ALL_WEBSITES:
        st.success("Der er ingen klar opgave lige nu.")
        st.write(
            "Alle aktuelle kandidater er enten under forberedelse, "
            "implementeret, under måling eller afventer nye data."
        )
        return
    names = {
        item["website"]: item.get("display_name") or item["website"]
        for item in websites
    }
    label = names.get(selected, selected)
    st.success(f"Der er ingen klar opgave for {label} lige nu.")
    st.write(
        "Opgaver kan være under forberedelse, allerede implementeret, "
        "under måling eller afvente nye data."
    )
    if queue.current() is not None:
        st.info(
            'Der findes klare opgaver på andre websites. Vælg "Alle websites" '
            "for at se den vigtigste."
        )


if __name__ == "__main__":
    main()
