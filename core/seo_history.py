"""Deterministic SEO trend analysis based on Search Console history."""

from dataclasses import dataclass
from datetime import date

from .database import Database


PERIODS = ("7d", "28d", "90d")


@dataclass(frozen=True)
class SEOHealth:
    """One website's SEO health for a comparison period."""

    website: str
    period: str
    click_change_pct: float | None
    impression_change_pct: float | None
    ctr_change: float | None
    position_change: float | None
    trend: str
    score: float


class SEOHistory:
    """Object-oriented facade used by specialist agents."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def analyze_site(
        self,
        website: str,
        analysis_date: date | None = None,
    ) -> list[SEOHealth]:
        return analyze_site(self.database, website, analysis_date)

    def analyze_all_sites(
        self,
        analysis_date: date | None = None,
    ) -> list[SEOHealth]:
        return analyze_all_sites(self.database, analysis_date)


def analyze_site(
    database: Database,
    website: str,
    analysis_date: date | None = None,
) -> list[SEOHealth]:
    """Analyze and persist 7, 28, and 90-day SEO health for one website."""
    reference_date = analysis_date or date.today()
    click_changes = _by_period(
        database.get_click_change(website, reference_date)
    )
    impression_changes = _by_period(
        database.get_impression_change(website, reference_date)
    )
    ctr_changes = _by_period(
        database.get_ctr_change(website, reference_date)
    )
    position_changes = _by_period(
        database.get_position_change(website, reference_date)
    )
    results: list[SEOHealth] = []

    for period in PERIODS:
        click_change = click_changes[period]["change"]
        impression_change = impression_changes[period]["change"]
        ctr_change = ctr_changes[period]["change"]
        position_change = position_changes[period]["change"]
        score = _calculate_score(
            click_change,
            impression_change,
            ctr_change,
            position_change,
        )
        health = SEOHealth(
            website=website,
            period=period,
            click_change_pct=click_change,
            impression_change_pct=impression_change,
            ctr_change=ctr_change,
            position_change=position_change,
            trend=_trend_from_score(score),
            score=score,
        )
        database.upsert_seo_health(
            website_id=website,
            analysis_date=reference_date.isoformat(),
            period=period,
            score=health.score,
            trend=health.trend,
            click_change=health.click_change_pct,
            impression_change=health.impression_change_pct,
            ctr_change=health.ctr_change,
            position_change=health.position_change,
        )
        results.append(health)
    return results


def analyze_all_sites(
    database: Database,
    analysis_date: date | None = None,
) -> list[SEOHealth]:
    """Analyze every website that has stored Search Console metrics."""
    results: list[SEOHealth] = []
    for website in database.get_search_console_website_ids():
        results.extend(analyze_site(database, website, analysis_date))
    return results


def _by_period(
    changes: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {str(item["period"]): item for item in changes}


def _calculate_score(
    click_change: float | None,
    impression_change: float | None,
    ctr_change: float | None,
    position_change: float | None,
) -> float:
    """Return a bounded 0-100 score with 50 as the neutral baseline."""
    score = 50.0
    if click_change is not None:
        score += _clamp(click_change, -100, 100) * 0.35
    if impression_change is not None:
        score += _clamp(impression_change, -100, 100) * 0.20
    if ctr_change is not None:
        score += _clamp(ctr_change, -10, 10) * 2.0
    if position_change is not None:
        score -= _clamp(position_change, -10, 10) * 3.0
    return round(_clamp(score, 0, 100), 1)


def _trend_from_score(score: float) -> str:
    if score >= 70:
        return "growing"
    if score >= 45:
        return "stable"
    if score >= 25:
        return "declining"
    return "critical"


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))
