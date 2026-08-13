"""Website briefing readiness based only on persisted facts."""

from typing import Any


def get_website_briefing_readiness(
    database: Any, website_id: str | None
) -> dict[str, Any]:
    if not website_id:
        return {
            "status": "Ikke klar", "required": {}, "recommended": {},
            "missing_required": ["aktivt website"],
        }
    source = database.get_website_intelligence_source(website_id) or {}
    metrics = database.get_search_console_daily_metrics(website_id=website_id)
    health = database.get_dashboard_system_health().get("openai", {})
    discovery = database.get_website_discovery_profile(website_id)
    analysis = database.get_latest_analysis(website_id=website_id)
    required = {
        "Website Registry": database.get_website(website_id) is not None,
        "Website Profile": database.get_website_profile_detail(website_id) is not None,
        "Mindst 14 Search Console-dage": len(metrics) >= 14,
        "Claude-forbindelse": bool(health.get("is_ok")),
    }
    recommended = {
        "Mindst 28 Search Console-dage": len(metrics) >= 28,
        "SEO Health": bool(source.get("seo_health")),
        "Partner Ads-historik": bool(
            source.get("partner_ads", {}).get("sales")
        ),
        "Website Discovery": discovery is not None,
        "Aktive projekter": bool(source.get("active_projects")),
        "Åbne opgaver": bool(source.get("active_tasks")),
        "Seneste AI-analyse": analysis is not None,
    }
    required_ready = all(required.values())
    status = (
        "Ikke klar" if not required_ready
        else "Klar" if all(recommended.values())
        else "Delvist klar"
    )
    return {
        "status": status, "required": required, "recommended": recommended,
        "missing_required": [
            label for label, available in required.items() if not available
        ],
        "search_console_days": len(metrics),
    }
