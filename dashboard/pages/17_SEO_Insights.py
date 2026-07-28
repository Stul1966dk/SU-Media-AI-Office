"""Read-only overview for SEO experiment insights."""

import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.formatting import format_date, format_status
from dashboard.components.help_panel import render_help_panel
from dashboard.components.ui import load_styles, render_next_step, render_sidebar


def _result_totals(evaluations: list[dict]) -> tuple[int, int, float]:
    """Return wins, losses and mean CTR change in percentage points."""
    won = {"strong_improvement", "improvement"}
    lost = {"strong_decline", "decline"}
    ctr_changes = [
        float(item["ctr_percentage_point_change"])
        for item in evaluations
        if item.get("ctr_percentage_point_change") is not None
    ]
    return (
        sum(item.get("result_status") in won for item in evaluations),
        sum(item.get("result_status") in lost for item in evaluations),
        sum(ctr_changes) / len(ctr_changes) if ctr_changes else 0.0,
    )


def _format_ctr_change(value: float) -> str:
    return f"{value:+.2f}".replace(".", ",") + " procentpoint"


def _latest_evaluation_rows(evaluations: list[dict]) -> list[dict[str, str]]:
    """Prepare at most ten evaluations, newest first, for presentation."""
    latest = sorted(
        evaluations,
        key=lambda item: item.get("evaluated_at") or "",
        reverse=True,
    )[:10]
    return [
        {
            "Website": str(item.get("website_id") or ""),
            "URL": str(item.get("target_url") or ""),
            "Resultat": format_status(item.get("result_status")),
            "CTR-ændring": _format_ctr_change(
                float(item.get("ctr_percentage_point_change") or 0)
            ),
            "Evalueringsdato": format_date(item.get("evaluated_at")),
        }
        for item in latest
    ]


def _learning_totals(
    evaluations: list[dict], experiments: list[dict]
) -> tuple[float, float | None, float | None, int]:
    """Calculate deterministic learning metrics from persisted results."""
    won_statuses = {"strong_improvement", "improvement"}
    lost_statuses = {"strong_decline", "decline"}
    wins = [
        item for item in evaluations
        if item.get("result_status") in won_statuses
    ]
    losses = sum(
        item.get("result_status") in lost_statuses for item in evaluations
    )
    decided = len(wins) + losses
    won_changes = [
        float(item["ctr_percentage_point_change"])
        for item in wins
        if item.get("ctr_percentage_point_change") is not None
    ]
    all_changes = [
        float(item["ctr_percentage_point_change"])
        for item in evaluations
        if item.get("ctr_percentage_point_change") is not None
    ]
    awaiting_statuses = {
        "implemented", "running", "waiting_for_data",
        "ready_for_evaluation", "evaluating",
    }
    awaiting = sum(
        bool(item.get("started_at"))
        and item.get("status") in awaiting_statuses
        for item in experiments
    )
    return (
        len(wins) / decided * 100 if decided else 0.0,
        sum(won_changes) / len(won_changes) if won_changes else None,
        max(all_changes) if all_changes else None,
        awaiting,
    )


def _format_optional_ctr_change(value: float | None) -> str:
    return _format_ctr_change(value) if value is not None else "Ingen data endnu"


def _summary_sentences(
    evaluation_count: int, won: int, lost: int, won_share: float,
    won_average: float | None, largest_improvement: float | None,
    awaiting: int,
) -> list[str]:
    """Build a short factual summary from the displayed KPI values."""
    if not evaluation_count:
        return [
            "Der er endnu ingen afsluttede SEO-eksperimenter.",
            "Der er derfor ingen målte CTR-resultater endnu.",
            f"{awaiting} eksperimenter afventer evaluering.",
        ]
    sentences = [
        f"Der findes {evaluation_count} registrerede SEO-evalueringer.",
    ]
    if won + lost:
        sentences.append(
            f"{str(f'{won_share:.1f}').replace('.', ',')} % af de vundne og "
            "tabte eksperimenter er vundet."
        )
    else:
        sentences.append(
            "Ingen evalueringer er endnu klassificeret som vundne eller tabte."
        )
    if won_average is not None:
        sentences.append(
            "Vundne eksperimenter har i gennemsnit forbedret CTR med "
            f"{_format_ctr_change(won_average)}."
        )
    if largest_improvement is not None:
        sentences.append(
            "Den største registrerede CTR-forbedring er "
            f"{_format_ctr_change(largest_improvement)}."
        )
    sentences.append(f"{awaiting} eksperimenter afventer evaluering.")
    return sentences[:5]


