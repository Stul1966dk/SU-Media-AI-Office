"""Safe, minimal OpenAI Responses API connection."""

import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any


EXPECTED_RESPONSE = "SU Media AI Office er forbundet med OpenAI."
TEST_INSTRUCTION = f"Svar kun med teksten:\n\n{EXPECTED_RESPONSE}"
DEFAULT_MODEL = "gpt-5.6-terra"


@dataclass(frozen=True)
class AIResponse:
    """Sanitized response metadata returned to analytical callers."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class AIServiceError(RuntimeError):
    """Sanitized OpenAI connection error safe for terminal output."""

    def __init__(
        self, category: str, *, original_type: str | None = None
    ) -> None:
        self.category = category
        self.original_type = original_type
        super().__init__(f"OpenAI-forbindelse fejlede ({category}).")


class AIService:
    """Test a connection without sending business data to OpenAI."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv(
            "OPENAI_API_KEY"
        )
        self.model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._client = client

    def test_connection(self) -> str:
        """Send the fixed connection instruction and print only its text."""
        if not self._api_key:
            raise AIServiceError("manglende API-nøgle")

        try:
            client = self._client or self._create_client()
            response = client.responses.create(
                model=self.model,
                input=TEST_INSTRUCTION,
            )
            text = str(response.output_text).strip()
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
                "input": prompt,
            }
            if tools:
                request["tools"] = tools
            response = client.responses.create(**request)
        except AIServiceError:
            raise
        except Exception as error:
            raise AIServiceError(
                self._error_category(error),
                original_type=type(error).__name__,
            ) from None
        usage = getattr(response, "usage", None)
        return AIResponse(
            text=str(response.output_text).strip(),
            model=str(getattr(response, "model", self.model)),
            prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            completion_tokens=int(
                getattr(usage, "output_tokens", 0) or 0
            ),
            latency_ms=round((perf_counter() - started) * 1000),
        )

    def _create_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError:
            raise AIServiceError("manglende OpenAI-pakke") from None
        return OpenAI(api_key=self._api_key)

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
