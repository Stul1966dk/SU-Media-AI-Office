"""Sprint 45.1 regression tests for the active-site scope on I dag."""

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"


def _load_page():
    spec = importlib.util.spec_from_file_location("daily_work_45_1", PAGE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ActiveSiteScopeTests(unittest.TestCase):
    def test_decisions_from_inactive_sites_are_hidden(self) -> None:
        page = _load_page()
        rows = [
            {"website_id": "active.dk", "title": "Aktiv"},
            {"website_id": "inactive.dk", "title": "Inaktiv"},
        ]

        result = page._filter_active_site_rows(
            rows, {"active.dk"}, website_field="website_id"
        )

        self.assertEqual(["Aktiv"], [item["title"] for item in result])

    def test_priority_tasks_from_inactive_sites_are_hidden(self) -> None:
        page = _load_page()
        rows = [
            {"website": "active.dk", "description": "Aktiv"},
            {"website": "inactive.dk", "description": "Inaktiv"},
        ]

        result = page._filter_active_site_rows(
            rows, {"active.dk"}, website_field="website"
        )

        self.assertEqual(["Aktiv"], [item["description"] for item in result])

    def test_today_filters_all_three_upstream_sources(self) -> None:
        source = PAGE.read_text(encoding="utf-8")

        self.assertIn("active_ids =", source)
        self.assertGreaterEqual(
            source.count("_filter_active_site_rows("), 4
        )
        self.assertIn('website_field="website_id"', source)
        self.assertIn('website_field="website"', source)


if __name__ == "__main__":
    unittest.main()
