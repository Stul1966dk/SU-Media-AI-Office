"""Database-only Website Intelligence Agent."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from core.database import Database
from core.website_registry import WebsiteRegistry


@dataclass(frozen=True)
class WebsiteIntelligenceResult:
    """Result from building or refreshing one website profile."""

    website: str
    profile_action: str
    statistics_action: str
    history_action: str
    health_score: float


@dataclass(frozen=True)
class WebsiteIntelligenceBatchResult:
    """Aggregate result from one intelligence run."""

    websites_analyzed: int
    profiles_created: int
    profiles_updated: int
    profiles_unchanged: int
    history_changes: int


class WebsiteIntelligenceAgent:
    """Build unified website profiles from already persisted office data."""

    def __init__(
        self,
        database: Database,
        website_registry: WebsiteRegistry,
    ) -> None:
        if website_registry.database is not database:
            raise ValueError(
                "Website Intelligence og Website Registry skal dele database."
            )
        self.database = database
        self.website_registry = website_registry

    def analyze_all_sites(
        self,
        analysis_date: date | None = None,
    ) -> WebsiteIntelligenceBatchResult:
        """Build or refresh a profile for every registered website."""
        created = 0
        updated = 0
        unchanged = 0
        history_changes = 0
        websites = self.website_registry.get_all()
        for website in websites:
            result = self.analyze_site(
                website["website"],
                analysis_date=analysis_date,
            )
            if result.profile_action == "created":
                created += 1
            elif result.profile_action == "updated":
                updated += 1
            else:
                unchanged += 1
            if result.history_action != "unchanged":
                history_changes += 1
        return WebsiteIntelligenceBatchResult(
            websites_analyzed=len(websites),
            profiles_created=created,
            profiles_updated=updated,
            profiles_unchanged=unchanged,
            history_changes=history_changes,
        )

    def analyze_site(
        self,
        website_id: str,
        *,
        analysis_date: date | None = None,
    ) -> WebsiteIntelligenceResult:
        """Build and persist one unified profile from database inputs."""
        source = self.database.get_website_intelligence_source(website_id)
        if source is None:
            raise ValueError(f"Website findes ikke: {website_id}")
        analysis_day = analysis_date or date.today()
        website = source["website"]
        search = source["search_console"]
        seo = source["seo_health"]
        partner_ads = source["partner_ads"]
        cms, theme = self._detect_platform(website["notes"])
        health_score = self._calculate_health(source)
        strong_areas, weak_areas = self._identify_areas(source)
        recommendations = self._recommend(weak_areas)
        profile = {
            "website_id": website_id,
            "display_name": website["display_name"] or website_id,
            "status": website["status"],
            "cms": cms,
            "theme": theme,
            "monetization": (
                website["primary_income_source"]
                if website["monetized"]
                else "Ikke monetized"
            ),
            "niche": website["niche"] or "Ukendt",
            "website_health": health_score,
            "strong_areas": strong_areas,
            "weak_areas": weak_areas,
            "ai_recommendations": recommendations,
        }
        profile_action = self.database.upsert_website_profile(profile)
        statistics = {
            "website_id": website_id,
            "statistic_date": analysis_day.isoformat(),
            "search_clicks": int(search["clicks"]),
            "search_impressions": int(search["impressions"]),
            "search_ctr": float(search["ctr"]),
            "average_position": search["average_position"],
            "sales_count": partner_ads["sales_count"],
            "revenue": float(partner_ads["revenue"]),
            "commission": float(partner_ads["commission"]),
            "seo_score": seo["score"] if seo else None,
            "seo_trend": seo["trend"] if seo else None,
            "active_projects": len(source["active_projects"]),
            "active_tasks": len(source["active_tasks"]),
            "website_health": health_score,
        }
        statistics_action = self.database.upsert_website_statistics(statistics)
        categories = self._categories(website)
        self.database.replace_website_categories(website_id, categories)
        snapshot = {
            "profile": profile,
            "statistics": statistics,
            "categories": categories,
        }
        history_action = self.database.save_website_history(
            website_id,
            analysis_day.isoformat(),
            snapshot,
        )
        return WebsiteIntelligenceResult(
            website=website_id,
            profile_action=profile_action,
            statistics_action=statistics_action,
            history_action=history_action,
            health_score=health_score,
        )

    @staticmethod
    def _detect_platform(notes: str) -> tuple[str, str]:
        normalized = notes.casefold()
        cms = "WordPress" if "wordpress" in normalized else "Ukendt"
        theme_match = re.search(
            r"(?:theme|tema)\s*[:=]\s*([^,;.]+)",
            notes,
            flags=re.IGNORECASE,
        )
        theme = theme_match.group(1).strip() if theme_match else "Ukendt"
        return cms, theme

    @staticmethod
    def _calculate_health(source: dict[str, Any]) -> float:
        website = source["website"]
        seo = source["seo_health"]
        search = source["search_console"]
        partner_ads = source["partner_ads"]
        seo_score = float(seo["score"]) if seo else 50.0
        score = seo_score * 0.65
        if website["active"] and website["status"] == "active":
            score += 10
        if website["monetized"]:
            score += 10
        if partner_ads["commission"] > 0:
            score += 10
        if search["impressions"] > 0:
            score += 5
        return round(max(0.0, min(score, 100.0)), 1)

    @staticmethod
    def _identify_areas(
        source: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        website = source["website"]
        seo = source["seo_health"]
        search = source["search_console"]
        partner_ads = source["partner_ads"]
        strong: list[str] = []
        weak: list[str] = []
        if website["monetized"]:
            strong.append("Monetization er aktiv")
        else:
            weak.append("Website er ikke monetized")
        if partner_ads["commission"] > 0:
            strong.append("Partner Ads har dokumenteret provision")
        if search["impressions"] > 0:
            strong.append("Search Console har organisk synlighed")
        else:
            weak.append("Ingen gemt Search Console-synlighed")
        if seo:
            if seo["trend"] == "growing" or seo["score"] >= 70:
                strong.append("SEO Health viser vækst")
            if seo["trend"] in {"declining", "critical"} or seo["score"] < 40:
                weak.append("SEO Health viser dokumenteret tilbagegang")
            if (
                seo["click_change"] is not None
                and seo["click_change"] <= -15
            ):
                weak.append("Klik er faldet mindst 15 procent")
        else:
            weak.append("SEO Health mangler")
        if website["status"] != "active":
            weak.append(f"Website-status er {website['status']}")
        return strong, weak

    @staticmethod
    def _recommend(weak_areas: list[str]) -> list[str]:
        recommendations: list[str] = []
        rules = {
            "Website er ikke monetized": (
                "Vurdér en dokumenteret monetization-model."
            ),
            "Ingen gemt Search Console-synlighed": (
                "Kontrollér property-match og datagrundlag i Search Console."
            ),
            "SEO Health viser dokumenteret tilbagegang": (
                "Følg det aktive SEO Recovery-arbejde eller opret en analyse."
            ),
            "Klik er faldet mindst 15 procent": (
                "Identificér siderne med størst klikfald før ændringer."
            ),
            "SEO Health mangler": (
                "Opbyg tilstrækkelig Search Console-historik til SEO Health."
            ),
        }
        for weakness in weak_areas:
            if weakness in rules and rules[weakness] not in recommendations:
                recommendations.append(rules[weakness])
        return recommendations

    @staticmethod
    def _categories(website: dict[str, Any]) -> list[dict[str, Any]]:
        categories: list[dict[str, Any]] = []
        niche_parts = [
            part.strip()
            for part in re.split(r",|/|\band\b", website["niche"])
            if part.strip()
        ]
        for rank, category in enumerate(niche_parts, start=1):
            categories.append(
                {
                    "category": category,
                    "category_type": "niche",
                    "rank": rank,
                }
            )
        if website["primary_income_source"]:
            categories.append(
                {
                    "category": website["primary_income_source"],
                    "category_type": "monetization",
                    "rank": len(categories) + 1,
                }
            )
        return categories
