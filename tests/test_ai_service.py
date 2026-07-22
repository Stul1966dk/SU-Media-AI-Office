"""Tests for the safe OpenAI connection."""

import io
import logging
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.ai_service import (
    AIService,
    AIServiceError,
    EXPECTED_RESPONSE,
    TEST_INSTRUCTION,
)


class AIServiceTestCase(unittest.TestCase):
    def test_missing_api_key_has_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                AIServiceError,
                "manglende API-nøgle",
            ):
                AIService().test_connection()

    def test_valid_key_uses_responses_api_and_prints_expected_text(self) -> None:
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text=EXPECTED_RESPONSE
        )
        output = io.StringIO()

        with redirect_stdout(output):
            result = AIService(
                client=client,
                api_key="test-secret-key",
                model="available-test-model",
            ).test_connection()

        self.assertEqual(result, EXPECTED_RESPONSE)
        self.assertEqual(output.getvalue().strip(), EXPECTED_RESPONSE)
        client.responses.create.assert_called_once_with(
            model="available-test-model",
            input=TEST_INSTRUCTION,
        )

    def test_key_is_not_printed_logged_or_in_sanitized_error(self) -> None:
        secret = "never-show-this-secret"
        client = Mock()
        client.responses.create.side_effect = RuntimeError(
            f"provider error containing {secret}"
        )
        output = io.StringIO()

        with self.assertLogs(level=logging.CRITICAL) as captured:
            logging.critical("unrelated")
            with redirect_stdout(output):
                with self.assertRaises(AIServiceError) as raised:
                    AIService(client=client, api_key=secret).test_connection()

        visible = output.getvalue() + str(raised.exception) + "".join(
            captured.output
        )
        self.assertNotIn(secret, visible)
        self.assertEqual(str(raised.exception), "OpenAI-forbindelse fejlede (API-fejl).")

    def test_no_business_data_is_sent(self) -> None:
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text=EXPECTED_RESPONSE
        )

        with redirect_stdout(io.StringIO()):
            AIService(client=client, api_key="test-key").test_connection()

        request = client.responses.create.call_args.kwargs
        self.assertEqual(set(request), {"model", "input"})
        self.assertEqual(request["input"], TEST_INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
