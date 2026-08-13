"""Tests for detailed, non-silent dashboard health diagnostics."""

import tempfile
import unittest
from pathlib import Path

from core.ai_service import AIServiceError
from core.database import Database
from core.system_health import check_runtime_services


class WorkingAI:
    def test_connection(self) -> str:
        return "SU Media AI Office er forbundet med Claude."


class FailingAI:
    def test_connection(self) -> str:
        raise AIServiceError("timeout", original_type="APITimeoutError")


class SystemHealthTests(unittest.TestCase):
    def _knowledge_root(self, root: Path) -> None:
        path = root / "knowledge" / "company"
        path.mkdir(parents=True)
        (path / "company_playbook.md").write_text(
            "# Company Playbook", encoding="utf-8"
        )

    def test_working_services_include_detail_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._knowledge_root(root)
            result = check_runtime_services(
                project_root=root, ai_service_factory=WorkingAI
            )
        self.assertTrue(result["knowledge_engine"]["is_ok"])
        self.assertTrue(result["openai"]["is_ok"])
        self.assertTrue(result["openai"]["checked_at"])

    def test_original_error_type_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._knowledge_root(root)
            result = check_runtime_services(
                project_root=root, ai_service_factory=FailingAI
            )
        self.assertEqual(
            "APITimeoutError: timeout", result["openai"]["detail"]
        )

    def test_missing_playbook_is_explicit_and_persistence_is_structured(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = check_runtime_services(
                project_root=root, ai_service_factory=WorkingAI
            )
            self.assertIn(
                "FileNotFoundError", result["knowledge_engine"]["detail"]
            )
            database = Database(root / "test.db")
            database.initialize()
            database.set_system_health(
                "knowledge_engine", result["knowledge_engine"]
            )
            stored = database.get_dashboard_system_health()
            database.close()
        self.assertEqual(
            "FileNotFoundError",
            stored["knowledge_engine"]["error_type"],
        )


if __name__ == "__main__":
    unittest.main()
