"""Dashboard for approval-gated SEO experiments."""

import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.experiment_evaluation import (
    EvaluationRules, RESULT_LABELS as EVALUATION_LABELS,
)
from dashboard.components.database import open_database
from dashboard.components.formatting import format_date, format_datetime
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import (
    load_styles, render_next_step, render_sidebar,
)


STATUS_LABELS = {
    "planned": "Afventer godkendelse", "approved": "Godkendt",
    "running": "Under måling", "waiting_for_data": "Under måling",
    "ready_for_evaluation": "Klar til evaluering",
    "evaluating": "Evaluerer",
    "completed": "Afsluttet", "cancelled": "Annulleret", "failed": "Fejl",
}
RESULT_LABELS = {
    "successful": "Forbedret",
    "partially_successful": "Forbedret",
    "no_measurable_effect": "Uændret",
    "negative_effect": "Forværret",
    "inconclusive": "Kan ikke vurderes endnu",
}
EXPERIMENT_TYPE_LABELS = {
    "title_meta": "Title og metabeskrivelse",
    "internal_links": "Interne links",
    "content_update": "Indholdsopdatering",
    "technical_fix": "Teknisk forbedring",
    "schema": "Strukturerede data",
}
PULSE_LABELS = {
    "Indsamler data": "Under måling",
    "Afventer data": "Under måling",
}
QUALITY_LABELS = {
    "sufficient": "Tilstrækkeligt datagrundlag",
    "insufficient": "Utilstrækkeligt datagrundlag",
}


def main() -> None:
    st.set_page_config(page_title="Resultater", page_icon="🧪", layout="wide")
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("Resultater")
    render_help_panel(
        purpose="Følg aktive målinger og lær af afsluttede ændringer.",
        requirements="En konkret beslutning, URL-data og brugerens godkendelse.",
        actions="Se hvad der måles, hvornår resultatet er klart, og hvad du bør gøre bagefter.",
        limitations="Siden ændrer aldrig et website og starter intet automatisk.",
    )
    render_next_step(
        text=(
            "Følg målingerne her. Gå tilbage til I dag, når ingen resultater "
            "kræver din handling."
        ),
        path="app.py",
        label="Tilbage til I dag",
    )
    database = open_database(read_only=True)
    try:
        experiments = database.get_seo_experiments()
        evaluation_rows = database.get_experiment_evaluations()
        evaluations = {
            item["experiment_id"]: item
            for item in evaluation_rows
        }
        approved_changes = {
            item["experiment_id"]: item
            for item in database.get_approved_changes()
            if item.get("experiment_id")
        }
        learnings = {
            item["experiment_id"]: item
            for item in database.get_experiment_learnings()
        }
        learning_entries = database.get_seo_learning_entries()
        _render_result_overview(experiments, evaluation_rows)
        active = [
            item for item in experiments
            if item["status"] in {
                "approved", "running", "waiting_for_data",
                "ready_for_evaluation", "evaluating",
            }
        ]
        completed = [
            item for item in experiments
            if item["status"] in {"completed", "cancelled", "failed"}
        ]
        st.subheader("Aktive målinger")
        if not active:
            st.info("Ingen aktive målinger. Start med den anbefalede opgave på I dag.")
        for experiment in active:
            _active_card(database, experiment)
        st.subheader("Afsluttede resultater")
        if not completed:
            st.info("Ingen afsluttede eksperimenter endnu.")
        for experiment in completed:
            with st.container(border=True):
                st.write(
                    f"**{experiment['website_id']} · "
                    f"{EVALUATION_LABELS.get(experiment.get('result'), RESULT_LABELS.get(experiment.get('result'), 'Afsluttet'))}**"
                )
                st.write(experiment["target_url"])
                st.write(
                    experiment.get("result_summary") or "Ingen konklusion."
                )
                st.write(
                    "**Anbefalet næste skridt:** "
                    + _next_step(experiment.get("result"))
                )
                with st.expander("Vis evalueringens datagrundlag"):
                    _detail(experiment, learnings.get(experiment["id"]),
                            evaluations.get(experiment["id"]),
                            approved_changes.get(experiment["id"]))
        _render_learning(learning_entries)
    finally:
        database.close()


