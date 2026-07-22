"""Tests for bounded, factual website discovery."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.website_discovery import WebsiteDiscoveryAgent
from core.database import Database
from core.website_registry import WebsiteRegistry
from integrations.website_scanner import MAX_SITEMAP_URLS, WebsiteScanner


class Response:
    def __init__(self, text: str, status: int = 200, url: str = "") -> None:
        self.text = text
        self.status_code = status
        self.url = url


class Session:
    def __init__(self, responses: dict[str, Response]) -> None:
        self.responses = responses
        self.headers: dict[str, str] = {}
        self.calls = []

    def get(self, url: str, **kwargs: object) -> Response:
        self.calls.append((url, kwargs))
        return self.responses[url]


class Scanner:
    def __init__(self, facts: dict[str, dict]) -> None:
        self.facts = facts

    def scan(self, domain: str) -> dict:
        value = self.facts[domain]
        if isinstance(value, Exception):
            raise value
        return dict(value)


class Orchestrator:
    def __init__(self) -> None:
        self.events = []

    def submit_event(self, event: object) -> int:
        self.events.append(event)
        return len(self.events)


def facts(domain: str, **changes: object) -> dict:
    value = WebsiteScanner._empty(domain)
    value.update({
        "http_status": 200, "https_enabled": True, "robots_status": "ok",
        "sitemap_status": "ok", "scan_status": "completed",
    })
    value.update(changes)
    return value


class WebsiteScannerTests(unittest.TestCase):
    def test_wordpress_theme_builder_robots_and_sitemap_are_documented(self) -> None:
        home = """
        <html><head><meta name="generator" content="WordPress 6">
        <link rel="canonical" href="https://example.dk/">
        <link href="/wp-content/themes/generatepress/style.css">
        <script src="/wp-content/plugins/elementor/app.js"></script>
        <script type="application/ld+json">{"@type":"WebSite"}</script>
        <title>Eksempel</title></head><body><h1>Forside</h1></body></html>
        """
        session = Session({
            "https://example.dk/": Response(home, url="https://example.dk/"),
            "https://example.dk/robots.txt": Response(
                "User-agent: *\nDisallow:\nSitemap: https://example.dk/map.xml",
                url="https://example.dk/robots.txt",
            ),
            "https://example.dk/map.xml": Response(
                "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
                "<url><loc>https://example.dk/a</loc></url></urlset>",
                url="https://example.dk/map.xml",
            ),
            "https://example.dk/wp-json/": Response(
                "{}", url="https://example.dk/wp-json/"
            ),
        })
        result = WebsiteScanner(session).scan("example.dk")
        self.assertEqual(("wordpress", "generatepress", "elementor"),
                         (result["cms"], result["theme"],
                          result["page_builder"]))
        self.assertEqual(("ok", "ok", 1),
                         (result["robots_status"], result["sitemap_status"],
                          result["sitemap_url_count"]))
        self.assertNotIn(home, str(result))
        self.assertTrue(all(call[1]["timeout"] == 10 for call in session.calls))

    def test_unknown_is_not_guessed_and_large_sitemap_is_capped(self) -> None:
        self.assertEqual(("unknown", 0), WebsiteScanner.detect_cms([]))
        self.assertEqual(("unknown", 0), WebsiteScanner.detect_theme([]))
        xml = "<urlset>" + "<url><loc>x</loc></url>" * 10_001 + "</urlset>"
        self.assertEqual(MAX_SITEMAP_URLS, WebsiteScanner._count_sitemap(xml)[0])


class WebsiteDiscoveryAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        for domain, status in (
            ("one.dk", "active"), ("bad.dk", "active"),
            ("old.dk", "phasing_out"),
        ):
            self.database.upsert_website({
                "website": domain, "display_name": domain, "active": True,
                "monetized": True, "priority": "high",
                "primary_income_source": "affiliate", "niche": "test",
                "domain_age": "1", "notes": "", "status": status,
            })
        self.orchestrator = Orchestrator()
        self.scanner = Scanner({
            "one.dk": facts("one.dk"),
            "bad.dk": RuntimeError("secret-token=abc"),
        })
        self.agent = WebsiteDiscoveryAgent(
            database=self.database, website_registry=WebsiteRegistry(self.database),
            website_intelligence=SimpleNamespace(),
            knowledge_engine=SimpleNamespace(),
            agent_orchestrator=self.orchestrator, scanner=self.scanner,
        )

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def test_failure_does_not_stop_batch_and_phasing_out_is_ignored(self) -> None:
        result = self.agent.scan_all_sites()
        self.assertEqual((2, 1), (result["websites_scanned"], result["failed"]))
        self.assertIsNone(self.agent.get_profile("old.dk"))
        self.assertNotIn("secret", self.agent.get_profile("bad.dk")["error_message"])

    def test_history_only_changes_and_issue_emits_event(self) -> None:
        self.agent.scan_site("one.dk")
        self.agent.scan_site("one.dk")
        self.assertEqual(1, len(self.agent.get_changes("one.dk")))
        self.scanner.facts["one.dk"] = facts(
            "one.dk", cms="wordpress", http_status=500
        )
        self.agent.scan_site("one.dk")
        self.assertEqual(2, len(self.agent.get_changes("one.dk")))
        self.assertTrue(any(
            event.event_type == "website_discovery_issue"
            for event in self.orchestrator.events
        ))
        self.assertEqual({"active_projects": 0, "open_tasks": 0},
                         self.database.get_executive_context()["counts"])


if __name__ == "__main__":
    unittest.main()
