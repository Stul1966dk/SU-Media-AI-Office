"""Regression checks for the Sprint 44.6 test-version stabilization."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StabilizationTests(unittest.TestCase):
    def test_every_visible_secondary_page_has_an_explicit_next_step(self):
        pages = (
            "1_Website_Profile.py",
            "4_Website_Discovery.py",
            "5_Content_Explorer.py",
            "6_AI_Analyst.py",
            "7_Indstillinger.py",
            "9_SEO.py",
            "11_Websites.py",
            "12_Systemstatus.py",
            "13_Eksperimenter.py",
            "14_Title_Optimering.py",
            "18_Integrationer.py",
        )
        for filename in pages:
            source = (
                ROOT / "dashboard" / "pages" / filename
            ).read_text(encoding="utf-8")
            self.assertIn("render_next_step(", source, filename)

    def test_dashboard_uses_current_streamlit_width_parameter(self):
        sources = [
            path.read_text(encoding="utf-8")
            for path in (ROOT / "dashboard").rglob("*.py")
        ]

        self.assertNotIn("use_container_width", "\n".join(sources))
        self.assertNotIn("components.html(", "\n".join(sources))

    def test_new_tasks_cannot_skip_the_concrete_deliverable(self):
        source = (
            ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
        ).read_text(encoding="utf-8")

        self.assertIn("Lav et nyt forslag", source)
        self.assertIn("Godkend forslag", source)
        self.assertIn("Godkend arbejdsudkast", source)
        self.assertNotIn('"Godkend opgave"', source)

    def test_sensitive_local_configuration_is_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        for filename in (".env", "credentials.json", "token.json"):
            self.assertIn(filename, ignore)


if __name__ == "__main__":
    unittest.main()