def _render_result_overview(
    experiments: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
) -> None:
    """Show the outcome users need before the underlying measurements."""
    improvements = {"strong_improvement", "improvement"}
    declines = {"strong_decline", "decline"}
    active_statuses = {
        "approved", "running", "waiting_for_data",
        "ready_for_evaluation", "evaluating",
    }
    improved = sum(
        item.get("result_status") in improvements for item in evaluations
    )
    unchanged = sum(
        item.get("result_status") == "neutral" for item in evaluations
    )
    declined = sum(
        item.get("result_status") in declines for item in evaluations
    )
    active = sum(item.get("status") in active_statuses for item in experiments)
    columns = st.columns(4)
    columns[0].metric("Aktive målinger", active)
    columns[1].metric("Forbedret", improved)
    columns[2].metric("Uændret", unchanged)
    columns[3].metric("Forværret", declined)
    st.caption(
        "Resultatet bygger på gemte før- og efterperioder. Åbn "
        "datagrundlaget på det enkelte resultat, hvis du vil se tallene."
    )


def _render_learning(
    entries: list[dict[str, Any]],
) -> None:
    """Present reusable measured learning without creating another inbox."""
    st.subheader("Dokumenteret læring")
    if not entries:
        st.info(
            "Der er endnu ingen dokumenterede mønstre. Læring opstår først, "
            "når en måling er afsluttet med tilstrækkelige data."
        )
        return
    improved_labels = {
        "Tydeligt forbedret", "Forbedret", "Delvist forbedret"
    }
    columns = st.columns(3)
    columns[0].metric("Dokumenterede observationer", len(entries))
    columns[1].metric(
        "Forbedrede observationer",
        sum(item["classification"] in improved_labels for item in entries),
    )
    columns[2].metric(
        "Gennemsnitlig målt effekt",
        f"{mean(float(item['effect_size']) for item in entries):+.1f} %",
    )
    st.write(
        "Denne læring bruges som historisk evidens, når AI Office "
        "prioriterer kommende anbefalinger."
    )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in entries:
        key = (item["change_type"], item["page_type"])
        grouped.setdefault(key, []).append(item)
    with st.expander("Se dokumenterede mønstre og datakvalitet"):
        for (change_type, page_type), rows in grouped.items():
            count = len(rows)
            effect = mean(float(item["effect_size"]) for item in rows)
            evidence = (
                "Understøttet mønster" if count >= 10
                else "Foreløbigt mønster" if count >= 3
                else "Enkelt observation"
            )
            st.write(f"**{change_type} på {page_type}**")
            st.write(
                f"{count} måling(er) · gennemsnitlig effekt {effect:+.1f} % "
                f"· {evidence}"
            )
            st.caption(
                "Datakvalitet: "
                + ", ".join(sorted({
                    str(item["data_quality"]) for item in rows
                }))
            )


def _summary(item: dict[str, Any]) -> dict[str, Any]:
    planned = item.get("planned_evaluation_date")
    remaining = (
        max(0, (date.fromisoformat(planned) - date.today()).days)
        if planned else ""
    )
    return {
        "Website": item["website_id"], "URL": item["target_url"],
        "Eksperiment": _experiment_type(item["experiment_type"]),
        "Mål": f"{_goal_metric(item['goal_metric'])} {item['target_change_pct']:+.0f}%",
        "Status": STATUS_LABELS.get(item["status"], item["status"]),
        "Start": format_datetime(item["started_at"]) if item["started_at"] else "",
        "Evaluering": format_date(planned) if planned else "",
        "Resterende dage": remaining,
        "Resultat": RESULT_LABELS.get(
            item.get("result"), item.get("result") or ""
        ),
    }


