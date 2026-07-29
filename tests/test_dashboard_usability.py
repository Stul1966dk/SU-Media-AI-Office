"""Sprint 24 dashboard usability regression tests."""

import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class DashboardUsabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("SU_MEDIA_DATABASE_PATH")
        os.environ["SU_MEDIA_DATABASE_PATH"] = str(
            Path(self.temp.name) / "dashboard.db"
        )

    def tearDown(self) -> None:
        if self.previous is None:
            os.environ.pop("SU_MEDIA_DATABASE_PATH", None)
        else:
            os.environ["SU_MEDIA_DATABASE_PATH"] = self.previous
        self.temp.cleanup()

    def test_application_opens_on_today(self) -> None:
        app = AppTest.from_file(
            str(ROOT / "dashboard" / "app.py"), default_timeout=20
        ).run()
        self.assertFalse(app.exception)
        self.assertTrue(any(
            "Godmorgen – her er dagens vigtigste opgave" in item.value
            for item in app.markdown
        ))

    def test_portfolio_remains_available_as_secondary_page(self) -> None:
        app = AppTest.from_file(
            str(ROOT / "dashboard" / "pages" / "19_Portefolje.py"),
            default_timeout=20,
        ).run()
        self.assertFalse(app.exception)
        self.assertEqual(["Portefølje"], [item.value for item in app.title])

    def test_getting_started_has_fixed_order_and_help(self) -> None:
        app = AppTest.from_file(
            str(ROOT / "dashboard" / "pages" / "0_Kom_godt_i_gang.py")
        ).run()
        self.assertFalse(app.exception)
        headings = [item.value for item in app.subheader]
        self.assertEqual(
            ["1. Vælg websites", "2. Forbind data",
             "3. Arbejd fra I dag", "4. Følg resultater"],
            headings,
        )
        self.assertTrue(any(
            item.label == "Hjælp til denne side" for item in app.expander
        ))

    def test_ai_analyst_has_selection_action_and_explained_empty_state(self) -> None:
        app = AppTest.from_file(
            str(ROOT / "dashboard" / "pages" / "6_AI_Analyst.py")
        ).run()
        self.assertFalse(app.exception)
        self.assertTrue(any(item.label == "Kør analyse" for item in app.button))
        self.assertTrue(app.info)

    def test_every_page_uses_help_panel_or_shared_placeholder(self) -> None:
        pages = (ROOT / "dashboard" / "pages").glob("*.py")
        for path in pages:
            source = path.read_text(encoding="utf-8")
            if path.name == "15_Dagens_Arbejde.py":
                # The daily surface intentionally has no expandable help:
                # the complete task and next action must be visible at once.
                continue
            self.assertTrue(
                "render_help_panel" in source or
                "dashboard.components.placeholder" in source or
                "render_portfolio" in source,
                path.name,
            )

    def test_discovery_contains_plain_language_signal_explanations(self) -> None:
        source = (
            ROOT / "dashboard" / "pages" / "4_Website_Discovery.py"
        ).read_text(encoding="utf-8")
        self.assertIn("WordPress blev fundet", source)
        self.assertIn("Vis teknisk signal", source)


if __name__ == "__main__":
    unittest.main()
