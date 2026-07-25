"""Tests for all-active-website integration connection checks."""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from integrations.plausible_integration import PlausibleIntegration
from integrations.search_console_integration import SearchConsoleIntegration


ACTIVE_WEBSITES = [
    {"website": "alpha.dk", "active": True, "status": "active"},
    {"website": "beta.dk", "active": True, "status": "active"},
    {"website": "old.dk", "active": False, "status": "inactive"},
]


class IntegrationConnectionCheckTests(unittest.TestCase):
    def test_plausible_checks_every_active_website_and_reports_failure(
        self,
    ) -> None:
        database = Mock()
        database.get_all_websites.return_value = ACTIVE_WEBSITES
        connector = Mock()
        connector.get_daily_visitors.side_effect = [12, RuntimeError("Ingen adgang")]
        result = PlausibleIntegration(
            database, connector=connector
        ).test_active_websites()
        self.assertEqual(2, result["tested"])
        self.assertEqual(1, result["failed"])
        self.assertEqual(["alpha.dk", "beta.dk"], [
            item["website"] for item in result["results"]
        ])
        self.assertFalse(result["results"][1]["ok"])

    def test_search_console_checks_property_for_every_active_website(
        self,
    ) -> None:
        database = Mock()
        database.get_all_websites.return_value = ACTIVE_WEBSITES
        integration = SearchConsoleIntegration(Path("."), database)
        connector = Mock()
        connector.list_properties.return_value = [
            {
                "site_url": "sc-domain:alpha.dk",
                "permission_level": "siteOwner",
            }
        ]
        with patch.object(
            integration, "connector", return_value=connector
        ):
            result = integration.test_active_websites()
        self.assertEqual(2, result["tested"])
        self.assertEqual(1, result["failed"])
        self.assertTrue(result["results"][0]["ok"])
        self.assertFalse(result["results"][1]["ok"])
        database.set_system_status.assert_called_once_with(
            "search_console", False
        )


if __name__ == "__main__":
    unittest.main()
