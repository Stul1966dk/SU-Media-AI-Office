"""Database-backed operational feature inventory."""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def build_feature_status(database: Any, project_root: Path) -> list[dict[str, str]]:
    """Combine implementation facts with live configuration and stored data."""
    load_dotenv(project_root / ".env")
    websites = database.get_all_websites()
    search = database.get_search_console_summary()
    health = database.get_dashboard_system_health()
    discovery = database.get_website_discovery_summary()
    content = database.get_recently_updated(limit=1)
    analyses = database.get_analysis_history(limit=1)
    briefing = database.get_latest_executive_briefing()
    sales = database.get_recent_sales(limit=1)
    seo = database.get_seo_health_history()
    projects = database.get_projects()
    tasks = database.get_task_records_for_project()
    events = database.get_recent_events(limit=1)
    runs = database.get_feature_runs()

    def service(name: str) -> dict[str, Any]:
        return health.get(name, {})

    def row(
        function: str, status: str, source: str, start: str,
        latest: str = "", limitation: str = "", next_step: str = "",
    ) -> dict[str, str]:
        return {
            "Funktion": function, "Status": status, "Datakilde": source,
            "Startmetode": start, "Seneste vellykkede kørsel": latest or "Ukendt",
            "Kendt begrænsning": limitation or "Ingen kendt",
            "Næste nødvendige trin": next_step or "Ingen",
        }

    partner_configured = bool(
        os.getenv("PARTNER_ADS_BASE_URL") and os.getenv("PARTNER_ADS_KEY")
    )
    telegram_configured = bool(
        os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")
    )
    openai = service("openai")
    return [
        row("Website Registry", "Klar til brug" if websites else "Mangler data",
            "Lokal registry/database", "Website Registry",
            next_step="Registrér websites" if not websites else ""),
        row("Partner Ads import",
            "Klar til brug" if partner_configured else "Mangler data",
            "Partner Ads XML", "Knappen på Partner Ads",
            (runs.get("partner_ads_import") or {}).get("completed_at")
            or (sales[0].get("created_at", "") if sales else ""),
            next_step="Konfigurér Partner Ads i .env" if not partner_configured else ""),
        row("Partner Ads automatisk overvågning", "Klar til test",
            "Partner Ads XML", "python src/main.py",
            limitation="Kører kun mens monitorprocessen er aktiv"),
        row("Telegram", "Klar til brug" if telegram_configured else "Mangler data",
            "Telegram Bot API", "Ved nye Partner Ads-salg",
            next_step="Konfigurér bot-token og chat-id" if not telegram_configured else ""),
        row("Search Console forbindelse",
            "Klar til brug" if search.get("connection_ok") else "Mangler data",
            "Google Search Console", "Hent Search Console-data på SEO",
            search.get("latest_sync") or "", next_step="Kør forbindelsen" if not search.get("connection_ok") else ""),
        row("Search Console dagstal",
            "Klar til brug" if search.get("stored_metrics") else "Mangler data",
            "Database, dagstal pr. website", "Hent Search Console-data på SEO",
            search.get("latest_sync") or ""),
        row("Search Console top sider", "Ikke implementeret",
            "Kræver page-dimension", "Ingen",
            limitation="Page-dimensionen importeres ikke"),
        row("Search Console top søgeord", "Ikke implementeret",
            "Kræver query-dimension", "Ingen",
            limitation="Query-dimensionen importeres ikke"),
        row("SEO History", "Klar til brug" if seo else "Mangler data",
            "Gemte Search Console-dagstal", "SEO Manager", seo[0].get("date", "") if seo else ""),
        row("Website Discovery", "Klar til brug" if websites else "Mangler data",
            "Offentlige website-signaler", "Website Discovery",
            discovery.get("latest_scan") or ""),
        row("Content Explorer", "Klar til brug" if discovery.get("wordpress") else "Mangler data",
            "Offentlig WordPress REST/HTML", "Content Explorer",
            content[0].get("updated_at", "") if content else "",
            next_step="Kør WordPress discovery" if not discovery.get("wordpress") else ""),
        row("AI Analyst", "Klar til brug" if analyses else "Klar til test",
            "Websiteprofil og gemte driftsdata", "Kør analyse",
            analyses[0].get("created_at", "") if analyses else ""),
        row("Executive Briefing", "Klar til brug" if briefing else "Klar til test",
            "Gemte analyser og driftsdata", "Generér briefing",
            (briefing or {}).get("created_at", "")),
        row("Project Manager", "Klar til brug", "Lokal database",
            "Via godkendte anbefalinger", projects[0].get("created_at", "") if projects else ""),
        row("Task Engine", "Klar til brug", "Lokal database",
            "Via Project Manager", tasks[0].get("created_at", "") if tasks else ""),
        row("Agent Orchestrator", "Klar til brug" if events else "Klar til test",
            "Lokal eventkø", "python src/main.py",
            events[0].get("created_at", "") if events else ""),
        row("Claude", "Klar til brug" if openai.get("is_ok") else "Fejl",
            "Claude API", "Ved AI-analyse/briefing",
            openai.get("checked_at", ""), limitation=openai.get("detail", "")),
        row("Automation Engine", "Ikke implementeret", "Ingen", "Ingen"),
        row("Supabase", "Ikke implementeret", "Ingen", "Ingen"),
    ]
