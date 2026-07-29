"""Regression tests for clear visual separation between app sections."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLES = ROOT / "dashboard" / "assets" / "styles.css"
DAILY_WORK = ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"


class SectionBoundaryTests(unittest.TestCase):
    def test_bordered_sections_have_distinct_surface_and_spacing(self) -> None:
        styles = STYLES.read_text(encoding="utf-8")

        self.assertIn(
            '[data-testid="stVerticalBlockBorderWrapper"] {', styles
        )
        self.assertIn("background: rgba(18, 24, 33, 0.58)", styles)
        self.assertIn("border-color: #34445a", styles)
        self.assertIn("margin-block: 1.15rem", styles)
        self.assertIn("box-shadow:", styles)

    def test_daily_work_keeps_extra_space_between_main_cards(self) -> None:
        source = DAILY_WORK.read_text(encoding="utf-8")

        self.assertIn("margin-block: 1.25rem", source)
        self.assertNotIn(
            "padding: .7rem; margin: 1.3rem 0;", source
        )


if __name__ == "__main__":
    unittest.main()
