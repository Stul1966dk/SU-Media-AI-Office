"""Sprint 44.1 regression tests for the simplified daily workflow."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SimpleDailyFlowTests(unittest.TestCase):
    def test_daily_page_exposes_next_step_before_optional_details(self):
        source = (
            ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
        ).read_text(encoding="utf-8")

        self.assertIn("Her er de vigtigste opgaver", source)
        self.assertIn("_render_guided_progress", source)
        self.assertIn("Se AI-forslaget", source)
        self.assertIn(
            'st.expander("Se datagrundlag")', source
        )
        self.assertIn(
            'st.expander("Hvorfor er denne opgave valgt?")', source
        )
        self.assertIn("help=(", source)

    def test_portfolio_is_not_the_application_entrypoint(self):
        source = (ROOT / "dashboard" / "app.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("15_Dagens_Arbejde.py", source)
        self.assertIn("def render_portfolio()", source)


if __name__ == "__main__":
    unittest.main()
