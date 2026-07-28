"""Tests for Search Console cleanup and bulk website scope."""

import tempfile
import unittest
from pathlib import Path

from core.database import Database
from core.search_console_service import SearchConsoleService
from core.website_registry import WebsiteRegistry


class Connector:
    def __init__(self, properties):
        self.properties = properties

    def authenticate(self):
        return object()

    def list_properties(self):
        return self.properties


class SiteScopeCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "office.db")
        self.database.initialize()
        for website in ("keep.dk", "remove.dk", "inactive.dk"):
            self.database.upsert_website({
                "website": website,
                "display_name": website,
                "active": website != "inactive.dk",
                "monetized": True,
                "priority": "medium",
                "primary_income_source": "affiliate",
                "niche": "test",
                "domain_age": "1",
                "notes": "",
                "status": (
                    "inactive" if website == "inactive.dk" else "active"
                ),
            })

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_sync_deactivates_property_missing_from_google(self):
        for website in ("keep.dk", "remove.dk"):
            self.database.upsert_search_console_property(
                site_url=f"sc-domain:{website}",
                permission_level="siteOwner",
                website_id=website,
            )
        connector = Connector([{
            "site_url": "sc-domain:keep.dk",
            "permission_level": "siteOwner",
        }])

        SearchConsoleService(
            connector,
            self.database,
            WebsiteRegistry(self.database),
        ).synchronize()

        properties = {
            row["site_url"]: row
            for row in self.database.get_search_console_properties()
        }
        self.assertTrue(properties["sc-domain:keep.dk"]["active"])
        self.assertFalse(properties["sc-domain:remove.dk"]["active"])

    def test_bulk_scope_replaces_only_manageable_active_set(self):
        changed = self.database.set_active_website_ids({"keep.dk"})

        self.assertEqual(1, changed)
        self.assertEqual(["keep.dk"], self.database.get_active_website_ids())
        self.assertFalse(self.database.get_website("remove.dk")["active"])
        self.assertFalse(self.database.get_website("inactive.dk")["active"])


if __name__ == "__main__":
    unittest.main()
