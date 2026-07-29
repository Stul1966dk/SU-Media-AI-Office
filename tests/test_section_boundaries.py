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
        self.assertIn("background: var(--app-surface)", styles)
        self.assertIn("border: 1px solid var(--app-border)", styles)
        self.assertIn("margin-block: 1.15rem", styles)
        self.assertIn("box-shadow:", styles)

    def test_daily_work_keeps_extra_space_between_main_cards(self) -> None:
        source = DAILY_WORK.read_text(encoding="utf-8")

        self.assertIn("margin-block: 1.25rem", source)
        self.assertNotIn(
            "padding: .7rem; margin: 1.3rem 0;", source
        )

    def test_accepted_task_keeps_target_page_card(self) -> None:
        source = DAILY_WORK.read_text(encoding="utf-8")
        implementation = source.split(
            "def _render_implementation(", 1
        )[1].split("def _render_page_card(", 1)[0]

        self.assertIn("_render_page_card(item, change)", implementation)
        self.assertIn("_render_change_card(item, change)", implementation)
        self.assertLess(
            implementation.index("_render_page_card(item, change)"),
            implementation.index("_render_change_card(item, change)"),
        )


if __name__ == "__main__":
    unittest.main()
