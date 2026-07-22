"""Tests for user-triggered Search Console dashboard import."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from core.search_console_service import (
    SearchConsoleDataSyncResult,
    SearchConsoleDimensionSyncResult,
    SearchConsoleSyncResult,
)
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "dashboard" / "pages" / "9_SEO.py"
SPEC = importlib.util.spec_from_file_location("seo_dashboard_page", PAGE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class FakeService:
    def synchronize(self) -> SearchConsoleSyncResult:
        return SearchConsoleSyncResult(
            connection_ok=True, total=3, matched=2, unmatched=1,
            properties=[],
        )

    def sync_all_properties(
        self, days: int = 35, website_ids: list[str] | None = None,
    ) -> SearchConsoleDataSyncResult:
        return SearchConsoleDataSyncResult(
            properties_processed=2, properties_failed=1,
            rows_created=20, rows_updated=10,
            start_date="2026-06-14", end_date="2026-07-18",
            errors=[{"site_url": "x", "error_type": "TestError"}],
        )

    def sync_dimensions(
        self, website_ids: list[str] | None = None,
    ) -> SearchConsoleDimensionSyncResult:
        return SearchConsoleDimensionSyncResult(
            properties_processed=2, properties_failed=0, page_rows=10,
            query_rows=20, page_query_rows=30, rows_created=60,
            rows_updated=0, errors=[],
        )


class SearchConsoleDashboardTests(unittest.TestCase):
    def test_import_result_reports_websites_days_errors_and_progress(self) -> None:
        progress = []
        result = MODULE.run_search_console_import(
            FakeService(), days=35,
            progress=lambda value, text: progress.append((value, text)),
        )
        self.assertEqual(1, result["websites_imported"])
        self.assertEqual(30, result["website_days_imported"])
        self.assertEqual(1, result["properties_failed"])
        self.assertEqual(10, result["page_rows"])
        self.assertEqual(20, result["query_rows"])
        self.assertEqual(30, result["page_query_rows"])
        self.assertEqual(100, progress[-1][0])

    def test_dashboard_has_import_button_and_explained_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("SU_MEDIA_DATABASE_PATH")
            os.environ["SU_MEDIA_DATABASE_PATH"] = str(
                Path(temporary) / "dashboard.db"
            )
            try:
                app = AppTest.from_file(str(PAGE), default_timeout=20).run()
            finally:
                if previous is None:
                    os.environ.pop("SU_MEDIA_DATABASE_PATH", None)
                else:
                    os.environ["SU_MEDIA_DATABASE_PATH"] = previous
        self.assertFalse(app.exception)
        self.assertTrue(any(
            button.label == "Hent Search Console-data"
            for button in app.button
        ))
        self.assertTrue(app.info)


if __name__ == "__main__":
    unittest.main()
