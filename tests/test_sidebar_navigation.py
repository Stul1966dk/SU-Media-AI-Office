"""Tests for grouped and durable sidebar navigation."""

import tempfile
import unittest
from pathlib import Path

from core.database import Database


ROOT = Path(__file__).resolve().parents[1]


class SidebarNavigationTests(unittest.TestCase):
    def test_group_state_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "test.db")
            database.initialize()
            database.set_navigation_group_state("seo", True)
            self.assertTrue(database.get_navigation_group_state("seo"))
            database.set_navigation_group_state("seo", False)
            self.assertFalse(database.get_navigation_group_state("seo"))
            self.assertIsNone(
                database.get_navigation_group_state("research")
            )
            database.close()

    def test_sidebar_contains_requested_groups_and_subpages(self) -> None:
        source = (
            ROOT / "dashboard" / "components" / "ui.py"
        ).read_text(encoding="utf-8")
        for label in (
            "Aktuel opgave", "Dashboard", "Executive Briefing", "Websites",
            "Research", "SEO", "AI Analyst", "Arbejde", "Indstillinger",
            "Kom godt i gang", "SEO-læring", "Integrationer",
        ):
            self.assertIn(label, source)
        self.assertIn("set_navigation_group_state", source)


if __name__ == "__main__":
    unittest.main()
