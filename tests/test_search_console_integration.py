"""Tests for shared Search Console connection lifecycle management."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.database import Database
from integrations.search_console import SearchConsoleAuthenticationError
from integrations.search_console_integration import SearchConsoleIntegration


class SearchConsoleIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database = Database(self.root / "test.db")
        self.database.initialize()
        self.integration = SearchConsoleIntegration(self.root, self.database)

    def tearDown(self) -> None:
        self.database.close()
        self.temporary_directory.cleanup()

    def test_missing_token_is_reported_as_disconnected(self) -> None:
        status = self.integration.status()
        self.assertFalse(status["connected"])
        self.assertFalse(status["valid"])
        self.assertIsNone(status["account"])

    def test_connect_saves_account_and_marks_integration_healthy(self) -> None:
        connector = Mock()
        connector.start_oauth_login.return_value = Mock()
        with (
            patch.object(self.integration, "connector", return_value=connector),
            patch.object(
                self.integration, "_account_email",
                return_value="owner@example.com",
            ),
        ):
            state = self.integration.connect()
        self.assertEqual("owner@example.com", state["account"])
        self.assertEqual(
            "owner@example.com",
            self.database.get_integration_state("search_console")["account"],
        )
        self.assertTrue(
            self.database.get_dashboard_system_status()["search_console"]
        )

    def test_disconnect_removes_token_and_metadata(self) -> None:
        self.integration.token_path.write_text("token", encoding="utf-8")
        self.database.set_integration_state(
            "search_console", {"account": "owner@example.com"}
        )
        self.integration.disconnect()
        self.assertFalse(self.integration.token_path.exists())
        self.assertIsNone(
            self.database.get_integration_state("search_console")
        )
        self.assertFalse(
            self.database.get_dashboard_system_status()["search_console"]
        )

    def test_authentication_error_is_shared_with_status_ui(self) -> None:
        self.integration.token_path.write_text("token", encoding="utf-8")
        connector = Mock()
        connector.authenticate.side_effect = SearchConsoleAuthenticationError(
            "Tokenet kunne ikke fornyes."
        )
        with patch.object(
            self.integration, "connector", return_value=connector
        ):
            status = self.integration.status(validate=True)
        self.assertFalse(status["valid"])
        self.assertEqual(
            "Tokenet kunne ikke fornyes.",
            self.database.get_integration_state(
                "search_console"
            )["last_error"],
        )

    def test_recorded_auth_error_produces_a_warning(self) -> None:
        self.assertIsNone(self.integration.authentication_warning())
        self.integration.record_authentication_error(
            SearchConsoleAuthenticationError("Tokenet er udløbet.")
        )
        warning = self.integration.authentication_warning()
        self.assertIsNotNone(warning)
        self.assertIn("Forbind igen", warning)

    def test_clearing_the_error_removes_the_warning(self) -> None:
        self.integration.record_authentication_error(
            SearchConsoleAuthenticationError("Tokenet er udløbet.")
        )
        self.assertIsNotNone(self.integration.authentication_warning())

        self.integration.clear_authentication_error()

        self.assertIsNone(self.integration.authentication_warning())
        state = self.database.get_integration_state("search_console")
        self.assertIsNone(state["last_error"])
        self.assertNotIn("error_at", state)


if __name__ == "__main__":
    unittest.main()
