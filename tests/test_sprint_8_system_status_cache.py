"""Focused Sprint 8 tests for the persistent Claude health cache."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from core.ai_service import AIServiceError
from core.database import Database
from core.system_health import check_runtime_services


NOW = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)


class CountingAI:
    calls = 0

    def test_connection(self) -> str:
        type(self).calls += 1
        return "SU Media AI Office er forbundet med Claude."


class FailingAI:
    calls = 0

    def test_connection(self) -> str:
        type(self).calls += 1
        raise AIServiceError("godkendelse", original_type="AuthError")


class SecretFailureAI:
    def test_connection(self) -> str:
        raise RuntimeError(os.environ["ANTHROPIC_API_KEY"])


class Sprint8SystemStatusCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        playbook = self.root / "knowledge" / "company"
        playbook.mkdir(parents=True)
        (playbook / "company_playbook.md").write_text(
            "# Test", encoding="utf-8"
        )
        self.database = Database(self.root / "test.db")
        self.database.initialize()
        CountingAI.calls = 0
        FailingAI.calls = 0
        self.environment = patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "sk-test-secret",
                "ANTHROPIC_MODEL": "test-model",
            },
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.database.close()
        self.temp.cleanup()

    def check(self, factory=CountingAI, when=NOW, force=False) -> dict:
        return check_runtime_services(
            project_root=self.root,
            ai_service_factory=factory,
            database=self.database,
            force_openai=force,
            reference_time=when,
        )["openai"]

    def test_no_cache_executes_one_openai_call(self) -> None:
        result = self.check()
        self.assertEqual(1, CountingAI.calls)
        self.assertTrue(result["test_executed"])
        self.assertEqual(1, result["openai_test_calls_executed"])

    def test_valid_success_cache_avoids_call(self) -> None:
        first = self.check()
        second = self.check(when=NOW + timedelta(hours=2))
        self.assertEqual(1, CountingAI.calls)
        self.assertFalse(second["test_executed"])
        self.assertEqual(1, second["openai_test_calls_avoided"])
        self.assertEqual(first["last_test_at"], second["last_test_at"])

    def test_cache_older_than_24_hours_executes_new_call(self) -> None:
        self.check()
        self.check(when=NOW + timedelta(hours=24))
        self.assertEqual(2, CountingAI.calls)

    def test_changed_configuration_fingerprint_executes_new_call(self) -> None:
        self.check()
        os.environ["ANTHROPIC_MODEL"] = "changed-model"
        result = self.check(when=NOW + timedelta(minutes=1))
        self.assertEqual(2, CountingAI.calls)
        self.assertEqual(
            "Claude-konfigurationen er ændret", result["cache_reason"]
        )

    def test_force_system_check_executes_new_call(self) -> None:
        self.check()
        result = self.check(when=NOW + timedelta(minutes=1), force=True)
        self.assertEqual(2, CountingAI.calls)
        self.assertEqual("Tvungen systemtest", result["cache_reason"])

    def test_failed_test_is_reused_for_fifteen_minutes(self) -> None:
        failed = self.check(factory=FailingAI)
        cached = self.check(
            factory=FailingAI, when=NOW + timedelta(minutes=14)
        )
        retried = self.check(
            factory=FailingAI, when=NOW + timedelta(minutes=15)
        )
        self.assertFalse(failed["is_ok"])
        self.assertFalse(cached["test_executed"])
        self.assertTrue(retried["test_executed"])
        self.assertEqual(2, FailingAI.calls)

    def test_api_key_never_appears_in_cache_or_error(self) -> None:
        secret = os.environ["ANTHROPIC_API_KEY"]
        result = self.check(factory=SecretFailureAI)
        stored = self.database.get_openai_health_cache()
        serialized = json.dumps(stored, ensure_ascii=False)
        self.assertNotIn(secret, result["detail"])
        self.assertNotIn(secret, serialized)
        self.assertNotEqual(secret, stored["config_fingerprint"])


if __name__ == "__main__":
    unittest.main()
