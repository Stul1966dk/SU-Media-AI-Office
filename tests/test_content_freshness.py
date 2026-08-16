import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from core.content_freshness import (
    audit_content,
    build_freshness_recommendations,
)
from core.content_freshness_review import ContentFreshnessReviewService
from core.task_deliverables import _prompt
from core.priority_scoring import stable_priority_key


ROOT = Path(__file__).resolve().parents[1]


def content(**overrides):
    value = {
        "website_id": "site.dk",
        "content_type": "post",
        "status": "publish",
        "title": "Guide til en app",
        "url": "https://site.dk/guide/",
        "source_updated_at": "2025-01-01T12:00:00+01:00",
        "published_at": "2024-01-01T12:00:00+01:00",
        "excerpt": "",
        "content_text": (
            "Denne guide forklarer trin for trin, hvordan du bruger appen. "
            "Følg vejledningen og kontrollér indstillingerne på din telefon. "
            "Du kan tilpasse funktionen efter dine egne behov."
        ),
    }
    value.update(overrides)
    return value


class ContentFreshnessTests(unittest.TestCase):
    def test_recent_content_without_risk_signals_is_current(self):
        result = audit_content(
            content(), reference_date=date(2026, 7, 29)
        )

        self.assertEqual("current", result["status"])
        self.assertFalse(result["requires_external_verification"])

    def test_old_year_and_old_update_require_review(self):
        row = content(
            source_updated_at="2021-01-01T00:00:00+01:00",
            content_text=(
                "Denne vejledning er skrevet til løsningen fra 2021. "
                "Du kan følge disse trin for at konfigurere programmet. "
                "Åbn indstillingerne, vælg funktionen og gem ændringen."
            ),
        )

        result = audit_content(row, reference_date=date(2026, 7, 29))

        self.assertIn(
            result["status"], {"review", "partially_outdated"}
        )
        self.assertTrue(any(
            signal["kind"] == "year" for signal in result["signals"]
        ))

    def test_explicit_discontinued_signal_and_age_is_likely_outdated(self):
        row = content(
            source_updated_at="2019-01-01T00:00:00+01:00",
            content_text=(
                "Denne app er udgået og findes ikke længere. Guiden viser, "
                "hvordan du tidligere kunne installere og konfigurere den. "
                "Kontrollér om der findes et aktuelt alternativ."
            ),
        )

        result = audit_content(row, reference_date=date(2026, 7, 29))

        self.assertEqual("likely_outdated", result["status"])
        self.assertTrue(any(
            signal["passage"] for signal in result["signals"]
        ))

    def test_only_explainable_public_findings_become_daily_candidates(self):
        candidates = build_freshness_recommendations(
            {
                "site.dk": [
                    content(),
                    content(
                        content_id="old",
                        url="https://site.dk/gammel/",
                        source_updated_at="2018-01-01T00:00:00+01:00",
                        content_text=(
                            "Funktionen er lukket ned og understøttes ikke "
                            "længere. Denne gamle guide beskriver den tidligere "
                            "arbejdsgang og dens indstillinger."
                        ),
                    ),
                ]
            },
            reference_date=date(2026, 7, 29),
            verified_reviews={
                "https://site.dk/gammel": {
                    "status": "outdated",
                    "confidence": "high",
                    "content_hash": "",
                    "official_sources": ["https://official.example/change"],
                }
            },
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("content_freshness", candidates[0]["task_type"])
        self.assertTrue(candidates[0]["freshness_evidence"]["signals"])

    def test_unverified_signal_never_becomes_daily_work(self):
        rows = {
            "site.dk": [
                content(
                    source_updated_at="2018-01-01T00:00:00+01:00",
                    content_text=(
                        "Denne funktion er lukket ned og understøttes ikke "
                        "længere. Guiden forklarer den tidligere arbejdsgang."
                    ),
                )
            ]
        }

        self.assertEqual(
            [], build_freshness_recommendations(
                rows, reference_date=date(2026, 7, 29)
            )
        )

    def test_freshness_evidence_is_included_in_ai_prompt(self):
        prompt = _prompt({
            "website": "site.dk",
            "target_url": "https://site.dk/gammel/",
            "experiment_type": "content_update",
            "forced_content_mode": "existing_section",
            "freshness_evidence": {
                "status": "review",
                "signals": [{"label": "Ældre årstal", "passage": "Fra 2020"}],
            },
        }, [])

        self.assertIn("aktualitetskontrol", prompt)
        self.assertIn("Ældre årstal", prompt)
        self.assertIn("officielle oplysninger", prompt)

    def test_overview_and_daily_flow_are_connected(self):
        overview = (
            ROOT / "dashboard" / "pages" / "21_Indholdsaktualitet.py"
        ).read_text(encoding="utf-8")
        today = (
            ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"
        ).read_text(encoding="utf-8")

        self.assertIn("Bekræftede fund", overview)
        self.assertIn("officielle kilder", overview)
        self.assertIn("build_freshness_recommendations", today)
        self.assertIn('"content_freshness"', today)
        self.assertIn(
            "_render_priority_task(database, freshness_tasks[0])", today
        )
        self.assertIn(
            "Kontrollen køres stille i baggrunden", overview
        )

    def test_freshness_competes_with_other_work_by_score(self):
        freshness = build_freshness_recommendations(
            {
                "site.dk": [
                    content(
                        source_updated_at="2018-01-01T00:00:00+01:00",
                        content_text=(
                            "Denne funktion er lukket ned og understøttes "
                            "ikke længere. Guiden forklarer den tidligere "
                            "arbejdsgang og de gamle indstillinger."
                        ),
                    )
                ]
            },
            reference_date=date(2026, 7, 29),
            verified_reviews={
                "https://site.dk/guide": {
                    "status": "outdated",
                    "confidence": "high",
                    "content_hash": "",
                    "official_sources": ["https://official.example/change"],
                }
            },
        )[0]
        more_important_traffic_task = {
            "task_type": "combined_traffic_decline",
            "website": "site.dk",
            "description": "Større dokumenteret trafikfald",
            "task_key": "traffic",
            "total_score": freshness["total_score"] + 10,
        }

        ranked = sorted(
            [freshness, more_important_traffic_task],
            key=stable_priority_key,
        )

        self.assertEqual("traffic", ranked[0]["task_key"])
        self.assertEqual("content_freshness", ranked[1]["task_type"])

    def test_background_review_requires_high_confidence_and_official_source(
        self,
    ):
        database = Mock()
        database.get_active_website_ids.return_value = ["site.dk"]
        database.get_content_freshness_reviews.return_value = {}
        database.get_content.return_value = [
            content(
                raw_hash="hash-1",
                source_updated_at="2018-01-01T00:00:00+01:00",
                content_text=(
                    "Denne funktion er lukket ned og understøttes ikke "
                    "længere. Guiden beskriver den tidligere arbejdsgang."
                ),
            )
        ]
        ai = Mock()
        ai.generate_response.return_value = SimpleNamespace(
            text=(
                '{"is_outdated": true, "confidence": "high", '
                '"reason": "Funktionen er officielt lukket", '
                '"official_sources": ["https://official.example/status"]}'
            )
        )

        result = ContentFreshnessReviewService(database, ai).run()

        self.assertEqual(1, result["records_updated"])
        saved = database.save_content_freshness_reviews.call_args.args[0]
        review = saved["https://site.dk/guide"]
        self.assertEqual("outdated", review["status"])
        self.assertEqual("hash-1", review["content_hash"])
        ai.generate_response.assert_called_once()
        self.assertEqual(
            [{"type": "web_search"}],
            ai.generate_response.call_args.kwargs["tools"],
        )


if __name__ == "__main__":
    unittest.main()
