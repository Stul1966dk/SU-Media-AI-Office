"""Explicit runtime health checks with safe, actionable diagnostics."""

import hashlib
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from .ai_service import AIService, AIServiceError, DEFAULT_MODEL
from .knowledge_engine import KnowledgeEngine


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPENAI_SUCCESS_CACHE = timedelta(hours=24)
OPENAI_FAILURE_CACHE = timedelta(minutes=15)


def check_runtime_services(
    *,
    project_root: Path = PROJECT_ROOT,
    ai_service_factory: Callable[[], AIService] = AIService,
    database: Any | None = None,
    force_openai: bool = False,
    reference_time: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Check services used by Streamlit and preserve their error types."""
    now = reference_time or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    checked_at = now.isoformat(timespec="seconds")
    load_dotenv(project_root / ".env", override=False)
    return {
        "knowledge_engine": _check_knowledge(project_root, checked_at),
        "openai": _cached_openai_check(
            ai_service_factory, database, now, force_openai
        ),
    }


def _cached_openai_check(
    ai_service_factory: Callable[[], AIService],
    database: Any | None,
    now: datetime,
    force: bool,
) -> dict[str, Any]:
    fingerprint = _openai_fingerprint()
    cached = (
        database.get_openai_health_cache()
        if database is not None else None
    )
    reason = _openai_test_reason(cached, fingerprint, now, force)
    if reason is None and cached:
        return {
            "is_ok": bool(cached["is_ok"]),
            "detail": str(cached["detail"]),
            "checked_at": str(cached["last_attempt"]),
            "error_type": cached.get("error_type"),
            "test_executed": False,
            "cache_reason": "Seneste OpenAI-test er stadig gyldig",
            "last_test_at": cached["last_attempt"],
            "next_test_at": cached["next_test_at"],
            "openai_test_calls_executed": 0,
            "openai_test_calls_avoided": 1,
        }
    checked_at = now.isoformat(timespec="seconds")
    result = _check_openai(ai_service_factory, checked_at)
    next_test = now + (
        OPENAI_SUCCESS_CACHE if result["is_ok"] else OPENAI_FAILURE_CACHE
    )
    state = {
        "last_attempt": checked_at,
        "last_success": (
            checked_at if result["is_ok"]
            else (cached or {}).get("last_success")
        ),
        "is_ok": result["is_ok"],
        "detail": result["detail"],
        "error_type": result.get("error_type"),
        "next_test_at": next_test.isoformat(timespec="seconds"),
        "config_fingerprint": fingerprint,
    }
    if database is not None:
        database.set_openai_health_cache(state)
    return {
        **result,
        "test_executed": True,
        "cache_reason": reason,
        "last_test_at": checked_at,
        "next_test_at": state["next_test_at"],
        "openai_test_calls_executed": 1,
        "openai_test_calls_avoided": 0,
    }


def _openai_test_reason(
    cached: dict[str, Any] | None, fingerprint: str,
    now: datetime, force: bool,
) -> str | None:
    if force:
        return "Tvungen systemtest"
    if not cached:
        return "Ingen tidligere OpenAI-test"
    if cached.get("config_fingerprint") != fingerprint:
        return "OpenAI-konfigurationen er ændret"
    try:
        next_test = datetime.fromisoformat(str(cached["next_test_at"]))
        if next_test.tzinfo is None:
            next_test = next_test.astimezone()
    except (KeyError, TypeError, ValueError):
        return "Gemt OpenAI-cache er ugyldig"
    if now >= next_test:
        return "OpenAI-cachen er udløbet"
    return None


def _openai_fingerprint() -> str:
    material = "\0".join((
        os.getenv("OPENAI_API_KEY", ""),
        os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


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
            False, f"{type(error).__name__}: OpenAI-test fejlede", checked_at,
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
