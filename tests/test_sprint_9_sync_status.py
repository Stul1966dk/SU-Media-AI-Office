"""Focused tests for the persisted Sprint 9 synchronization overview."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.sync_status import load_sync_status


ROOT = Path(__file__).resolve().parents[1]


class SyncStatusTestCase(unittest.TestCase):
    def database(self, steps=None, *, openai_ok=True):
        database = Mock()
        database.get_last_data_refresh_result.return_value = (
            {"started_at": "2026-07-25T10:00:00+02:00",
             "completed_at": "2026-07-25T10:01:00+02:00",
             "steps": steps or []}
            if steps is not None else None
        )
        database.get_feature_runs.return_value = {}
        database.get_dashboard_system_health.return_value = (
            {"openai": {
                "is_ok": openai_ok, "checked_at": "2026-07-25T10:01:00+02:00",
                "detail": "OK" if openai_ok else "Forbindelsen fejlede",
                "error_type": None if openai_ok else "ConnectionError",
            }} if steps is not None else {}
        )
        database.get_openai_health_cache.return_value = (
            {"is_ok": openai_ok, "last_attempt": "2026-07-25T10:01:00+02:00",
             "last_success": "2026-07-25T10:01:00+02:00" if openai_ok else None,
             "next_test_at": "2026-07-26T10:01:00+02:00"}
            if steps is not None else None
        )
        return database

    @staticmethod
    def complete_steps():
        return [
            {"step": "Partner Ads", "status": "completed"},
            {"step": "Search Console-dagstal", "status": "completed"},
            {"step": "Search Console-sider og søgeord", "status": "completed"},
            {"step": "Plausible", "status": "completed"},
            {"step": "SEO History", "status": "completed"},
            {"step": "Website Intelligence", "status": "completed"},
            {"step": "SEO-eksperimentovervågning", "status": "completed"},
            {"step": "Prioriteringsscore", "status": "completed"},
        ]

    def test_overall_green_without_errors(self):
        model = load_sync_status(self.database(self.complete_steps()))
        self.assertEqual("Alle integrationer fungerer", model["overall_status"])

    def test_partial_error_gives_warning(self):
        steps = self.complete_steps()
        steps[1].update({
            "properties_failed": 1,
            "property_results": [{"property": "bad.dk", "status": "error"}],
        })
        model = load_sync_status(self.database(steps))
        self.assertEqual(
            "Synkronisering gennemført med advarsler",
            model["overall_status"],
        )
        self.assertEqual("Gennemført med advarsler", model["items"][1]["status"])

    def test_overall_failure_is_failed(self):
        steps = self.complete_steps()
        steps[3] = {
            "step": "Plausible", "status": "error",
            "error_message": "Tjenesten svarede ikke",
        }
        model = load_sync_status(self.database(steps))
        self.assertEqual(
            "En eller flere integrationer fejler", model["overall_status"]
        )

    def test_no_data_is_not_run(self):
        model = load_sync_status(self.database())
        self.assertEqual(
            "Ingen synkronisering er kørt endnu", model["overall_status"]
        )
        self.assertTrue(all(
            item["status"] == "Ikke kørt endnu" for item in model["items"]
        ))

    def test_search_console_and_plausible_keep_details(self):
        steps = self.complete_steps()
        steps[1]["property_results"] = [{
            "property": "sc-domain:alpha.dk", "status": "completed",
            "start_date": "2026-07-20", "end_date": "2026-07-24",
        }]
        steps[3]["website_results"] = [{
            "website_id": "alpha.dk", "status": "completed",
            "start_date": "2026-07-20", "end_date": "2026-07-24",
        }]
        model = load_sync_status(self.database(steps))
        self.assertEqual(
            "sc-domain:alpha.dk", model["items"][1]["details"][0]["property"]
        )
        self.assertEqual(
            "alpha.dk", model["items"][3]["details"][0]["website_id"]
        )

    def test_page_does_not_validate_or_call_apis_on_load(self):
        source = (ROOT / "dashboard/pages/18_Integrationer.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("status(validate=False)", source)
        self.assertNotIn("status(validate=True)", source)
        # Network-capable methods remain guarded by explicit button branches.
        self.assertLess(
            source.index('if st.button(\n        "Test alle websites i Plausible"'),
            source.index("integration.test_active_websites()"),
        )

    def test_sensitive_values_are_removed(self):
        secret = "sk-supersecret123456"
        steps = self.complete_steps()
        steps[3].update({
            "status": "error", "api_key": secret,
            "error_message": f"Bearer {secret}",
            "website_results": [{
                "website_id": "alpha.dk", "status": "error",
                "token": secret, "error": secret,
            }],
        })
        model = load_sync_status(self.database(steps))
        rendered = repr(model)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("api_key", rendered)
        self.assertNotIn("'token'", rendered)


if __name__ == "__main__":
    unittest.main()
