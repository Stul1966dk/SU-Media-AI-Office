"""Explicit runtime health checks with safe, actionable diagnostics."""

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from .ai_service import AIService, AIServiceError
from .knowledge_engine import KnowledgeEngine


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def check_runtime_services(
    *,
    project_root: Path = PROJECT_ROOT,
    ai_service_factory: Callable[[], AIService] = AIService,
) -> dict[str, dict[str, Any]]:
    """Check services used by Streamlit and preserve their error types."""
    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    load_dotenv(project_root / ".env", override=False)
    return {
        "knowledge_engine": _check_knowledge(project_root, checked_at),
        "openai": _check_openai(ai_service_factory, checked_at),
    }


def _check_knowledge(
    project_root: Path, checked_at: str
) -> dict[str, Any]:
    root = project_root / "knowledge"
    playbook = root / "company" / "company_playbook.md"
    try:
        if not playbook.is_file():
            raise FileNotFoundError(
                "knowledge/company/company_playbook.md mangler"
            )
        count = KnowledgeEngine(root).initialize()
        if isinstance(count, bool) and not count:
            raise RuntimeError("initialize() returnerede False")
        if not count:
            raise RuntimeError("Ingen dokumenter fundet")
        return _result(True, f"{count} dokumenter indlæst", checked_at)
    except Exception as error:
        return _result(
            False, f"{type(error).__name__}: {error}", checked_at,
            error_type=type(error).__name__,
        )


def _check_openai(
    ai_service_factory: Callable[[], AIService], checked_at: str
) -> dict[str, Any]:
    try:
        message = ai_service_factory().test_connection()
        return _result(True, message, checked_at)
    except AIServiceError as error:
        error_type = error.original_type or type(error).__name__
        return _result(
            False, f"{error_type}: {error.category}", checked_at,
            error_type=error_type,
        )
    except Exception as error:
        return _result(
            False, f"{type(error).__name__}: {error}", checked_at,
            error_type=type(error).__name__,
        )


def _result(
    is_ok: bool, detail: str, checked_at: str,
    *, error_type: str | None = None,
) -> dict[str, Any]:
    return {
        "is_ok": is_ok,
        "detail": detail,
        "checked_at": checked_at,
        "error_type": error_type,
    }
