"""Regression tests for copyable snippets and focused daily work."""

import unittest
from pathlib import Path

from core.task_deliverables import (
    format_title_meta_option,
    prefer_pipe_separator,
    split_title_meta_option,
    validate_task_deliverable,
)


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"


class DailyWorkUsabilityTests(unittest.TestCase):
    def test_existing_one_line_snippet_is_split_and_uses_pipe(self) -> None:
        title, meta = split_title_meta_option(
            "Title: Del kalender på iPhone: Sådan laver du en fælles "
            "kalender Meta: Lær at dele kalender på iPhone."
        )

        self.assertEqual(
            "Del kalender på iPhone | Sådan laver du en fælles kalender",
            title,
        )
        self.assertEqual("Lær at dele kalender på iPhone.", meta)

    def test_title_meta_formatter_preserves_separate_fields(self) -> None:
        value = format_title_meta_option(
            "Del kalender på iPhone: Fælles kalender",
            "Del kalenderen med familien.",
        )

        self.assertEqual(
            "Title: Del kalender på iPhone | Fælles kalender\n"
            "Meta: Del kalenderen med familien.",
            value,
        )

    def test_ai_title_meta_requires_both_fields(self) -> None:
        payload = """
        {
          "deliverable_type": "title_meta",
          "summary": "Forslag",
          "recommended_option": "Kun en løs tekst",
          "alternatives": ["A", "B"],
          "rationale": "Data",
          "implementation_steps": ["Gør det"],
          "validation_checks": ["Kontrollér"]
        }
        """

        with self.assertRaises(ValueError):
            validate_task_deliverable(payload)

    def test_today_uses_copy_fields_without_status_block(self) -> None:
        source = PAGE.read_text(encoding="utf-8")

        self.assertIn("split_title_meta_option(", source)
        self.assertIn(
            'prefer_pipe_separator(change["approved_title"])',
            source,
        )
        self.assertIn(
            'title=prefer_pipe_separator(change["approved_title"])',
            source,
        )
        self.assertIn("Brug kopiér-knappen i title-feltet.", source)
        self.assertIn("Brug kopiér-knappen i meta-feltet.", source)
        self.assertNotIn('st.subheader("Igangværende SEO-arbejde")', source)
        self.assertNotIn(
            'st.expander("Se status og øvrigt igangværende arbejde")',
            source,
        )

    def test_finished_action_navigates_to_top_level_page(self) -> None:
        source = PAGE.read_text(encoding="utf-8")
        finish = source.split("def _finish_daily_action(", 1)[1].split(
            "def _render_draft_decision(", 1
        )[0]

        self.assertIn('st.switch_page("app.py")', finish)
        self.assertNotIn("st.rerun()", finish)

    def test_separator_helper_changes_only_the_first_title_colon(self) -> None:
        self.assertEqual(
            "Guide | Sådan gør du: trin for trin",
            prefer_pipe_separator("Guide: Sådan gør du: trin for trin"),
        )


if __name__ == "__main__":
    unittest.main()