def _detail(
    item: dict[str, Any], learning: dict[str, Any] | None,
    evaluation: dict[str, Any] | None = None,
    approved_change: dict[str, Any] | None = None,
) -> None:
    st.subheader("Eksperimentdetaljer")
    st.write(f"**Hypotese:** {item['hypothesis']}")
    st.write(f"**Ændring:** {item['change_description']}")
    st.write(
        f"**Mål:** {_goal_metric(item['goal_metric'])} skal "
        f"{'stige' if item['goal_direction'] == 'increase' else 'falde'} "
        f"{item['target_change_pct']:.0f}%."
    )
    st.write(f"**Resultat:** {item.get('result_summary') or 'Ikke evalueret'}")
    if learning and learning.get("learning"):
        st.write(f"**Læring:** {learning['learning']}")
    if approved_change:
        st.write("**Implementeret ændring**")
        st.write(f"**Gammel title:** {approved_change.get('current_title') or 'Ikke registreret'}")
        st.write(f"**Ny title:** {approved_change.get('approved_title') or 'Ikke registreret'}")
        st.write(f"**Gammel meta:** {approved_change.get('current_meta') or 'Ikke registreret'}")
        st.write(f"**Ny meta:** {approved_change.get('approved_meta') or 'Ikke registreret'}")
    if evaluation:
        st.write(
            f"**Baselineperiode:** {format_date(evaluation['baseline_start'])}–"
            f"{format_date(evaluation['baseline_end'])}  \n"
            f"**Efterperiode:** {format_date(evaluation['comparison_start'])}–"
            f"{format_date(evaluation['comparison_end'])}"
        )
        columns = st.columns(4)
        columns[0].metric("Klik før", evaluation["clicks_before"])
        columns[1].metric("Klik efter", evaluation["clicks_after"])
        columns[2].metric("CTR før", f"{evaluation['ctr_before']*100:.1f} %")
        columns[3].metric("CTR efter", f"{evaluation['ctr_after']*100:.1f} %")
        position_change = float(evaluation["position_change"])
        position_label = (
            "Positionsforbedring" if position_change > 0
            else "Positionsforværring" if position_change < 0
            else "Position"
        )
        st.write(f"**{position_label}:** {abs(position_change):.1f}")
        st.write(
            "**Samlet vurdering:** "
            + EVALUATION_LABELS.get(
                evaluation["result_status"], evaluation["result_status"]
            )
        )
        st.write(
            "**AI-konklusion:** "
            + (evaluation.get("ai_conclusion") or "Ingen AI-konklusion.")
        )
        for caveat in evaluation.get("caveats", []):
            st.caption(caveat)
        if evaluation["result_status"] == "insufficient_data":
            _insufficient_requirements(evaluation)
        with st.expander("Tekniske detaljer"):
            st.write(
                f"Visninger før/efter: {evaluation['impressions_before']} / "
                f"{evaluation['impressions_after']} "
                f"({evaluation['impressions_absolute_change']:+d})"
            )
            click_relative = evaluation.get("clicks_relative_change")
            impression_relative = evaluation.get("impressions_relative_change")
            ctr_relative = evaluation.get("ctr_relative_change")
            st.write(
                "Relative ændringer: klik "
                f"{click_relative:+.1f} %" if click_relative is not None
                else "Relative ændringer: klik ikke beregnelig"
            )
            st.write(
                f"Visninger {impression_relative:+.1f} %" if impression_relative is not None
                else "Visninger: ikke beregnelig"
            )
            st.write(
                f"CTR {ctr_relative:+.1f} % · "
                f"{evaluation['ctr_percentage_point_change']:+.2f} procentpoint"
                if ctr_relative is not None else
                f"CTR: ikke beregnelig · {evaluation['ctr_percentage_point_change']:+.2f} procentpoint"
            )
            st.write(
                "Datakvalitet: "
                + QUALITY_LABELS.get(
                    evaluation["sample_quality"], "Ikke vurderet"
                )
            )


