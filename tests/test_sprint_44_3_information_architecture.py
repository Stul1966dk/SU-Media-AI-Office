"""Regression tests for Sprint 44.3's simplified information architecture."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class InformationArchitectureTests(unittest.TestCase):
    def test_seo_is_documentation_without_parallel_task_actions(self):
        seo = source("dashboard/pages/9_SEO.py")

        self.assertIn("Denne side forklarer datagrundlaget", seo)
        self.assertIn("Fortsæt opgaven på I dag", seo)
        self.assertNotIn("Gem opgavekladde", seo)
        self.assertNotIn("Markér implementeret og start 28-dages måling", seo)

    def test_website_profile_hides_secondary_details_and_points_to_today(self):
        profile = source("dashboard/pages/1_Website_Profile.py")

        self.assertIn('st.expander("Se tekniske og historiske detaljer")', profile)
        self.assertIn('label="Gå til I dag"', profile)
        self.assertIn('help="Skifter alle oplysninger', profile)

    def test_legacy_work_registers_point_to_today(self):
        for filename in (
            "dashboard/pages/2_Projekter.py",
            "dashboard/pages/3_Executive_Briefing.py",
            "dashboard/pages/8_Opgaver.py",
        ):
            page = source(filename)
            self.assertIn("render_next_step(", page, filename)
            self.assertIn('path="app.py"', page, filename)

    def test_results_owns_measurements(self):
        results = source("dashboard/pages/13_Eksperimenter.py")

        self.assertIn('st.title("Resultater")', results)
        self.assertIn("Følg aktive målinger", results)


if __name__ == "__main__":
    unittest.main()
