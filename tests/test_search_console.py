"""Tests for Search Console authentication, import, and comparisons."""

import io
import logging
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from core.database import Database
from core.search_console_service import SearchConsoleService
from core.website_registry import WebsiteRegistry
from integrations.search_console import (
    SearchConsoleAuthenticationError,
    SearchConsoleConnector,
)


class FakeConnector:
    """Deterministic Search Console connector used by service tests."""

    def __init__(
        self,
        properties: list[dict[str, str]],
        metrics: dict[str, list[dict[str, object]]],
        failing_site: str | None = None,
    ) -> None:
        self.properties = properties
        self.metrics = metrics
        self.failing_site = failing_site
        self.authenticate_calls = 0
        self.metric_calls: list[str] = []

    def authenticate(self) -> object:
        self.authenticate_calls += 1
        return object()

    def list_properties(self) -> list[dict[str, str]]:
        return self.properties

    def get_search_analytics(
        self,
        site_url: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, object]]:
        self.metric_calls.append(site_url)
        if site_url == self.failing_site:
            raise RuntimeError("secret-token-must-not-be-logged")
        return self.metrics.get(site_url, [])


def metric(
    metric_date: date,
    clicks: int,
    impressions: int = 100,
    position: float = 5.0,
) -> dict[str, object]:
    return {
        "date": metric_date.isoformat(),
        "clicks": clicks,
        "impressions": impressions,
        "ctr": clicks / impressions if impressions else 0.0,
        "position": position,
    }


class SearchConsoleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(
            Path(self.temporary_directory.name) / "office.sqlite3"
        )
        self.database.initialize()
        for website in ("alpha.dk", "beta.dk"):
            self.database.upsert_website(
                {
                    "website": website,
                    "display_name": website,
                    "active": True,
                    "monetized": True,
                    "priority": "medium",
                    "primary_income_source": "affiliate",
                    "niche": "test",
                    "domain_age": "1",
                    "notes": "",
                    "status": "active",
                }
            )
        self.registry = WebsiteRegistry(self.database)

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def service(
        self,
        connector: FakeConnector,
        logger: logging.Logger | None = None,
    ) -> SearchConsoleService:
        return SearchConsoleService(
            connector=connector,
            database=self.database,
            website_registry=self.registry,
            logger=logger,
        )

    def test_existing_oauth_token_is_reused(self) -> None:
        token_path = Path(self.temporary_directory.name) / "token.json"
        token_path.write_text("{}", encoding="utf-8")
        connector = SearchConsoleConnector(
            Path(self.temporary_directory.name) / "credentials.json",
            token_path,
        )
        credentials = Mock(valid=True, expired=False, expiry=None)
        with patch(
            "integrations.search_console."
            "Credentials.from_authorized_user_file",
            return_value=credentials,
        ) as load_token:
            result = connector.authenticate()
        self.assertIs(result, credentials)
        load_token.assert_called_once()

    def test_missing_token_has_clear_error(self) -> None:
        connector = SearchConsoleConnector(
            Path(self.temporary_directory.name) / "credentials.json",
            Path(self.temporary_directory.name) / "missing-token.json",
        )
        with self.assertRaisesRegex(
            SearchConsoleAuthenticationError,
            "token.json blev ikke fundet",
        ):
            connector.authenticate()

    def test_connector_queries_daily_search_analytics_for_one_property(
        self,
    ) -> None:
        connector = SearchConsoleConnector(
            Path(self.temporary_directory.name) / "credentials.json",
            Path(self.temporary_directory.name) / "token.json",
        )
        connector.credentials = Mock()
        request = Mock()
        request.execute.return_value = {
            "rows": [
                {
                    "keys": ["2026-07-16"],
                    "clicks": 5,
                    "impressions": 100,
                    "ctr": 0.05,
                    "position": 4.5,
                }
            ]
        }
        service = Mock()
        service.searchanalytics.return_value.query.return_value = request
        with patch(
            "integrations.search_console.build",
            return_value=service,
        ):
            rows = connector.get_search_analytics(
                "sc-domain:alpha.dk",
                "2026-07-01",
                "2026-07-16",
            )
        service.searchanalytics.return_value.query.assert_called_once_with(
            siteUrl="sc-domain:alpha.dk",
            body={
                "startDate": "2026-07-01",
                "endDate": "2026-07-16",
                "dimensions": ["date"],
                "rowLimit": 25000,
            },
        )
        self.assertEqual(rows[0]["date"], "2026-07-16")
        self.assertEqual(rows[0]["clicks"], 5)

    def test_one_property_is_fetched_and_stored(self) -> None:
        site_url = "sc-domain:alpha.dk"
        connector = FakeConnector(
            [{"site_url": site_url, "permission_level": "siteOwner"}],
            {site_url: [metric(date.today(), 4)]},
        )
        service = self.service(connector)
        service.synchronize()
        result = service.sync_property(site_url, "alpha.dk")
        self.assertEqual(result["rows_created"], 1)
        self.assertEqual(connector.metric_calls, [site_url])
        self.assertEqual(
            len(self.database.get_search_console_daily_metrics("alpha.dk")),
            1,
        )

    def test_all_matched_properties_are_processed(self) -> None:
        sites = ["sc-domain:alpha.dk", "sc-domain:beta.dk"]
        connector = FakeConnector(
            [
                {"site_url": site, "permission_level": "siteOwner"}
                for site in sites
            ],
            {site: [metric(date.today(), 1)] for site in sites},
        )
        service = self.service(connector)
        service.synchronize()
        result = service.sync_all_properties()
        self.assertEqual(result.properties_processed, 2)
        self.assertEqual(connector.metric_calls, sites)

    def test_reimport_updates_without_duplicates(self) -> None:
        site_url = "sc-domain:alpha.dk"
        connector = FakeConnector(
            [{"site_url": site_url, "permission_level": "siteOwner"}],
            {site_url: [metric(date.today(), 2)]},
        )
        service = self.service(connector)
        service.synchronize()
        first = service.sync_property(site_url, "alpha.dk")
        connector.metrics[site_url] = [metric(date.today(), 9)]
        second = service.sync_property(site_url, "alpha.dk")
        rows = self.database.get_search_console_daily_metrics("alpha.dk")
        self.assertEqual(first["rows_created"], 1)
        self.assertEqual(second["rows_updated"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["clicks"], 9)

    def test_seven_day_comparison_is_calculated_correctly(self) -> None:
        reference_date = date(2026, 7, 17)
        for offset in range(1, 15):
            is_current = offset <= 7
            self.database.upsert_search_console_daily_metric(
                website_id="alpha.dk",
                site_url="sc-domain:alpha.dk",
                metric_date=(reference_date - timedelta(days=offset)).isoformat(),
                clicks=20 if is_current else 10,
                impressions=200 if is_current else 200,
                ctr=0.1 if is_current else 0.05,
                average_position=4.0 if is_current else 6.0,
            )
        comparison = self.database.get_search_console_comparisons(
            reference_date
        )[0]
        self.assertEqual(comparison["current_clicks"], 140)
        self.assertEqual(comparison["previous_clicks"], 70)
        self.assertAlmostEqual(comparison["click_change_percent"], 100.0)
        self.assertAlmostEqual(comparison["ctr_change_points"], 0.05)
        self.assertAlmostEqual(comparison["position_difference"], -2.0)

    def test_one_property_failure_does_not_stop_the_rest_or_log_secret(
        self,
    ) -> None:
        failed = "sc-domain:alpha.dk"
        successful = "sc-domain:beta.dk"
        connector = FakeConnector(
            [
                {"site_url": failed, "permission_level": "siteOwner"},
                {"site_url": successful, "permission_level": "siteOwner"},
            ],
            {successful: [metric(date.today(), 3)]},
            failing_site=failed,
        )
        stream = io.StringIO()
        logger = logging.getLogger(f"search-console-test-{id(self)}")
        logger.handlers = [logging.StreamHandler(stream)]
        logger.propagate = False
        service = self.service(connector, logger)
        service.synchronize()
        result = service.sync_all_properties()
        self.assertEqual(result.properties_failed, 1)
        self.assertEqual(result.properties_processed, 2)
        self.assertIn(failed, stream.getvalue())
        self.assertNotIn("secret-token-must-not-be-logged", stream.getvalue())
        self.assertEqual(
            len(self.database.get_search_console_daily_metrics("beta.dk")),
            1,
        )


if __name__ == "__main__":
    unittest.main()
