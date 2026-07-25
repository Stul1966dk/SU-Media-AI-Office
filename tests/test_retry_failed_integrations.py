"""Focused tests for targeted retries of failed external integrations."""

import unittest
from unittest.mock import Mock

from core.integration_retry import FailedIntegrationRetryService
from core.search_console_service import SearchConsoleDataSyncResult


class RetryFailedIntegrationsTestCase(unittest.TestCase):
    def database(self, steps):
        database = Mock()
        database.get_last_data_refresh_result.return_value = {
            "started_at": "2026-07-25T10:00:00+02:00",
            "completed_at": "2026-07-25T10:05:00+02:00",
            "steps": steps,
            "status": "warning",
            "completed_steps": 1,
            "warning_steps": 1,
            "failed_steps": 0,
            "skipped_steps": 0,
        }
        return database

    @staticmethod
    def daily_result():
        return SearchConsoleDataSyncResult(
            properties_processed=1,
            properties_failed=0,
            rows_created=0,
            rows_updated=3,
            start_date="2026-07-20",
            end_date="2026-07-25",
            earliest_fetched_date="2026-07-20",
            latest_fetched_date="2026-07-25",
            import_mode="incremental",
            errors=[],
            property_results=[{
                "site_url": "sc-domain:failed.dk",
                "website_id": "failed.dk",
                "status": "completed",
                "rows_created": 0,
                "rows_updated": 3,
            }],
        )

    def service(self, database, *, search=None, plausible=None):
        search = search or Mock()
        search.sync_all_properties.return_value = self.daily_result()
        plausible = plausible or Mock()
        plausible.import_active_websites.return_value = {
            "websites_attempted": 1,
            "websites_processed": 1,
            "websites_updated": 1,
            "websites_failed": 0,
            "rows_created": 0,
            "rows_updated": 2,
            "errors": [],
            "website_results": [{
                "website_id": "failed.dk", "status": "completed",
            }],
            "overall_status": "completed",
        }
        return FailedIntegrationRetryService(
            database, search_console=search, plausible=plausible,
            partner_refresh=Mock(),
        ), search, plausible

    def test_only_failed_search_console_property_is_retried(self):
        database = self.database([{
            "step": "Search Console-dagstal",
            "status": "warning",
            "errors": [
                {"site_url": "sc-domain:failed.dk"},
            ],
            "property_results": [{
                "site_url": "sc-domain:ok.dk", "status": "completed",
            }],
        }])
        service, search, plausible = self.service(database)
        service.retry()
        search.sync_all_properties.assert_called_once_with(
            days=35,
            property_urls=["sc-domain:failed.dk"],
            force_full_refresh=False,
        )
        plausible.import_active_websites.assert_not_called()

    def test_only_failed_plausible_website_is_retried(self):
        database = self.database([{
            "step": "Plausible",
            "status": "warning",
            "website_results": [
                {"website_id": "ok.dk", "status": "completed"},
                {"website_id": "failed.dk", "status": "failed"},
            ],
            "errors": [{"website": "failed.dk"}],
        }])
        service, search, plausible = self.service(database)
        service.retry()
        plausible.import_active_websites.assert_called_once_with(
            website_ids=["failed.dk"], force_full_refresh=False
        )
        search.sync_all_properties.assert_not_called()

    def test_successful_websites_are_not_retried(self):
        database = self.database([{
            "step": "Plausible",
            "status": "warning",
            "website_results": [
                {"website_id": "one.dk", "status": "completed"},
                {"website_id": "two.dk", "status": "completed"},
                {"website_id": "bad.dk", "status": "failed"},
            ],
        }])
        service, _search, plausible = self.service(database)
        service.retry()
        requested = plausible.import_active_websites.call_args.kwargs[
            "website_ids"
        ]
        self.assertEqual(["bad.dk"], requested)

    def test_no_concrete_errors_performs_no_retry(self):
        database = self.database([{
            "step": "Partner Ads", "status": "error",
            "error_message": "Import fejlede",
        }])
        partner = Mock()
        service = FailedIntegrationRetryService(
            database, search_console=Mock(), plausible=Mock(),
            partner_refresh=partner,
        )
        result = service.retry()
        self.assertEqual("skipped", result["status"])
        self.assertEqual(
            "Ingen konkrete fejl kan genkøres automatisk", result["message"]
        )
        partner.assert_not_called()
        database.save_data_refresh_result.assert_not_called()

    def test_persisted_status_is_updated_after_success(self):
        database = self.database([{
            "step": "Search Console-dagstal",
            "status": "warning",
            "errors": [{"site_url": "sc-domain:failed.dk"}],
        }])
        service, _search, _plausible = self.service(database)
        service.retry()
        saved = database.save_data_refresh_result.call_args.args[0]
        self.assertEqual("success", saved["steps"][0]["status"])
        self.assertEqual(0, saved["failed_steps"])
        database.save_integration_retry_result.assert_called_once()

    def test_sensitive_values_are_never_persisted_or_returned(self):
        secret = "sk-never-store-this-value"
        database = self.database([{
            "step": "Plausible",
            "status": "warning",
            "errors": [{"website": "failed.dk"}],
        }])
        plausible = Mock()
        plausible.import_active_websites.side_effect = RuntimeError(secret)
        service, _search, _plausible = self.service(
            database, plausible=plausible
        )
        result = service.retry()
        persisted = repr(database.mock_calls)
        self.assertNotIn(secret, repr(result))
        self.assertNotIn(secret, persisted)
        self.assertEqual(
            "Integrationen kunne ikke genkøres.",
            result["integrations"][0]["error_message"],
        )


if __name__ == "__main__":
    unittest.main()
