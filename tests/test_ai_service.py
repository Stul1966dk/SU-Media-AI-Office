"""Tests for the safe Claude (Anthropic) connection."""

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
    MAX_OUTPUT_TOKENS,
    TEST_INSTRUCTION,
)


def _text_message(text: str) -> SimpleNamespace:
    """Build a minimal Claude message with a single text block."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        model="available-test-model",
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=3, output_tokens=5),
    )


class AIServiceTestCase(unittest.TestCase):
    def test_missing_api_key_has_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                AIServiceError,
                "manglende API-nøgle",
            ):
                AIService().test_connection()

    def test_valid_key_uses_messages_api_and_prints_expected_text(self) -> None:
        client = Mock()
        client.messages.create.return_value = _text_message(EXPECTED_RESPONSE)
        output = io.StringIO()

        with redirect_stdout(output):
            result = AIService(
                client=client,
                api_key="test-secret-key",
                model="available-test-model",
            ).test_connection()

        self.assertEqual(result, EXPECTED_RESPONSE)
        self.assertEqual(output.getvalue().strip(), EXPECTED_RESPONSE)
        client.messages.create.assert_called_once_with(
            model="available-test-model",
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": TEST_INSTRUCTION}],
        )

    def test_key_is_not_printed_logged_or_in_sanitized_error(self) -> None:
        secret = "never-show-this-secret"
        client = Mock()
        client.messages.create.side_effect = RuntimeError(
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
        self.assertEqual(str(raised.exception), "AI-forbindelse fejlede (API-fejl).")

    def test_no_business_data_is_sent(self) -> None:
        client = Mock()
        client.messages.create.return_value = _text_message(EXPECTED_RESPONSE)

        with redirect_stdout(io.StringIO()):
            AIService(client=client, api_key="test-key").test_connection()

        request = client.messages.create.call_args.kwargs
        self.assertEqual(set(request), {"model", "max_tokens", "messages"})
        self.assertEqual(
            request["messages"], [{"role": "user", "content": TEST_INSTRUCTION}]
        )

    def test_generate_response_translates_web_search_tool(self) -> None:
        client = Mock()
        client.messages.create.return_value = _text_message("{}")

        AIService(client=client, api_key="test-key").generate_response(
            "prompt", tools=[{"type": "web_search"}]
        )

        tools = client.messages.create.call_args.kwargs["tools"]
        self.assertEqual(tools[0]["type"], "web_search_20260209")
        self.assertEqual(tools[0]["name"], "web_search")

    def test_generate_response_flags_a_refusal(self) -> None:
        client = Mock()
        client.messages.create.return_value = SimpleNamespace(
            content=[], model="m", stop_reason="refusal",
            usage=SimpleNamespace(input_tokens=1, output_tokens=0),
        )

        with self.assertRaises(AIServiceError):
            AIService(client=client, api_key="test-key").generate_response(
                "prompt"
            )


if __name__ == "__main__":
    unittest.main()
