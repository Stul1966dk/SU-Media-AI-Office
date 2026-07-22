"""The single, focused surface for today's reviewed SEO change."""

import base64
import sys
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALL_WEBSITES = "Alle websites"
FILTER_SESSION_KEY = "daily_work_website_filter"
FILTER_WIDGET_KEY = "daily_work_website_filter_widget"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.title_optimizer import TitleOptimizer
from core.ai_service import AIService
from core.daily_work_preparation import DailyWorkPreparationService
from core.seo_experiment_engine import SEOExperimentEngine
from core.website_registry import WebsiteRegistry
from core.work_queue_service import WorkQueueService
from dashboard.components.database import open_database
from dashboard.components.ui import load_styles, render_sidebar


def _optimizer(database: Any) -> TitleOptimizer:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return TitleOptimizer(
        database=database,
        website_registry=WebsiteRegistry(database),
        ai_service=AIService(),
    )


def main() -> None:
    st.set_page_config(
        page_title="Aktuel opgave", page_icon="✓", layout="centered"
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    _load_daily_work_styles()
    render_sidebar(show_website_selector=False)
    st.title("Aktuel opgave")

    database = open_database()
    try:
        registry = WebsiteRegistry(database)
        queue = WorkQueueService(
            database,
            registry,
            experiment_engine=SEOExperimentEngine(database),
        )
        websites = _active_websites(registry)
        selected = _render_website_filter(websites)
        website_id = None if selected == ALL_WEBSITES else selected
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


def _render_recommendation(
    database: Any, queue: WorkQueueService, item: dict[str, Any]
) -> None:
    change = _recommended_change(item)
    if not _has_concrete_change(change):
        st.error("Opgaven er ikke komplet og kan derfor ikke vises endnu.")
        return

    _render_page_card(item, change)
    _render_change_card(item, change)
    _render_reason_card(item)

    accept_column, skip_column = st.columns(2)
    accept = accept_column.button(
        "🟢 Accepter opgave", type="primary", use_container_width=True
    )
    skip = skip_column.button(
        "⚪ Spring over", use_container_width=True
    )
    if accept:
        try:
            queue.approve(
                item["id"],
                title=change["approved_title"],
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
        use_container_width=True,
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
        st.markdown(
            f"<div class='recommended-copy'>{escape(change['approved_title'])}</div>",
            unsafe_allow_html=True,
        )
        _copy_button("Kopiér title", change["approved_title"], f"title-{item['id']}")
        st.write("**Ny metabeskrivelse**")
        st.markdown(
            f"<div class='recommended-copy'>{escape(change['approved_meta'])}</div>",
            unsafe_allow_html=True,
        )
        _copy_button("Kopiér metabeskrivelse", change["approved_meta"], f"meta-{item['id']}")


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


def _copy_button(label: str, value: str, key: str) -> None:
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    components.html(
        f"""
        <button id="{escape(key)}" class="copy-button"
          onclick='navigator.clipboard.writeText(
                     new TextDecoder().decode(
                       Uint8Array.from(atob("{encoded}"), c=>c.charCodeAt(0))));
                   this.textContent="Kopieret"'>
          {escape(label)}
        </button>
        <style>
          .copy-button {{font: 600 16px sans-serif; padding: 10px 16px;
            border: 1px solid #b8bec7; border-radius: 8px; background: white;
            cursor: pointer;}}
        </style>
        """,
        height=52,
    )


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
          .recommended-copy {font-size: 1.12rem; line-height: 1.6; padding: .9rem 1rem;
            margin: .35rem 0 .55rem; border-radius: .6rem; background: #f3f6f9;
            color: #17212b !important; font-weight: 500;
            border: 1px solid #cbd5e1; overflow-wrap: anywhere;
            white-space: normal;}
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
