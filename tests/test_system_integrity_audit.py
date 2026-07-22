"""Sprint 37 integrity audit and status-machine regression tests."""

import tempfile
import unittest
from pathlib import Path

from core.database import Database
from core.system_audit import SystemIntegrityAudit
from core.workflow_status import WORK_QUEUE_TRANSITIONS, validate_transition


class SystemIntegrityAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "audit.db")
        self.database.initialize()
        self.database.upsert_website({
            "website": "site.dk", "display_name": "site.dk",
            "active": True, "monetized": True, "priority": "high",
            "primary_income_source": "affiliate", "niche": "test",
            "domain_age": "1", "notes": "", "status": "active",
        })

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _queue_item(self) -> dict:
        self.database.replace_queued_work([{
            "website": "site.dk", "target_url": "https://site.dk/",
            "target_query": "test", "task_title": "Title og meta",
            "task_description": "Opdater title og meta.",
            "expected_effect": "Flere klik", "confidence": 80,
            "estimated_minutes": 30, "priority_score": 80,
            "experiment_type": "title_meta",
        }])
        return self.database.get_work_queue()[0]

    def test_illegal_status_transition_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Ulovlig statusovergang"):
            validate_transition(
                WORK_QUEUE_TRANSITIONS, "queued", "completed", "arbejdskø"
            )
        validate_transition(
            WORK_QUEUE_TRANSITIONS, "queued", "queued", "arbejdskø"
        )

    def test_audit_reports_approved_queue_item_without_change(self) -> None:
        item = self._queue_item()
        self.database.update_work_queue_item(
            item["id"], {"status": "awaiting_implementation"}
        )
        result = SystemIntegrityAudit(self.database).run()
        self.assertIn(
            "approved_task_without_change",
            {finding["code"] for finding in result["findings"]},
        )

    def test_safe_repair_downgrades_false_approval_without_deleting(self) -> None:
        item = self._queue_item()
        self.database.update_work_queue_item(
            item["id"], {"status": "awaiting_implementation"}
        )
        repaired = SystemIntegrityAudit(self.database).repair_safe()
        self.assertEqual(1, repaired["repaired_invalid_approvals"])
        self.assertEqual(
            "queued",
            self.database.get_work_queue_item(item["id"])["status"],
        )


if __name__ == "__main__":
    unittest.main()