def _result_distribution(
    evaluations: list[dict],
) -> list[tuple[str, int, float]]:
    """Group persisted evaluation classifications for the status cards."""
    groups = (
        ("Forbedring", {"strong_improvement", "improvement"}),
        ("Neutral", {"neutral"}),
        ("Forværring", {"strong_decline", "decline"}),
        ("Utilstrækkelige data", {"insufficient_data"}),
    )
    total = len(evaluations)
    return [
        (
            label,
            sum(item.get("result_status") in statuses for item in evaluations),
            (
                sum(
                    item.get("result_status") in statuses
                    for item in evaluations
                ) / total * 100
                if total else 0.0
            ),
        )
        for label, statuses in groups
    ]


def _website_performance(evaluations: list[dict]) -> list[dict[str, str | int]]:
    """Group final evaluation outcomes by website and sort best first."""
    won_statuses = {"strong_improvement", "improvement"}
    lost_statuses = {"strong_decline", "decline"}
    final_statuses = won_statuses | lost_statuses | {"neutral"}
    grouped: dict[str, dict[str, int | float]] = {}
    for item in evaluations:
        if item.get("result_status") not in final_statuses:
            continue
        website = str(item.get("website_id") or "")
        if not website:
            continue
        row = grouped.setdefault(
            website, {"completed": 0, "won": 0, "lost": 0, "win_rate": 0.0}
        )
        row["completed"] += 1
        row["won"] += item.get("result_status") in won_statuses
        row["lost"] += item.get("result_status") in lost_statuses
    for row in grouped.values():
        decided = int(row["won"]) + int(row["lost"])
        row["win_rate"] = int(row["won"]) / decided * 100 if decided else 0.0
    ordered = sorted(
        grouped.items(),
        key=lambda item: (
            -float(item[1]["win_rate"]),
            -int(item[1]["completed"]),
            item[0],
        ),
    )
    return [
        {
            "Website": website,
            "Antal afsluttede eksperimenter": int(values["completed"]),
            "Vundne": int(values["won"]),
            "Tabte": int(values["lost"]),
            "Vinderprocent (%)": str(
                f'{float(values["win_rate"]):.1f}'
            ).replace(".", ","),
        }
        for website, values in ordered
    ]


def _recommended_action(
    evaluation_count: int, awaiting: int, active_experiments: int
) -> str:
    """Return one recommendation from the existing experiment state."""
    if not evaluation_count and awaiting:
        return (
            "Der er endnu ingen afsluttede eksperimenter. "
            "Afvent de første evalueringer."
        )
    if awaiting:
        return f"{awaiting} eksperimenter afventer evaluering."
    if active_experiments:
        return "Alle aktive eksperimenter er evalueret."
    return "Ingen aktive eksperimenter. Opret et nyt SEO-eksperiment."


def main() -> None:
    """Point old bookmarks to the unified result and learning surface."""
    st.set_page_config(
        page_title="SEO Insights", page_icon="insights", layout="wide"
    )
    load_styles(PROJECT_ROOT / "dashboard" / "assets" / "styles.css")
    render_sidebar()
    st.title("SEO Insights")
    render_help_panel(
        purpose="Hjælp ældre bogmærker videre til det samlede resultatoverblik.",
        requirements="Ingen.",
        actions="Åbn Resultater for målinger, konklusioner og læring.",
        limitations="Denne ældre side viser ikke længere et separat overblik.",
    )
    st.info(
        "SEO Insights er nu samlet under Resultater, så du ikke skal lede "
        "efter samme information på flere sider."
    )
    render_next_step(
        text=(
            "Fortsæt til Resultater for at se aktive målinger, afsluttede "
            "konklusioner og dokumenteret læring samlet."
        ),
        path="pages/13_Eksperimenter.py",
        label="Åbn Resultater",
    )


if __name__ == "__main__":
    main()
