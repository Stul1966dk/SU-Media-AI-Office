"""The single, focused surface for today's reviewed SEO change."""

import importlib
import json
import re
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


class NoSafeInternalLinkError(ValueError):
    """Raised when no relevant and unlocked internal-link source exists."""


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
from core.prompt_guidelines import PromptGuidelines
from core.website_registry import WebsiteRegistry
from connectors.wordpress_connector import WordPressConnector
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
from dashboard.components.ui import (
    load_styles,
    render_page_link,
    render_sidebar,
)
from dashboard.components.website_selector import set_selected_website

task_deliverables_module = importlib.reload(task_deliverables_module)
fallback_task_deliverable = task_deliverables_module.fallback_task_deliverable
format_deliverable = task_deliverables_module.format_deliverable
format_title_meta_option = task_deliverables_module.format_title_meta_option
generate_task_deliverable = task_deliverables_module.generate_task_deliverable
prefer_pipe_separator = task_deliverables_module.prefer_pipe_separator
split_title_meta_option = task_deliverables_module.split_title_meta_option
validate_content_change = task_deliverables_module.validate_content_change
validate_content_novelty = task_deliverables_module.validate_content_novelty
validate_internal_link = task_deliverables_module.validate_internal_link


def _optimizer(database: Any) -> TitleOptimizer:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return TitleOptimizer(
        database=database,
        website_registry=WebsiteRegistry(database),
        ai_service=AIService(),
    )


