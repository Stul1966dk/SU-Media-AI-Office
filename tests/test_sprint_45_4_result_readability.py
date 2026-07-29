"""Regression tests for calmer metrics and visible measured changes."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLES = ROOT / "dashboard" / "assets" / "styles.css"
RESULTS = ROOT / "dashboard" / "pages" / "13_Eksperimenter.py"


class ResultReadabilityTests(unittest.TestCase):
    def test_global_metric_values_use_compact_typography(self) -> None:
        css = STYLES.read_text(encoding="utf-8")

        self.assertIn('[data-testid="stMetricValue"]', css)
        self.assertIn("font-size: 1.35rem", css)
        self.assertIn('[data-testid="stMetricLabel"]', css)

    def test_active_result_shows_change_before_progress(self) -> None:
        source = RESULTS.read_text(encoding="utf-8")
        card = source.split("def _active_card(", 1)[1].split(
            "def _render_visible_change(", 1
        )[0]

        change_at = card.index(
            "_render_visible_change(item, implemented_change)"
        )
        progress_at = card.index('st.write("**Fremdrift i måleperioden**")')
        self.assertLess(change_at, progress_at)
        self.assertNotIn('st.expander("Se ændring")', card)

    def test_title_and_meta_are_visible_as_separate_copy_fields(self) -> None:
        source = RESULTS.read_text(encoding="utf-8")
        renderer = source.split("def _render_visible_change(", 1)[1].split(
            "def _development(", 1
        )[0]

        self.assertIn('st.write("**Ny title**")', renderer)
        self.assertIn('approved_change.get("approved_title")', renderer)
        self.assertIn('st.write("**Ny metabeskrivelse**")', renderer)
        self.assertIn('approved_change.get("approved_meta")', renderer)
        self.assertGreaterEqual(renderer.count("st.code("), 2)


if __name__ == "__main__":
    unittest.main()
