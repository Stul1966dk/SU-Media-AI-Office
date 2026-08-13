"""Approval-only dashboard for title and meta proposals."""

import sys
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.title_optimizer import (
    TitleOptimizer, TitleOptimizationValidationError,
)
from core.ai_service import AIService
from core.website_registry import WebsiteRegistry
from dashboard.components.database import open_database
from dashboard.components.formatting import format_datetime, format_status
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_next_step, render_sidebar
from dashboard.components.website_selector import get_selected_website_id


def _optimizer(database: Any) -> TitleOptimizer:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return TitleOptimizer(
        database=database, website_registry=WebsiteRegistry(database),
        ai_service=AIService(),
    )


def main() -> None:
    st.set_page_config(
        page_title="Title optimering", page_icon="✍️", layout="wide"
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Title optimering")
    render_help_panel(
        purpose="Lav tre målbare title- og metabeskrivelsesforslag til én URL.",
        requirements=(
            "To Search Console-perioder, offentlig adgang til siden og Claude."
        ),
        actions="Generér, redigér, godkend eller afvis en kladde.",
        limitations=(
            "Siden publicerer aldrig. Implementering sker manuelt uden for "
            "AI Office og skal bagefter markeres eksplicit."
        ),
    )
    render_next_step(
        text=(
            "Brug værktøjet til en specialiseret title/meta-analyse. Det "
            "daglige opgaveflow og næste handling findes på I dag."
        ),
        path="app.py",
        label="Tilbage til I dag",
    )
    database = open_database()
    optimizer = _optimizer(database)
    try:
        website_id = get_selected_website_id()
        requested_queue_id = st.query_params.get("queue_item")
        requested_item = None
        if requested_queue_id and str(requested_queue_id).isdigit():
            requested_item = database.get_work_queue_item(
                int(requested_queue_id)
            )
        if requested_item and not requested_item.get("draft_id"):
            st.info(
                "Du er ved at oprette konkrete forslag til "
                f"{requested_item['target_url']}."
            )
            if st.button(
                "Opret forslag til denne opgave", type="primary",
                key=f"queue-draft-{requested_item['id']}",
            ):
                with st.spinner("Analyserer siden og opretter forslag…"):
                    try:
                        candidate = dict(requested_item["candidate"])
                        candidate.update({
                            "website": requested_item["website_id"],
                            "target_url": requested_item["target_url"],
                            "target_query": requested_item["target_query"],
                            "clicks": candidate.get("current_clicks", 0),
                            "impressions": candidate.get(
                                "current_impressions", 0
                            ),
                            "ctr": candidate.get("current_ctr", 0),
                            "position": candidate.get("current_position", 0),
                            "period": "",
                            "reason": candidate.get(
                                "expected_effect_reason", ""
                            ),
                            "confidence": candidate.get("confidence", 0),
                        })
                        draft_id = optimizer.run_for_candidate(candidate)
                        database.update_work_queue_item(
                            requested_item["id"], {"draft_id": draft_id}
                        )
                        st.session_state["title_draft_id"] = draft_id
                        st.success("Forslagene er klar til godkendelse.")
                        st.rerun()
                    except Exception as error:
                        st.error("Forslagene kunne ikke oprettes.")
                        with st.expander("Tekniske detaljer"):
                            st.code(type(error).__name__)
                            st.write(str(error)[:300])
        if st.button("Opret title-forslag", type="primary"):
            with st.spinner("Vælger URL og analyserer den offentlige side…"):
                try:
                    draft_id = optimizer.run(website_id)
                    st.session_state["title_draft_id"] = draft_id
                    st.success("Forslagene er klar til godkendelse.")
                except TitleOptimizationValidationError as error:
                    st.error(
                        "Modelforslaget kunne ikke valideres efter ét "
                        "reparationsforsøg."
                    )
                    with st.expander("Tekniske detaljer"):
                        st.code(type(error).__name__)
                        st.write(f"Fase: {error.phase}")
                        if error.missing_fields:
                            st.write("Manglende kritiske felter:")
                            for field in error.missing_fields:
                                st.write(f"- {field}")
                        else:
                            st.write(str(error)[:300])
                except ValueError as error:
                    st.error("Datagrundlaget er ikke klar til title-flowet.")
                    with st.expander("Tekniske detaljer"):
                        st.code("DataRequirementError")
                        st.write(str(error)[:300])
                except Exception as error:
                    st.error("Title-flowet kunne ikke gennemføres.")
                    with st.expander("Tekniske detaljer"):
                        st.code(type(error).__name__)
                        st.write(str(error)[:300])
        draft_website_id = (
            requested_item["website_id"] if requested_item else website_id
        )
        drafts = database.get_title_optimization_drafts(draft_website_id)
        if not drafts:
            st.info(
                "Ingen title-kladder endnu. Knappen vælger automatisk én "
                "egnet, ulåst URL fra det aktive website."
            )
            return
        selected_id = st.selectbox(
            "Kladde", [item["id"] for item in drafts],
            index=next((
                index for index, item in enumerate(drafts)
                if item["id"] == st.session_state.get("title_draft_id")
            ), 0),
            format_func=lambda value: next(
                f"#{item['id']} · {item['target_url']} · "
                f"{format_status(item['status'])}"
                for item in drafts if item["id"] == value
            ),
        )
        draft = next(item for item in drafts if item["id"] == selected_id)
        _render_draft(optimizer, draft)
    finally:
        database.close()


def _render_draft(optimizer: TitleOptimizer, draft: dict[str, Any]) -> None:
    titles = draft["title_proposals"]
    metas = draft["meta_proposals"]
    recommended_title = min(
        draft["recommended_title_index"], len(titles) - 1
    )
    recommended_meta = min(
        draft["recommended_meta_index"], len(metas) - 1
    )
    state_prefix = f"title-choice-{draft['id']}"
    title_index = st.session_state.get(
        state_prefix + "-title", recommended_title
    )
    meta_index = st.session_state.get(
        state_prefix + "-meta", recommended_meta
    )

    st.subheader("AI anbefaler denne ændring")
    st.write("**Side**")
    st.write(draft["current_title"] or "Siden uden en synlig title")
    st.write("**URL**")
    st.link_button(draft["target_url"], draft["target_url"])
    st.write("**Primært søgeord**")
    st.write(draft["target_query"] or "Intet entydigt søgeord fundet")

    search = draft.get("page_analysis", {}).get("search_console", {})
    st.subheader("Kort forklaring")
    if search:
        st.write(
            f"Google viste siden "
            f"{_format_integer(search.get('impressions', 0))} gange "
            f"i perioden, og den lå omkring placering "
            f"{float(search.get('position', 0)):.1f}."
        )
        st.write(
            f"Kun {float(search.get('ctr', 0))*100:.1f}% klikkede på "
            "resultatet. En tydeligere title og metabeskrivelse kan derfor "
            "gøre siden mere attraktiv i søgeresultatet."
        )
    else:
        st.write(
            "Siden bliver vist i Google, men får færre klik end forventet. "
            "En tydeligere title og metabeskrivelse kan gøre resultatet mere "
            "relevant for brugeren."
        )

    st.subheader("Hvad anbefaler AI")
    st.write("Test en ny title og metabeskrivelse.")
    effect = (
        "Høj" if draft["confidence"] >= 80 else
        "Mellem" if draft["confidence"] >= 60 else "Lav"
    )
    st.write(f"**Forventet effekt:** {effect}")
    st.write(
        "**Hvorfor:** Siden har allerede synlighed i Google. Ændringen kan "
        "forbedre antallet af klik uden at ændre selve sideindholdet."
    )

    st.subheader("Title-forslag")
    _proposal_cards(
        titles, "title", recommended_title, state_prefix
    )
    st.subheader("Metabeskrivelser")
    _proposal_cards(
        metas, "meta", recommended_meta, state_prefix
    )
    st.success(
        "AI anbefaler denne kombination:  \n"
        f"**{titles[recommended_title]['text']}**  \n"
        f"{metas[recommended_meta]['text']}"
    )

    if draft["status"] == "awaiting_approval":
        st.subheader("Vælg hvad der skal ske nu")
        columns = st.columns(2)
        if columns[0].button(
            "Godkend anbefalet forslag", type="primary",
            key=state_prefix + "-approve-recommended",
        ):
            _approve(
                optimizer, draft,
                titles[recommended_title]["text"],
                metas[recommended_meta]["text"],
            )
        if columns[1].button(
            "Vælg et andet forslag", key=state_prefix + "-choose"
        ):
            st.session_state[state_prefix + "-mode"] = "choose"
            st.rerun()
        columns = st.columns(2)
        if columns[0].button(
            "Redigér selv", key=state_prefix + "-edit"
        ):
            st.session_state[state_prefix + "-mode"] = "edit"
            st.rerun()
        if columns[1].button(
            "Afvis alle forslag", key=state_prefix + "-reject"
        ):
            optimizer.reject_draft(draft["id"])
            st.rerun()
        mode = st.session_state.get(state_prefix + "-mode")
        if mode == "choose":
            chosen_title = st.radio(
                "Vælg en title", range(len(titles)), index=title_index,
                format_func=lambda index: titles[index]["text"],
                key=state_prefix + "-title",
            )
            chosen_meta = st.radio(
                "Vælg en metabeskrivelse", range(len(metas)),
                index=meta_index,
                format_func=lambda index: metas[index]["text"],
                key=state_prefix + "-meta",
            )
            if st.button("Godkend mit valg", key=state_prefix + "-approve-choice"):
                _approve(
                    optimizer, draft, titles[chosen_title]["text"],
                    metas[chosen_meta]["text"],
                )
        elif mode == "edit":
            edited_title = st.text_input(
                "Din title", value=titles[title_index]["text"],
                key=state_prefix + "-edited-title",
            )
            edited_meta = st.text_area(
                "Din metabeskrivelse", value=metas[meta_index]["text"],
                key=state_prefix + "-edited-meta",
            )
            if st.button(
                "Godkend mine tekster", key=state_prefix + "-approve-edit"
            ):
                _approve(optimizer, draft, edited_title, edited_meta)
    elif draft["status"] == "converted_to_experiment":
        st.success("Forslaget er godkendt.")
        st.write("Der er oprettet:")
        st.write("- én opgave\n- ét planlagt eksperiment\n- én baseline\n- en URL-lås")
        st.warning("**Status: Afventer implementering**")
        st.caption("Intet publiceres automatisk.")
        if st.button("Markér som implementeret", type="primary"):
            try:
                optimizer.mark_implemented(draft["id"])
                st.rerun()
            except ValueError as error:
                st.error(str(error))
    elif draft["status"] == "approved":
        st.success(
            "Implementeringen er registreret. Status: Måleperiode."
        )
        st.write("**Implementeret:** " + format_datetime(draft["implemented_at"]))
    elif draft["status"] == "rejected":
        st.info("Alle forslag er afvist. Der er ikke oprettet en opgave.")

    _technical_details(optimizer, draft, search)


def _proposal_cards(
    proposals: list[dict[str, Any]], kind: str, recommended: int,
    state_prefix: str,
) -> None:
    label = "title" if kind == "title" else "metabeskrivelse"
    for index, proposal in enumerate(proposals):
        with st.container(border=True):
            if index == recommended:
                st.caption("AI anbefaler denne kombination")
            st.write(f"**{proposal['text']}**")
            st.caption(f"{len(proposal['text'])} tegn")
            st.write(proposal.get("reason") or "Forslaget matcher siden.")
            risks = proposal.get("risks") or []
            if risks:
                st.write("**Vær opmærksom på:** " + " ".join(risks[:2]))
            if st.button(
                f"Vælg denne {label}",
                key=f"{state_prefix}-{kind}-card-{index}",
            ):
                st.session_state[f"{state_prefix}-{kind}"] = index
                st.session_state[state_prefix + "-mode"] = "choose"
                st.rerun()


def _approve(
    optimizer: TitleOptimizer, draft: dict[str, Any],
    title: str, meta: str,
) -> None:
    try:
        optimizer.approve_draft(draft["id"], title, meta)
        st.rerun()
    except ValueError as error:
        st.error(str(error))


def _technical_details(
    optimizer: TitleOptimizer, draft: dict[str, Any],
    search: dict[str, Any],
) -> None:
    with st.expander("Se datagrundlag og tekniske detaljer", expanded=False):
        if search:
            st.write(f"**Klik:** {_format_integer(search.get('clicks', 0))}")
            st.write(
                f"**Visninger:** "
                f"{_format_integer(search.get('impressions', 0))}"
            )
            st.write(f"**CTR:** {float(search.get('ctr', 0))*100:.1f}%")
            st.write(
                f"**Placering:** {float(search.get('position', 0)):.1f}"
            )
            st.write(f"**Periode:** {search.get('period', 'Ikke oplyst')}")
        health = optimizer.database.get_seo_health_history(
            website_id=draft["website_id"], period="28d"
        )
        st.write(
            f"**SEO Health:** "
            f"{float(health[0]['score']):.1f}"
            if health else "**SEO Health:** Ikke beregnet"
        )
        st.write("**Datakilder:** Search Console og den offentlige side.")
        st.write(
            "**Kontrol af forslag:** "
            + draft["reviewer"].get("summary", "Forslagene er kontrolleret.")
        )
        limitations = _friendly_limitations(
            draft["analysis"].get("limitations", [])
        )
        if limitations:
            st.write("**Begrænsninger:**")
            for limitation in limitations:
                st.write(f"- {limitation}")
        rejected = (
            draft["reviewer"].get("rejected_titles", [])
            + draft["reviewer"].get("rejected_metas", [])
        )
        if rejected:
            with st.expander(
                f"Forkastede forslag ({len(rejected)})", expanded=False
            ):
                for item in rejected:
                    st.write(f"**{item['proposal'].get('text', 'Uden tekst')}**")
                    for reason in item.get("reasons", []):
                        st.write(f"- {reason}")


def _friendly_limitations(values: list[str]) -> list[str]:
    friendly = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        lower = text.lower()
        if "serp" in lower or "konkurrent" in lower:
            text = (
                "Vi har endnu ikke sammenlignet siden med aktuelle "
                "konkurrenter i Google. Forslagene bygger derfor på sidens "
                "egne data og søgeintentionen."
            )
        if text not in friendly:
            friendly.append(text)
        if len(friendly) == 3:
            break
    return friendly


def _format_integer(value: Any) -> str:
    return f"{int(value or 0):,}".replace(",", ".")


if __name__ == "__main__":
    main()