def main() -> None:
    st.set_page_config(
        page_title="I dag", page_icon="✓", layout="wide"
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    _load_daily_work_styles()
    render_sidebar(show_website_selector=False)
    st.markdown(
        """
        <section class="daily-hero">
          <span class="daily-eyebrow">AI Office</span>
          <h1>Her er de vigtigste opgaver</h1>
          <p>Ét tydeligt næste trin ad gangen. Resten viser vi, når du får brug for det.</p>
        </section>
        """,
        unsafe_allow_html=True,
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
        _render_daily_summary(database, websites)
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
        priority_tasks = _filter_unlocked_recommendations(
            database, priority_tasks
        )
        priority_tasks = traffic_recommendations_module.expand_daily_work_types(
            priority_tasks,
            content_urls_by_website=_content_urls_by_website(
                database, active_ids
            ),
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


def _content_urls_by_website(
    database: Any, website_ids: set[str]
) -> dict[str, list[str]]:
    """Return the persisted page inventory used to qualify link candidates."""
    result: dict[str, list[str]] = {}
    for website_id in sorted(website_ids):
        try:
            rows = database.get_content(website_id)
        except Exception:
            rows = []
        result[website_id] = [
            str(row.get("url") or row.get("link") or "").strip()
            for row in rows
            if str(row.get("url") or row.get("link") or "").strip()
        ]
    return result


def _filter_unlocked_recommendations(
    database: Any, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Never offer a new change on a URL that is already being measured."""
    experiments = SEOExperimentEngine(database)
    return [
        item
        for item in rows
        if not item.get("target_url")
        or not experiments.is_url_locked(str(item["target_url"]))
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
        _render_guided_progress(str(actionable.get("stage") or "draft"))
        _render_workflow_card(database, actionable, primary=True)


def _render_workflow_card(
    database: Any, item: dict[str, Any], *, primary: bool
) -> None:
    with st.container(border=True):
        st.caption("DIN NÆSTE OPGAVE")
        st.markdown(f"## {item['title']}")
        st.write(f"**{item['website']}** · {item['status_label']}")
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

    _render_approved_escape_actions(database, item)

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


def _render_approved_escape_actions(
    database: Any, item: dict[str, Any]
) -> None:
    """Never trap the user inside an approved task."""
    st.markdown("### Vil du arbejde videre med noget andet?")
    st.caption(
        "Du kan udsætte opgaven uden at miste det godkendte forslag."
    )
    postpone_until = _recommended_postpone_date(
        database, str(item.get("target_url") or "")
    )
    postpone_column, another_column, portfolio_column = st.columns(3)
    if postpone_column.button(
        f"Udsæt til {postpone_until.strftime('%d.%m.%Y')}",
        key=f"postpone-approved-{item['recommendation_key']}",
        help=(
            "Skjuler opgaven indtil den aktive måling på siden er afsluttet. "
            "Det godkendte forslag bevares."
        ),
    ):
        try:
            _workflow(database).snooze_decision(
                str(item["recommendation_key"]), postpone_until
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _finish_daily_action(
                f"Opgaven er udsat til {postpone_until.strftime('%d.%m.%Y')}."
            )
    if another_column.button(
        "Vælg en anden opgave",
        key=f"choose-other-{item['recommendation_key']}",
        help=(
            "Skjuler denne opgave til i morgen og viser den næste ledige "
            "opgave."
        ),
    ):
        tomorrow = date.today() + timedelta(days=1)
        try:
            _workflow(database).snooze_decision(
                str(item["recommendation_key"]), tomorrow
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _finish_daily_action(
                "Opgaven er gemt til senere. Her er den næste ledige opgave."
            )
    with portfolio_column:
        render_page_link(
            "pages/19_Portefolje.py",
            label="Tilbage til Portefølje",
        )


def _recommended_postpone_date(database: Any, target_url: str) -> date:
    """Prefer the active experiment's evaluation date over a fixed delay."""
    active = database.get_seo_experiments(
        target_url=target_url,
        statuses=("approved", "running", "waiting_for_data",
                  "ready_for_evaluation"),
    )
    dates = [
        date.fromisoformat(str(item["planned_evaluation_date"]))
        for item in active
        if item.get("planned_evaluation_date")
    ]
    future_dates = [value for value in dates if value > date.today()]
    return min(future_dates) if future_dates else date.today() + timedelta(
        days=14
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
            "search_intent", "content_opportunity_type", "missing_topic",
            "evidence_queries", "duplication_check",
        ))
    ):
        _render_content_update(deliverable)
        return
    if (
        deliverable.get("deliverable_type") == "internal_links"
        and all(deliverable.get(field) for field in (
            "source_url", "destination_url", "anchor_text", "link_location",
            "current_sentence", "linked_sentence",
        ))
    ):
        _render_internal_link(deliverable)
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
    labels = {
        "existing_section": "Udbyg en eksisterende side",
        "new_category": "Ny kategoritekst",
        "new_article": "Ny artikel",
        "new_blog_post": "Nyt blogindlæg",
    }
    st.caption(labels.get(
        str(deliverable.get("content_opportunity_type")),
        "Ukendt indholdstype",
    ))
    if deliverable.get("content_opportunity_type") != "existing_section":
        st.write("**Foreslået titel**")
        st.code(
            str(deliverable.get("proposed_title") or ""),
            language=None,
            wrap_lines=True,
        )
        st.write("**Foreslået URL**")
        st.code(
            str(deliverable.get("proposed_slug") or ""),
            language=None,
            wrap_lines=True,
        )
        st.write("**Disposition**")
        for index, row in enumerate(deliverable.get("outline") or [], 1):
            st.write(f"{index}. {row}")
    st.write("**Placering på siden**")
    st.info(str(deliverable.get("content_location") or "Ikke angivet"))
    is_new_section = str(deliverable.get("current_content") or "").startswith(
        "Ny sektion"
    )
    if not is_new_section:
        st.write("**Erstat denne eksisterende tekst**")
        st.code(
            str(deliverable.get("current_content") or "Ikke identificeret"),
            language=None,
            wrap_lines=True,
        )
    st.write(
        "**Indsæt denne nye tekst**"
        if is_new_section
        else "**Med denne færdige tekst**"
    )
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
    with st.expander("Se datagrundlag"):
        st.write(f"**Manglende emne:** {deliverable.get('missing_topic')}")
        st.write(
            "**Search Console-evidens:** "
            + ", ".join(deliverable.get("evidence_queries") or [])
        )
        st.write(f"**Søgeintention:** {deliverable.get('search_intent')}")
        st.write(f"**Dubletkontrol:** {deliverable.get('duplication_check')}")


def _render_internal_link(deliverable: dict[str, Any]) -> None:
    st.write("**Kildeside – her skal linket indsættes**")
    st.markdown(
        f"[{deliverable['source_url']}]({deliverable['source_url']})"
    )
    st.write("**Destinationsside – linket skal pege hertil**")
    st.markdown(
        f"[{deliverable['destination_url']}]"
        f"({deliverable['destination_url']})"
    )
    st.write("**Placering på kildesiden**")
    st.info(str(deliverable["link_location"]))
    st.write("**Nuværende passage**")
    st.code(
        str(deliverable["current_sentence"]),
        language=None,
        wrap_lines=True,
    )
    st.write("**Ankertekst**")
    st.code(
        str(deliverable["anchor_text"]),
        language=None,
        wrap_lines=True,
    )
    st.write("**Færdig passage med link**")
    st.code(
        str(deliverable["linked_sentence"]),
        language=None,
        wrap_lines=True,
    )
    st.caption(
        "Kopiér den færdige passage, og link kun den viste ankertekst."
    )


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
            try:
                with st.spinner("AI Office udarbejder arbejdsinstruksen…"):
                    deliverable, used_fallback = _generate_deliverable(
                        database, _recommendation_from_work_item(item)
                    )
            except ValueError as error:
                st.warning(str(error))
                return
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
                    "Anbefalet løsning:",
                    (
                        "Indholdstype:"
                        if "Indholdstype:" in description
                        else "Placering:"
                    ),
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
                    "Søgeintention:",
                    (
                        "Foreslået titel:"
                        if "Foreslået titel:" in description
                        else "Begrundelse:"
                    ),
                ),
            })
            content_gap_headings = (
                "Indholdstype:", "Manglende emne:",
                "Search Console-evidens:", "Dubletkontrol:",
            )
            if all(
                heading in description for heading in content_gap_headings
            ):
                result.update({
                    "content_opportunity_type": section(
                        "Indholdstype:", "Manglende emne:"
                    ),
                    "missing_topic": section(
                        "Manglende emne:", "Search Console-evidens:"
                    ),
                    "evidence_queries": [
                        row.strip() for row in section(
                            "Search Console-evidens:", "Dubletkontrol:"
                        ).split(",") if row.strip()
                    ],
                    "duplication_check": section(
                        "Dubletkontrol:", "Placering:"
                    ),
                })
                if "Foreslået titel:" in description:
                    result.update({
                        "proposed_title": section(
                            "Foreslået titel:", "Foreslået URL:"
                        ),
                        "proposed_slug": section(
                            "Foreslået URL:", "Disposition:"
                        ),
                        "outline": _strip_list_markers(section(
                            "Disposition:", "Begrundelse:"
                        )),
                    })
                else:
                    result.update({
                        "proposed_title": "",
                        "proposed_slug": "",
                        "outline": [],
                    })
    if result["deliverable_type"] == "internal_links":
        optional_headings = (
            "Kildeside:", "Destinationsside:", "Ankertekst:",
            "Placering på kildesiden:", "Nuværende passage:",
            "Passage med link:",
        )
        if all(heading in description for heading in optional_headings):
            result.update({
                "recommended_option": section(
                    "Anbefalet løsning:", "Kildeside:"
                ),
                "source_url": section(
                    "Kildeside:", "Destinationsside:"
                ),
                "destination_url": section(
                    "Destinationsside:", "Ankertekst:"
                ),
                "anchor_text": section(
                    "Ankertekst:", "Placering på kildesiden:"
                ),
                "link_location": section(
                    "Placering på kildesiden:", "Nuværende passage:"
                ),
                "current_sentence": section(
                    "Nuværende passage:", "Passage med link:"
                ),
                "linked_sentence": section(
                    "Passage med link:", "Begrundelse:"
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
        details = [str(item["website"]), str(item["priority"])]
        if item.get("estimated_minutes"):
            details.append(f"{item['estimated_minutes']} minutter")
        st.caption(" · ".join(details))
        if item.get("target_url"):
            st.markdown(
                f"**Side:** [{item['target_url']}]({item['target_url']})"
            )
        with st.expander("Se opgaveforklaring og måling"):
            st.write(item.get("recommended_action") or item["description"])
            if item.get("completion_criterion"):
                st.write(f"**Færdig når:** {item['completion_criterion']}")
            if item.get("measurement_method"):
                st.write(f"**Måling:** {item['measurement_method']}")
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
        _render_new_decision_actions(database, item)
    _render_priority_explanation(item)


def _render_new_decision_actions(
    database: Any, item: dict[str, Any]
) -> None:
    title = str(item["description"])
    key = str(item["task_key"])
    state_key = f"task-deliverable:{key}"
    if state_key not in st.session_state:
        try:
            with st.spinner("AI Office udarbejder det konkrete forslag…"):
                deliverable, used_fallback = _generate_deliverable(
                    database, item
                )
        except ValueError as error:
            st.warning(str(error))
            return
        st.session_state[state_key] = deliverable
        st.session_state[f"{state_key}:fallback"] = used_fallback
    deliverable = st.session_state[state_key]
    if st.session_state.get(f"{state_key}:fallback"):
        st.warning(
            "AI-forbindelsen var ikke tilgængelig. Forslaget er lavet "
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
    if item.get("experiment_type") == "internal_links":
        _refresh_sparse_internal_link_content(
            database, str(item.get("website") or "")
        )
    public_context = []
    has_target_context = False
    if item.get("target_url"):
        try:
            current_page = _optimizer(database).analyze_current_snippet({
                "target_url": item["target_url"],
            })
            public_context.append({
                "relation": "berørt side",
                **current_page,
            })
            has_target_context = bool(current_page.get("content_sections"))
        except Exception:
            pass
    try:
        content_rows = database.get_content(item["website"])
        if not has_target_context:
            target = str(item.get("target_url") or "").rstrip("/").casefold()
            for row in content_rows:
                if not row.get("content_sections") and row.get(
                    "content_sections_json"
                ):
                    try:
                        row["content_sections"] = json.loads(
                            row["content_sections_json"]
                        )
                    except (TypeError, ValueError):
                        row["content_sections"] = []
            stored_target = next(
                (
                    row for row in content_rows
                    if str(row.get("url") or "").rstrip("/").casefold()
                    == target
                    and row.get("content_sections")
                ),
                None,
            )
            if stored_target:
                public_context.append({
                    "relation": "berørt side",
                    "title": stored_target.get("title", ""),
                    "url": stored_target.get("url", ""),
                    "h1": next(
                        (
                            section.get("text", "")
                            for section in stored_target["content_sections"]
                            if section.get("element") == "h1"
                        ),
                        "",
                    ),
                    "content_excerpt": stored_target.get("content_text", ""),
                    "content_sections": stored_target["content_sections"],
                })
        candidate_rows = content_rows
        if item.get("experiment_type") == "internal_links":
            candidate_rows = _rank_internal_link_candidates(
                item,
                content_rows,
                is_locked=SEOExperimentEngine(database).is_url_locked,
            )
            if not candidate_rows:
                raise NoSafeInternalLinkError(
                    "AI Office fandt ingen emnemæssigt relevant kildeside, "
                    "som samtidig er fri for aktive opgaver eller målinger. "
                    "Der vises derfor ikke et usikkert linkforslag."
                )
        context_rows = (
            candidate_rows[:8]
            if item.get("experiment_type") == "internal_links"
            else candidate_rows
        )
        for row in context_rows:
            public_context.append({
                "relation": "mulig relateret side",
                "title": row.get("title", ""),
                "url": row.get("url") or row.get("link") or "",
                "excerpt": _usable_content_excerpt(row),
            })
    except NoSafeInternalLinkError:
        raise
    except Exception:
        pass
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    guided_item = {
        **item,
        "_prompt_guidelines": PromptGuidelines(database).text_for(
            (
                "content_gap"
                if item.get("forced_content_mode") == "content_gap"
                else task_deliverables_module._deliverable_type(item)
            )
        ),
    }
    try:
        return generate_task_deliverable(
            guided_item,
            ai_service=AIService(),
            public_context=public_context,
        ), False
    except Exception:
        fallback = fallback_task_deliverable(
            item, public_context=public_context
        )
        if fallback["deliverable_type"] == "content_update":
            validate_content_novelty(
                fallback, public_context=public_context
            )
        return fallback, True


def _usable_content_excerpt(row: dict[str, Any]) -> str:
    """Prefer intact article text when a stored excerpt has broken letters."""
    excerpt = str(row.get("excerpt") or row.get("content") or "").strip()
    content_text = str(row.get("content_text") or "").strip()
    broken_letter = re.search(
        r"(?<=[A-Za-zÆØÅæøå])\?(?=[A-Za-zÆØÅæøå])"
        r"|(?<![A-Za-zÆØÅæøå])[A-Za-zÆØÅæøå]\?(?=\s|$)",
        excerpt,
    )
    if broken_letter and content_text:
        excerpt = content_text
    return excerpt[:500]


def _refresh_sparse_internal_link_content(
    database: Any,
    website_id: str,
    *,
    connector_type: Any = WordPressConnector,
) -> bool:
    """Refresh public WordPress content when link evidence is incomplete."""
    if not website_id:
        return False
    existing = [
        row for row in database.get_content(website_id)
        if str(row.get("content_type") or "post").casefold()
        in {"post", "page"}
    ]
    state_reader = getattr(database, "get_integration_state", None)
    sitemap_state = (
        state_reader(f"sitemap:{website_id}") if callable(state_reader) else {}
    ) or {}
    sitemap_content_count = sum(
        str(row.get("content_type") or "") in {"post", "page", "url"}
        for row in sitemap_state.get("urls", [])
    )
    expected_content = max(10, sitemap_content_count)
    if len(existing) >= expected_content:
        return False
    connector = connector_type(website_id=website_id, database=database)
    try:
        if not connector.connect():
            return False
        connector.import_content()
        return True
    finally:
        connector.disconnect()


def _rank_internal_link_candidates(
    item: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    is_locked: Any,
) -> list[dict[str, Any]]:
    """Return only topically relevant, unlocked internal-link sources."""
    target_url = _normalized_page_url(str(item.get("target_url") or ""))
    target_material = " ".join(str(item.get(key) or "") for key in (
        "target_query", "description", "title", "recommended_action",
    ))
    target_terms = _meaningful_link_terms(target_material)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        content_type = str(row.get("content_type") or "post").casefold()
        status = str(row.get("status") or "public").casefold()
        if content_type not in {"post", "page"}:
            continue
        if status not in {"publish", "published", "public"}:
            continue
        url = str(row.get("url") or row.get("link") or "")
        if not url or _normalized_page_url(url) == target_url:
            continue
        if is_locked(url):
            continue
        source_material = " ".join((
            str(row.get("title") or ""),
            _usable_content_excerpt(row),
        ))
        overlap = target_terms & _meaningful_link_terms(source_material)
        if not overlap:
            continue
        ranked.append((len(overlap), row))
    ranked.sort(key=lambda candidate: candidate[0], reverse=True)
    return [row for _, row in ranked]


def _meaningful_link_terms(value: str) -> set[str]:
    stopwords = {
        "artikel", "bedste", "brug", "bruger", "find", "guide", "guiden",
        "hjælp", "hvordan", "hvad", "hvorfor", "ikke", "kan", "komplet",
        "lav", "laver", "læs", "man", "med", "mere", "opret", "oprette",
        "opretter", "side", "sådan", "til", "trin", "vælg",
    }
    return {
        word
        for word in re.findall(r"[0-9a-zæøå]+", str(value).casefold())
        if len(word) >= 3 and word not in stopwords
    }


def _normalized_page_url(value: str) -> str:
    return str(value or "").strip().rstrip("/").casefold()


def _render_deliverable_for_approval(
    database: Any,
    item: dict[str, Any],
    title: str,
    deliverable: dict[str, Any],
    state_key: str,
) -> None:
    """Show the actual output before allowing an approval."""
    st.markdown("### Forslag")
    _render_deliverable_option(deliverable)
    with st.expander("Se begrundelse, alternativer og kontrol"):
        st.write(f"**Hvorfor:** {deliverable['rationale']}")
        st.write("**Alternativer:**")
        for index, alternative in enumerate(deliverable["alternatives"], 1):
            st.write(f"{index}. {alternative}")
        st.write("**Implementering:**")
        for index, step in enumerate(
            deliverable["implementation_steps"], 1
        ):
            st.write(f"{index}. {step}")
        st.write("**Kontrol før godkendelse:**")
        for check in deliverable["validation_checks"]:
            st.write(f"- {check}")
    if deliverable["deliverable_type"] == "content_update":
        _render_compact_content_approval(
            database, item, title, deliverable, state_key
        )
        return
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
        elif deliverable["deliverable_type"] == "internal_links":
            edited_source = st.text_input(
                "Kildeside",
                value=deliverable["source_url"],
                help="Den eksisterende side, hvor linket skal indsættes.",
            )
            edited_destination = st.text_input(
                "Destinationsside",
                value=deliverable["destination_url"],
                help="Den dokumenterede målside, som linket skal pege på.",
            )
            edited_anchor = st.text_input(
                "Ankertekst",
                value=deliverable["anchor_text"],
            )
            edited_location = st.text_input(
                "Placering på kildesiden",
                value=deliverable["link_location"],
            )
            edited_current = st.text_area(
                "Nuværende passage",
                value=deliverable["current_sentence"],
                height=120,
            )
            edited_linked = st.text_area(
                "Færdig passage med link",
                value=deliverable["linked_sentence"],
                height=150,
                help=(
                    "Kopiér passagen, og opret linket på den angivne "
                    "ankertekst."
                ),
            )
            edited_solution = edited_linked
            reviewed_fields = {
                "source_url": edited_source,
                "destination_url": edited_destination,
                "anchor_text": edited_anchor,
                "link_location": edited_location,
                "current_sentence": edited_current,
                "linked_sentence": edited_linked,
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
        approved = st.form_submit_button("Godkend forslag", type="primary")
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
        if reviewed["deliverable_type"] == "internal_links":
            try:
                validate_internal_link(
                    reviewed,
                    expected_target_url=str(item.get("target_url") or ""),
                )
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


def _render_compact_content_approval(
    database: Any,
    item: dict[str, Any],
    title: str,
    deliverable: dict[str, Any],
    state_key: str,
) -> None:
    """Approve directly and keep duplicate editing fields collapsed."""
    grounded = not str(deliverable.get("content_location") or "").startswith(
        "Placeringen kan ikke fastslås"
    )
    if not grounded:
        st.error(
            "Forslaget kan ikke godkendes, før artikelteksten er hentet, "
            "og en eksisterende placering er identificeret."
        )
    if st.button(
        "Godkend forslag",
        type="primary",
        key=f"approve-content-direct-{item['task_key']}",
        help="Godkender det viste forslag uden at publicere noget.",
        disabled=not grounded,
    ):
        _create_and_approve(
            database, item, title, format_deliverable(deliverable)
        )
    with st.expander("Redigér før godkendelse"):
        with st.form(f"edit-content-deliverable-{item['task_key']}"):
            edited_title = st.text_input("Opgavetitel", value=title)
            edited_location = st.text_input(
                "Placering på siden",
                value=deliverable["content_location"],
            )
            edited_current = st.text_area(
                "Eksisterende tekst",
                value=deliverable["current_content"],
                height=100,
            )
            edited_replacement = st.text_area(
                "Ny færdig tekst",
                value=deliverable["replacement_content"],
                height=220,
            )
            edited = st.form_submit_button(
                "Gem ændringer og godkend", type="primary"
            )
        if edited:
            reviewed = {
                **deliverable,
                "content_location": edited_location,
                "current_content": edited_current,
                "replacement_content": edited_replacement,
                "recommended_option": edited_replacement,
            }
            try:
                validate_content_change(reviewed)
            except ValueError as error:
                st.error(str(error))
            else:
                _create_and_approve(
                    database, item, edited_title, format_deliverable(reviewed)
                )
    if st.button(
        "Lav et nyt forslag",
        key=f"regenerate-{item['task_key']}",
        help="Kasserer det viste forslag og genererer et nyt.",
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
    except Exception:
        st.error(
            "Forslaget kunne ikke godkendes på grund af en teknisk fejl. "
            "Prøv igen, eller genindlæs siden."
        )
    else:
        _finish_daily_action(
            "Forslaget er godkendt. Næste trin er at udføre ændringen "
            "på websitet."
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
    _render_guided_progress("draft")
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
    _render_guided_progress("approved")
    change = item.get("approved_change") or {}
    if not _has_concrete_change(change):
        st.error("Den godkendte ændring er ufuldstændig og kan ikke implementeres.")
        return
    _render_page_card(item, change)
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


def _render_daily_summary(
    database: Any, websites: list[dict[str, Any]]
) -> None:
    """Give the page a compact orientation strip before the work begins."""
    experiments = database.get_seo_experiments()
    active_measurements = sum(
        1
        for item in experiments
        if str(item.get("status") or "").lower()
        in {"active", "running", "measuring", "implemented"}
    )
    st.markdown(
        f"""
        <section class="daily-summary" aria-label="Dagens overblik">
          <div><span class="summary-icon">✓</span><strong>1</strong><small>opgave i dag</small></div>
          <div><span class="summary-icon">◎</span><strong>{len(websites)}</strong><small>aktive websites</small></div>
          <div><span class="summary-icon">↗</span><strong>{active_measurements}</strong><small>aktive målinger</small></div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_guided_progress(stage: str) -> None:
    """Show the user's place in the three-step daily workflow."""
    current = {
        "draft": 1,
        "approved": 2,
        "awaiting_implementation": 2,
        "implemented": 3,
        "measuring": 3,
    }.get(stage, 1)
    steps = (
        ("Se AI-forslaget", "Gennemgå og godkend"),
        ("Ret siden", "Udfør ændringen"),
        ("Registrér ændringen", "Start 28-dages måling"),
    )
    cards = []
    for number, (title, description) in enumerate(steps, 1):
        state = "is-current" if number == current else (
            "is-complete" if number < current else ""
        )
        marker = "✓" if number < current else str(number)
        cards.append(
            f'<div class="daily-step {state}">'
            f'<span class="step-number">{marker}</span>'
            f'<span><strong>{title}</strong><small>{description}</small></span>'
            "</div>"
        )
    st.markdown(
        '<section class="daily-progress" aria-label="Opgavens trin">'
        + "".join(cards)
        + "</section>",
        unsafe_allow_html=True,
    )


def _load_daily_work_styles() -> None:
    st.markdown(
        """
        <style>
          :root {
            --daily-bg: #f5f4f8;
            --daily-card: #ffffff;
            --daily-text: #222037;
            --daily-muted: #6f6a7d;
            --daily-border: #dedbe8;
            --daily-purple: #6d35c5;
            --daily-purple-soft: #f0eafd;
            --daily-green: #18845d;
            --daily-green-soft: #eaf7f1;
          }
          .stApp {background: var(--daily-bg);}
          [data-testid="stHeader"] {background: rgba(245, 244, 248, 0.92);}
          [data-testid="stMainBlockContainer"] {
            max-width: 1180px;
            padding-top: 2.5rem;
            padding-bottom: 4rem;
          }
          .daily-hero {margin: 0 0 1.4rem;}
          .daily-eyebrow {
            color: var(--daily-purple);
            font-size: .78rem;
            font-weight: 800;
            letter-spacing: .1em;
            text-transform: uppercase;
          }
          .daily-hero h1 {
            color: var(--daily-text);
            font-size: clamp(1.75rem, 3vw, 2.55rem);
            letter-spacing: -.035em;
            line-height: 1.12;
            margin: .35rem 0 .45rem;
          }
          .daily-hero p {color: var(--daily-muted); margin: 0;}
          .daily-summary {
            background: var(--daily-card);
            border: 1px solid var(--daily-border);
            border-radius: 1rem;
            box-shadow: 0 8px 28px rgba(48, 37, 72, .06);
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            margin: 1.25rem 0 1.5rem;
            overflow: hidden;
          }
          .daily-summary > div {
            align-items: center;
            display: grid;
            gap: .05rem .75rem;
            grid-template-columns: 2.5rem auto;
            padding: 1rem 1.25rem;
          }
          .daily-summary > div + div {border-left: 1px solid var(--daily-border);}
          .daily-summary strong {color: var(--daily-text); font-size: 1.15rem;}
          .daily-summary small {color: var(--daily-muted);}
          .summary-icon {
            align-items: center;
            background: var(--daily-purple-soft);
            border-radius: .7rem;
            color: var(--daily-purple);
            display: flex;
            font-size: 1.15rem;
            grid-row: 1 / span 2;
            height: 2.5rem;
            justify-content: center;
          }
          .daily-progress {
            display: grid;
            gap: .75rem;
            grid-template-columns: repeat(3, 1fr);
            margin: 1.75rem 0 1rem;
          }
          .daily-step {
            align-items: center;
            background: #eeecf2;
            border: 1px solid transparent;
            border-radius: .85rem;
            color: var(--daily-muted);
            display: flex;
            gap: .8rem;
            padding: .85rem 1rem;
          }
          .daily-step.is-current {
            background: var(--daily-purple-soft);
            border-color: #cbb7ee;
            color: var(--daily-text);
          }
          .daily-step.is-complete {
            background: var(--daily-green-soft);
            color: var(--daily-green);
          }
          .step-number {
            align-items: center;
            background: #fff;
            border: 1px solid currentColor;
            border-radius: 999px;
            display: flex;
            flex: 0 0 2rem;
            height: 2rem;
            justify-content: center;
            font-weight: 750;
          }
          .daily-step.is-current .step-number {
            background: var(--daily-purple);
            border-color: var(--daily-purple);
            color: #fff;
          }
          .daily-step strong, .daily-step small {display: block;}
          .daily-step small {font-size: .78rem; margin-top: .12rem;}
          [data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--daily-card);
            border-color: var(--daily-border);
            border-radius: 1rem;
            box-shadow: 0 8px 28px rgba(48, 37, 72, .055);
            padding: .6rem;
          }
          [data-testid="stVerticalBlockBorderWrapper"] {
            margin-block: 1.25rem;
          }
          [data-testid="stExpander"] {
            background: rgba(255, 255, 255, .55);
            border-color: var(--daily-border);
            border-radius: .8rem;
          }
          [data-testid="stMain"] [data-baseweb="select"] > div,
          [data-testid="stMain"] [data-testid="stSelectbox"] [role="group"],
          [data-testid="stMain"] [data-testid="stSelectbox"] input,
          [data-testid="stTextInput"] input,
          [data-testid="stTextArea"] textarea {
            background: #fff !important;
            border-color: var(--daily-border) !important;
            color: var(--daily-text) !important;
          }
          [data-testid="stMain"] [data-baseweb="select"] *,
          [data-testid="stMain"] [data-baseweb="select"] svg,
          [data-testid="stMain"] [data-testid="stSelectbox"] input,
          [data-testid="stMain"] [data-testid="stSelectbox"] button {
            color: var(--daily-text) !important;
            fill: var(--daily-text) !important;
          }
          .stButton button {
            border-radius: .7rem;
            min-height: 3rem;
            font-size: .95rem;
          }
          .stButton button[kind="primary"],
          [data-testid="stFormSubmitButton"] button[kind="primary"] {
            background: var(--daily-purple);
            border-color: var(--daily-purple);
            color: #fff;
          }
          [data-testid="stCode"] {
            background: #f8f7fa;
            border: 1px solid var(--daily-border);
            border-radius: .75rem;
          }
          [data-testid="stMain"] h1,
          [data-testid="stMain"] h2,
          [data-testid="stMain"] h3,
          [data-testid="stMain"] p,
          [data-testid="stMain"] label,
          [data-testid="stMain"] [data-testid="stMarkdownContainer"] {
            color: var(--daily-text);
          }
          [data-testid="stCaptionContainer"], .stCaption {
            color: var(--daily-muted);
          }
          @media (max-width: 760px) {
            .daily-summary, .daily-progress {grid-template-columns: 1fr;}
            .daily-summary > div + div {
              border-left: 0;
              border-top: 1px solid var(--daily-border);
            }
          }
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
