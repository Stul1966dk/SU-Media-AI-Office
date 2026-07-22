"""Website discovery coordinator with change history and issue events."""

from datetime import datetime
from typing import Any

from core.agent_orchestrator import Event
from core.database import Database
from integrations.website_scanner import WebsiteScanner


IGNORED_STATUSES = {"phasing_out", "archived", "cancelled"}


class WebsiteDiscoveryAgent:
    """Persist documented public facts without changing remote websites."""

    def __init__(
        self, *, database: Database, website_registry: Any,
        website_intelligence: Any, knowledge_engine: Any,
        agent_orchestrator: Any, scanner: WebsiteScanner | None = None,
    ) -> None:
        self.database = database
        self.website_registry = website_registry
        self.website_intelligence = website_intelligence
        self.knowledge_engine = knowledge_engine
        self.agent_orchestrator = agent_orchestrator
        self.scanner = scanner or WebsiteScanner()

    def scan_site(self, website_id: str) -> dict[str, Any]:
        """Scan one eligible website, persist facts and emit justified issues."""
        website = self.website_registry.get(website_id)
        if website is None:
            raise ValueError(f"Website findes ikke: {website_id}")
        if website["status"] in IGNORED_STATUSES or not website["active"]:
            return {"website_id": website_id, "scan_status": "ignored"}
        scanned_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            facts = self.scanner.scan(website["website"])
        except Exception as error:
            facts = WebsiteScanner._empty(website["website"])
            facts["error_message"] = self._error_type(error)
        profile = {
            **facts, "website_id": website["website"], "scanned_at": scanned_at,
        }
        saved = self.database.save_website_discovery_profile(profile)
        self._emit_issues(website, profile, saved["previous"])
        return {**profile, "changed": saved["changed"]}

    def scan_all_sites(self) -> dict[str, Any]:
        """Scan all eligible sites while isolating per-site failures."""
        results = []
        for website in self.website_registry.get_all():
            if website["status"] in IGNORED_STATUSES or not website["active"]:
                continue
            results.append(self.scan_site(website["website"]))
        return {
            "websites_scanned": len(results),
            "completed": sum(x["scan_status"] == "completed" for x in results),
            "failed": sum(x["scan_status"] == "failed" for x in results),
            "results": results,
        }

    def get_profile(self, website_id: str) -> dict[str, Any] | None:
        return self.database.get_website_discovery_profile(website_id)

    def get_changes(self, website_id: str) -> list[dict[str, Any]]:
        return self.database.get_website_discovery_changes(website_id)

    def _emit_issues(
        self, website: dict[str, Any], profile: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> None:
        issues = []
        if profile["http_status"] >= 400:
            issues.append(f"HTTP-fejl {profile['http_status']}")
        if not profile["https_enabled"]:
            issues.append("HTTPS mangler")
        if profile["robots_status"] == "blocked_all":
            issues.append("robots.txt blokerer hele websitet")
        if website["monetized"] and profile["sitemap_status"] != "ok":
            issues.append("Sitemap mangler på monetized website")
        if previous and previous["cms"] != profile["cms"]:
            issues.append(f"CMS ændret fra {previous['cms']} til {profile['cms']}")
        for issue in issues:
            self.agent_orchestrator.submit_event(Event(
                event_type="website_discovery_issue",
                source="Website Discovery Agent",
                website=website["website"],
                title="Website Discovery-fund",
                description=issue,
                priority=80,
                data={"finding": issue},
            ))

    @staticmethod
    def _error_type(error: Exception) -> str:
        name = type(error).__name__.lower()
        for marker, label in (
            ("timeout", "timeout"), ("ssl", "tls_error"),
            ("connection", "connection_error"), ("redirect", "redirect_error"),
            ("value", "invalid_response"),
        ):
            if marker in name:
                return label
        return "scan_error"
