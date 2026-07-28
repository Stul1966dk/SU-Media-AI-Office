"""Sprint 25 website context and dashboard regression tests."""

import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.database import Database


ROOT = Path(__file__).resolve().parents[1]


class Sprint25DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("SU_MEDIA_DATABASE_PATH")
        self.database_path = Path(self.temp.name) / "dashboard.db"
        os.environ["SU_MEDIA_DATABASE_PATH"] = str(self.database_path)
        database = Database(self.database_path)
        database.initialize()
        database.upsert_website({
            "website": "active.example", "display_name": "Active",
            "active": True, "monetized": True, "priority": "high",
            "primary_income_source": "Partner Ads", "niche": "Test",
            "domain_age": "1", "notes": "", "status": "active",
        })
        database.upsert_website({
            "website": "archived.example", "display_name": "Archived",
            "active": True, "monetized": False, "priority": "low",
            "primary_income_source": "", "niche": "Test",
            "domain_age": "1", "notes": "", "status": "archived",
        })
        database.close()

    def tearDown(self) -> None:
        if self.previous is None:
            os.environ.pop("SU_MEDIA_DATABASE_PATH", None)
        else:
            os.environ["SU_MEDIA_DATABASE_PATH"] = self.previous
        self.temp.cleanup()

    def test_sidebar_selector_excludes_archived_websites(self) -> None:
        app = AppTest.from_file(
            str(
                ROOT / "dashboard" / "pages" / "19_Portefolje.py"
            ),
            default_timeout=20,
        ).run()
        self.assertFalse(app.exception)
        selector = next(
            item for item in app.sidebar.selectbox
            if item.label == "Aktivt website"
        )
        self.assertEqual(["active.example"], selector.options)

    def test_seo_view_does_not_import_without_button(self) -> None:
        app = AppTest.from_file(
            str(ROOT / "dashboard" / "pages" / "9_SEO.py")
        ).run()
        self.assertFalse(app.exception)
        self.assertTrue(any(
            button.label == "Hent Search Console-data"
            for button in app.button
        ))

    def test_projects_tasks_and_partner_ads_are_real_pages(self) -> None:
        for name in ("2_Projekter.py", "8_Opgaver.py", "10_Partner_Ads.py"):
            source = (ROOT / "dashboard" / "pages" / name).read_text("utf-8")
            self.assertNotIn("dashboard.components.placeholder", source)
            app = AppTest.from_file(
                str(ROOT / "dashboard" / "pages" / name)
            ).run()
            self.assertFalse(app.exception, name)


if __name__ == "__main__":
    unittest.main()