def _active_card(database: Any, item: dict[str, Any]) -> None:
    snapshots = database.get_experiment_snapshots(item["id"])
    latest = snapshots[-1] if snapshots else {}
    started = (
        date.fromisoformat(item["started_at"][:10])
        if item.get("started_at") else date.today()
    )
    total_days = int(item.get("waiting_period_days") or 28)
    day_number = min(total_days, max(1, (date.today() - started).days + 1))
    measurement_end = started + timedelta(days=total_days - 1)
    evaluation = item.get("planned_evaluation_date")
    remaining = (
        max(0, (date.fromisoformat(evaluation) - date.today()).days)
        if evaluation else ""
    )
    evaluation_rows = database.get_experiment_evaluations(item["id"])
    insufficient = (
        item.get("result") == "insufficient_data" and bool(evaluation_rows)
    )
    with st.container(border=True):
        st.subheader(item["website_id"])
        st.link_button(item["target_url"], item["target_url"])
        implemented_change = next(iter(database.get_approved_changes(
            experiment_id=item["id"]
        )), {})
        implemented_at = (
            implemented_change.get("implemented_at") or item.get("started_at")
        )
        before_period = _date_interval(
            item.get("baseline_start"), item.get("baseline_end")
        )
        measurement_period = _date_interval(
            started.isoformat(), measurement_end.isoformat()
        )
        columns = st.columns(3)
        columns[0].metric("Ændring", _experiment_type(item["experiment_type"]))
        columns[1].metric("Implementeret", format_date(implemented_at))
        columns[2].metric("Førperiode", before_period)
        columns = st.columns(2)
        columns[0].metric("Måleperiode", measurement_period)
        columns[1].metric(
            "Næste evaluering" if insufficient else "Evalueres",
            format_date(evaluation) if evaluation else "Ukendt",
        )
        _render_visible_change(item, implemented_change)
        measurement_complete = day_number >= total_days
        measurement_remaining = max(0, total_days - day_number)
        progress_text = (
            f"Dag {day_number} af {total_days} · Måleperioden er afsluttet"
            if measurement_complete else
            f"Dag {day_number} af {total_days} · "
            f"{measurement_remaining} "
            f"{'dag' if measurement_remaining == 1 else 'dage'} tilbage"
        )
        st.write("**Fremdrift i måleperioden**")
        st.progress(
            day_number / total_days,
            text=progress_text,
        )
        if insufficient:
            st.caption(
                f"Næste evaluering: {format_date(evaluation)} · "
                f"om {remaining} {'dag' if remaining == 1 else 'dage'}"
            )
            st.write("**Status:** Utilstrækkelige data")
            st.warning(
                "Der er endnu ikke data nok til en sikker evaluering. "
                f"Systemet forsøger igen den {format_date(evaluation)}."
            )
        else:
            st.write(
                f"**Status:** {_pulse_label(latest.get('pulse_status'))}"
            )
            st.write(
                "**Seneste observation:** "
                + latest.get(
                    "observation",
                    "Der er endnu ikke data nok til en statusopdatering.",
                )
            )
        with st.expander("Se udvikling"):
            _development(database, item, snapshots)
        with st.expander("Se datagrundlag"):
            approved_rows = database.get_approved_changes(
                experiment_id=item["id"]
            )
            _detail(
                item, None,
                evaluation_rows[0] if evaluation_rows else None,
                approved_rows[0] if approved_rows else None,
            )


def _render_visible_change(
    item: dict[str, Any], approved_change: dict[str, Any]
) -> None:
    """Show the exact measured change without requiring an expander."""
    st.markdown("#### Implementeret ændring")
    if (
        item.get("experiment_type") == "title_meta"
        and approved_change
    ):
        st.write("**Ny title**")
        st.code(
            approved_change.get("approved_title") or "Ikke registreret",
            language=None,
            wrap_lines=True,
        )
        st.write("**Ny metabeskrivelse**")
        st.code(
            approved_change.get("approved_meta") or "Ikke registreret",
            language=None,
            wrap_lines=True,
        )
        return
    st.write(
        item.get("change_description")
        or approved_change.get("reason")
        or "Ændringen er ikke beskrevet."
    )


