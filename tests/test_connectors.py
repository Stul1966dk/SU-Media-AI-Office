"""Tests for read-only connector selection, fallback and import."""

import tempfile
import unittest
from pathlib import Path

from connectors.connector_factory import ConnectorFactory
from connectors.wordpress_connector import WordPressConnector
from core.database import Database


class Response:
    def __init__(
        self, payload: object = None, *, text: str = "",
        status: int = 200, url: str = "",
    ) -> None:
        self.payload = payload
        self.text = text
        self.status_code = status
        self.url = url

    def json(self) -> object:
        return self.payload


class Session:
    def __init__(self, responses: dict[str, Response]) -> None:
        self.responses = responses
        self.headers = {}
        self.calls = []

    def get(self, url: str, **kwargs: object) -> Response:
        self.calls.append((url, kwargs))
        return self.responses[url]


class Orchestrator:
    def __init__(self) -> None:
        self.events = []

    def submit_event(self, event: object) -> int:
        self.events.append(event)
        return len(self.events)


def post(identifier: int, title: str = "Test") -> dict:
    return {
        "id": identifier, "title": {"rendered": title}, "slug": f"test-{identifier}",
        "link": f"https://wp.dk/test-{identifier}", "status": "publish",
        "date": "2026-01-01", "modified": "2026-01-02",
        "content": {"rendered": "<h2>Dansk overskrift</h2>"
                                "<p>Tre danske ord i et afsnit</p>"
                                "<a href='/intern'>I</a>"
                                "<a href='https://other.dk'>E</a>"},
        "excerpt": {"rendered": "<p>Kort</p>"},
        "_embedded": {
            "wp:term": [[{"taxonomy": "category", "name": "Nyheder"}],
                        [{"taxonomy": "post_tag", "name": "AI"}]],
            "wp:featuredmedia": [{"source_url": "https://wp.dk/image.jpg"}],
        },
    }


class ConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        for domain in ("wp.dk", "other.dk"):
            self.database.upsert_website({
                "website": domain, "display_name": domain, "active": True,
                "monetized": True, "priority": "high",
                "primary_income_source": "affiliate", "niche": "test",
                "domain_age": "1", "notes": "", "status": "active",
            })
        self._discovery("wp.dk", "wordpress")
        self._discovery("other.dk", "unknown")

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _discovery(self, website: str, cms: str) -> None:
        from integrations.website_scanner import WebsiteScanner
        profile = WebsiteScanner._empty(website)
        profile.update({
            "website_id": website, "cms": cms, "scan_status": "completed",
            "scanned_at": "2026-01-01T00:00:00+00:00",
        })
        self.database.save_website_discovery_profile(profile)

    def _rest_session(
        self, posts: list[dict], pages: list[dict] | None = None
    ) -> Session:
        root = Response({
            "name": "WP", "description": "Site", "language": "da_DK",
            "timezone_string": "Europe/Copenhagen",
        })
        return Session({
            "https://wp.dk/wp-json/": root,
            "https://wp.dk/wp-json/wp/v2/posts?per_page=100&_embed=1":
                Response(posts),
            "https://wp.dk/wp-json/wp/v2/pages?per_page=100&_embed=1":
                Response(pages or []),
            "https://wp.dk/wp-json/wp/v2/categories?per_page=100&_embed=1":
                Response([]),
            "https://wp.dk/wp-json/wp/v2/tags?per_page=100&_embed=1":
                Response([]),
            "https://wp.dk/wp-json/wp/v2/media?per_page=100&_embed=1":
                Response([]),
        })

    def test_factory_uses_documented_wordpress_only(self) -> None:
        factory = ConnectorFactory(self.database)
        self.assertEqual("WordPressConnector",
                         factory.suggested_connector("wp.dk"))
        self.assertIsNone(factory.create("other.dk"))

    def test_rest_api_normalizes_content_without_authentication(self) -> None:
        session = self._rest_session([post(1)])
        connector = WordPressConnector(
            website_id="wp.dk", database=self.database, session=session
        )
        self.assertTrue(connector.connect())
        item = connector.get_posts()[0]
        self.assertEqual((1, 1), (item["internal_link_count"],
                                 item["external_link_count"]))
        self.assertEqual(["Nyheder"], item["categories"])
        self.assertEqual(
            {"element": "h2", "text": "Dansk overskrift"},
            item["content_sections"][0],
        )
        self.assertIn("Tre danske ord", item["content_text"])
        self.assertTrue(all("auth" not in str(call).lower() for call in session.calls))
        self.assertTrue(all(call[1]["headers"]["Cookie"] == ""
                            for call in session.calls))

    def test_html_fallback_is_public_and_read_only(self) -> None:
        html = """
        <html lang="da"><head><title>WP Site</title>
        <meta name="generator" content="WordPress 6.8">
        <meta name="description" content="Beskrivelse"></head>
        <body><a href="/om">Om</a><img src="/a.jpg" alt="A"></body></html>
        """
        session = Session({
            "https://wp.dk/wp-json/": Response(status=404),
            "https://wp.dk/": Response(text=html, url="https://wp.dk/"),
        })
        connector = WordPressConnector(
            website_id="wp.dk", database=self.database, session=session
        )
        self.assertTrue(connector.connect())
        self.assertEqual("6.8",
                         connector.get_site_information()["wordpress_version"])
        self.assertEqual(1, len(connector.get_pages()))
        self.assertEqual("A", connector.get_media()[0]["alt_text"])

    def test_import_is_idempotent_and_large_change_emits_event(self) -> None:
        orchestrator = Orchestrator()
        connector = WordPressConnector(
            website_id="wp.dk", database=self.database,
            session=self._rest_session([], [post(i) for i in range(21)]),
            agent_orchestrator=orchestrator,
        )
        connector.connect()
        first = connector.import_content()
        second = connector.import_content()
        self.assertEqual((21, 0), (first["changed"], second["changed"]))
        self.assertEqual(21, len(self.database.get_content_by_type("wp.dk", "page")))
        stored = self.database.get_content_by_type("wp.dk", "page")[0]
        self.assertTrue(stored["content_sections"])
        self.assertIn("Tre danske ord", stored["content_text"])
        self.assertEqual(1, len(orchestrator.events))
        self.assertEqual("website_content_updated",
                         orchestrator.events[0].event_type)


if __name__ == "__main__":
    unittest.main()
