"""Sprint 40.1 tests for the read-only Plausible Stats connection."""

import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests

from connectors.plausible_connector import (
    PlausibleConnector, PlausibleConnectorError,
)


class PlausibleConnectorTests(unittest.TestCase):
    def test_daily_visitors_uses_stats_query(self) -> None:
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {
            "results": [{"dimensions": ["2026-07-22"], "metrics": [42]}],
            "meta": {},
        }
        session.post.return_value = response
        connector = PlausibleConnector(api_token="secret", session=session)

        self.assertEqual(
            42, connector.get_daily_visitors("baalfad.dk", date(2026, 7, 22))
        )
        call = session.post.call_args
        self.assertEqual("https://plausible.io/api/v2/query", call.args[0])
        self.assertEqual({
            "site_id": "baalfad.dk", "metrics": ["visitors"],
            "date_range": ["2026-07-22", "2026-07-22"],
            "dimensions": ["time:day"],
        }, call.kwargs["json"])
        self.assertEqual(
            "Bearer secret", call.kwargs["headers"]["Authorization"]
        )

    def test_connection_uses_selected_site_and_yesterday(self) -> None:
        connector = PlausibleConnector(api_token="secret", site_id="site.dk")
        connector.get_daily_visitors = Mock(return_value=7)
        with patch("connectors.plausible_connector.date") as mocked_date:
            mocked_date.today.return_value = date(2026, 7, 23)
            self.assertTrue(connector.test_connection())
        connector.get_daily_visitors.assert_called_once_with(
            "site.dk", date(2026, 7, 22)
        )

    def test_zero_visitors_and_env_key(self) -> None:
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"results": []}
        session.post.return_value = response
        with patch.dict("os.environ", {"PLAUSIBLE_API_KEY": "from-env"}):
            connector = PlausibleConnector(session=session)
        self.assertEqual(0, connector.get_daily_visitors("site.dk", "2026-07-22"))
        self.assertEqual("from-env", connector.api_token)

    def test_wrong_or_missing_token_has_safe_message(self) -> None:
        with self.assertRaisesRegex(PlausibleConnectorError, "mangler"):
            PlausibleConnector(api_token="").get_daily_visitors(
                "site.dk", "2026-07-22"
            )
        session = Mock()
        session.post.return_value = Mock(status_code=401)
        with self.assertRaisesRegex(PlausibleConnectorError, "afviste"):
            PlausibleConnector(
                api_token="wrong", session=session
            ).get_daily_visitors("site.dk", "2026-07-22")

    def test_network_error_is_sanitized(self) -> None:
        session = Mock()
        session.post.side_effect = requests.ConnectionError("secret detail")
        with self.assertRaisesRegex(PlausibleConnectorError, "kunne ikke") as caught:
            PlausibleConnector(
                api_token="secret", session=session
            ).get_daily_visitors("site.dk", "2026-07-22")
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