def _development(
    database: Any, item: dict[str, Any],
    snapshots: list[dict[str, Any]],
) -> None:
    st.write(
        f"**Baseline:** {item.get('baseline_clicks') or 0} klik · "
        f"{float(item.get('baseline_ctr') or 0)*100:.1f}% CTR · "
        f"placering {float(item.get('baseline_position') or 0):.1f}"
    )
    if snapshots:
        latest = snapshots[-1]
        st.write(
            f"**Aktuelt:** {latest['clicks']} klik · "
            f"{latest['ctr']*100:.1f}% CTR · "
            f"placering {latest['average_position']:.1f}"
        )
        chart_rows = [{
            "Dato": format_date(row["observed_date"]),
            "Klik": row["clicks"], "CTR": row["ctr"] * 100,
            "Placering": row["average_position"],
            "Visninger": row["impressions"],
        } for row in snapshots]
        for metric in ("Klik", "CTR", "Placering", "Visninger"):
            st.write(f"**{metric}**")
            st.line_chart(chart_rows, x="Dato", y=metric)
        st.caption("For placering er et lavere tal en forbedring.")
    else:
        st.info("Ingen aktuelle målepunkter endnu.")
    st.write("**Tidslinje**")
    for observation in database.get_experiment_observations(item["id"]):
        st.write(
            f"{format_date(observation['observation_date'])} · "
            f"{observation['description']}"
        )


def _next_step(result: str | None) -> str:
    return {
        "strong_improvement": "Bevar ændringen og fortsæt overvågningen.",
        "improvement": "Bevar ændringen og følg udviklingen.",
        "neutral": "Fortsæt målingen eller overvej en ny variant senere.",
        "decline": "Overvej at justere eller tilbageføre ændringen.",
        "strong_decline": "Gennemgå ændringen med henblik på tilbageførsel.",
        "insufficient_data": "Afvent mere data. Ingen konklusion endnu.",
        "successful": "Bevar ændringen og følg udviklingen.",
        "partially_successful": "Bevar ændringen og følg udviklingen.",
        "no_measurable_effect": "Overvej en ny variant senere.",
        "negative_effect": "Overvej at justere ændringen.",
        "inconclusive": "Afvent mere data. Ingen konklusion endnu.",
    }.get(result, "Følg udviklingen.")


def _insufficient_requirements(evaluation: dict[str, Any]) -> None:
    """Explain the configured minimums without exposing internal statuses."""
    baseline_days = (
        date.fromisoformat(evaluation["comparison_end"])
        - date.fromisoformat(evaluation["comparison_start"])
    ).days + 1
    rules = EvaluationRules.from_environment()
    st.write("**Datagrundlag**")
    st.write(
        f"- Visninger: {evaluation['impressions_after']} af mindst "
        f"{rules.minimum_impressions} – "
        f"{_requirement_status(evaluation['impressions_after'], rules.minimum_impressions)}\n"
        f"- Klik: {evaluation['clicks_after']} af mindst "
        f"{rules.minimum_clicks} – "
        f"{_requirement_status(evaluation['clicks_after'], rules.minimum_clicks)}\n"
        f"- Datadage: {baseline_days} af mindst {rules.minimum_days} – "
        f"{_requirement_status(baseline_days, rules.minimum_days)}"
    )


def _requirement_status(actual: int | float, minimum: int | float) -> str:
    return "✅ Opfyldt" if actual >= minimum else "❌ Ikke opfyldt"


def _experiment_type(value: str) -> str:
    return EXPERIMENT_TYPE_LABELS.get(value, "Anden SEO-ændring")


def _goal_metric(value: str) -> str:
    return {
        "ctr": "Klikrate", "clicks": "Klik", "impressions": "Visninger",
        "average_position": "Gennemsnitlig placering",
    }.get(value, "Resultat")


def _pulse_label(value: str | None) -> str:
    return PULSE_LABELS.get(value or "Afventer data", value or "Under måling")


def _date_interval(start: Any, end: Any) -> str:
    if not start or not end:
        return "Ikke registreret"
    return f"{format_date(start)}–{format_date(end)}"


if __name__ == "__main__":
    main()
