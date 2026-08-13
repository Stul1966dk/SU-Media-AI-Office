"""Safe, minimal Anthropic (Claude) Messages API connection."""

import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any


EXPECTED_RESPONSE = "SU Media AI Office er forbundet med Claude."
TEST_INSTRUCTION = f"Svar kun med teksten:\n\n{EXPECTED_RESPONSE}"
DEFAULT_MODEL = "claude-opus-5"
MAX_OUTPUT_TOKENS = 8192
WEB_SEARCH_TOOL_TYPE = "web_search_20260209"


@dataclass(frozen=True)
class AIResponse:
    """Sanitized response metadata returned to analytical callers."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class AIServiceError(RuntimeError):
    """Sanitized Claude connection error safe for terminal output."""

    def __init__(
        self, category: str, *, original_type: str | None = None
    ) -> None:
        self.category = category
        self.original_type = original_type
        super().__init__(f"AI-forbindelse fejlede ({category}).")


class AIService:
    """Test a connection without sending business data to Claude."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv(
            "ANTHROPIC_API_KEY"
        )
        self.model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self._client = client

    def test_connection(self) -> str:
        """Send the fixed connection instruction and print only its text."""
        if not self._api_key:
            raise AIServiceError("manglende API-nøgle")

        try:
            client = self._client or self._create_client()
            response = client.messages.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                messages=[{"role": "user", "content": TEST_INSTRUCTION}],
            )
            text = self._extract_text(response)
        except AIServiceError:
            raise
        except Exception as error:
            raise AIServiceError(
                self._error_category(error),
                original_type=type(error).__name__,
            ) from None

        if text != EXPECTED_RESPONSE:
            raise AIServiceError("uventet svar")

        print(text)
        return text

    def generate_response(
        self, prompt: str, *, tools: list[dict[str, Any]] | None = None
    ) -> AIResponse:
        """Return one text response and non-sensitive usage metadata."""
        if not self._api_key:
            raise AIServiceError("manglende API-nøgle")
        started = perf_counter()
        try:
            client = self._client or self._create_client()
            request: dict[str, Any] = {
                "model": self.model,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            }
            translated_tools = self._translate_tools(tools)
            if translated_tools:
                request["tools"] = translated_tools
            response = client.messages.create(**request)
        except AIServiceError:
            raise
        except Exception as error:
            raise AIServiceError(
                self._error_category(error),
                original_type=type(error).__name__,
            ) from None
        if getattr(response, "stop_reason", None) == "refusal":
            raise AIServiceError("afvist af sikkerhedsfilter")
        usage = getattr(response, "usage", None)
        return AIResponse(
            text=self._extract_text(response),
            model=str(getattr(response, "model", self.model)),
            prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            completion_tokens=int(
                getattr(usage, "output_tokens", 0) or 0
            ),
            latency_ms=round((perf_counter() - started) * 1000),
        )

    @staticmethod
    def _translate_tools(
        tools: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        """Map the caller's generic tool hints to Claude server tools."""
        if not tools:
            return None
        translated: list[dict[str, Any]] = []
        for tool in tools:
            if isinstance(tool, dict) and tool.get("type") == "web_search":
                translated.append(
                    {"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search"}
                )
            else:
                translated.append(tool)
        return translated

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Join the text blocks of a Claude message, ignoring the rest."""
        blocks = getattr(response, "content", None) or []
        parts = [
            str(getattr(block, "text", ""))
            for block in blocks
            if getattr(block, "type", None) == "text"
        ]
        return "".join(parts).strip()

    def _create_client(self) -> Any:
        try:
            from anthropic import Anthropic
        except ImportError:
            raise AIServiceError("manglende Anthropic-pakke") from None
        return Anthropic(api_key=self._api_key)

    @staticmethod
    def _error_category(error: Exception) -> str:
        name = type(error).__name__.lower()
        categories = (
            ("authentication", "godkendelse"),
            ("permission", "adgang"),
            ("ratelimit", "rate limit"),
            ("timeout", "timeout"),
            ("connection", "netværk"),
            ("badrequest", "ugyldig forespørgsel"),
            ("notfound", "model ikke tilgængelig"),
        )
        return next(
            (label for marker, label in categories if marker in name),
            "API-fejl",
        )
