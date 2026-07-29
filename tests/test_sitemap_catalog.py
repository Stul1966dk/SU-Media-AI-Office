"""Tests for the per-website sitemap catalog."""

import unittest

from core.sitemap_catalog import SitemapCatalog


class Response:
    def __init__(self, text: str, *, error: bool = False) -> None:
        self.content = text.encode("utf-8")
        self.error = error

    def raise_for_status(self) -> None:
        if self.error:
            import requests
            raise requests.HTTPError("Ikke fundet")
        return None


class Session:
    def __init__(self, responses):
        self.responses = responses
        self.headers = {}

    def get(self, url, **_kwargs):
        value = self.responses.get(url)
        return (
            value if isinstance(value, Response)
            else Response(value or "", error=value is None)
        )


class Database:
    def __init__(self):
        self.states = {}

    def get_integration_state(self, key):
        return self.states.get(key)

    def set_integration_state(self, key, value):
        self.states[key] = value


class SitemapCatalogTests(unittest.TestCase):
    def test_follows_index_and_persists_page_and_post_urls(self) -> None:
        index = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap><loc>https://site.dk/post-sitemap.xml</loc></sitemap>
        <sitemap><loc>https://site.dk/page-sitemap.xml</loc></sitemap>
        </sitemapindex>"""
        posts = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://site.dk/artikel/</loc><lastmod>2026-01-01</lastmod></url>
        </urlset>"""
        pages = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://site.dk/om/</loc></url>
        </urlset>"""
        database = Database()
        result = SitemapCatalog(database, session=Session({
            "https://site.dk/sitemap_index.xml": index,
            "https://site.dk/post-sitemap.xml": posts,
            "https://site.dk/page-sitemap.xml": pages,
        })).sync("site.dk", "https://site.dk/sitemap_index.xml")

        self.assertEqual(2, result["url_count"])
        self.assertEqual(3, result["sitemaps_read"])
        self.assertEqual(
            {"post", "page"},
            {item["content_type"] for item in result["urls"]},
        )
        self.assertEqual(
            result, database.get_integration_state("sitemap:site.dk")
        )

    def test_rejects_sitemap_on_another_domain(self) -> None:
        with self.assertRaisesRegex(ValueError, "valgte website"):
            SitemapCatalog(Database(), session=Session({})).sync(
                "site.dk", "https://other.dk/sitemap.xml"
            )

    def test_wordpress_tag_sitemap_is_not_classified_as_post(self) -> None:
        self.assertEqual(
            "tag",
            SitemapCatalog._content_type(
                "https://site.dk/post_tag-sitemap.xml"
            ),
        )

    def test_auto_sync_uses_standard_index_without_manual_input(self) -> None:
        database = Database()
        session = Session({
            "https://site.dk/sitemap_index.xml": (
                "<urlset><url><loc>https://site.dk/side/</loc></url></urlset>"
            ),
        })

        result = SitemapCatalog(database, session=session).auto_sync("site.dk")

        self.assertEqual("found", result["status"])
        self.assertEqual(
            "https://site.dk/sitemap_index.xml", result["sitemap_url"]
        )

    def test_auto_sync_saves_not_found_state(self) -> None:
        database = Database()

        result = SitemapCatalog(
            database, session=Session({})
        ).auto_sync("site.dk")

        self.assertEqual("not_found", result["status"])
        self.assertEqual(2, len(result["attempted_urls"]))


if __name__ == "__main__":
    unittest.main()
