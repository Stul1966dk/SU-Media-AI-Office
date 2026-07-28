"""Sprint 43.3 tests for explainable cross-source recommendations."""

import unittest

from core.traffic_recommendations import build_traffic_recommendations
from dashboard.components.data import build_dashboard_priority_tasks


def search(status="ready", cause="CTR-fald"):
    return {
        "website_id": "site.dk",
        "status": status,
        "previous_clicks": 100,
        "current_clicks": 70 if status == "ready" else 110,
        "loss_pages": [{
            "page_url": "https://site.dk/side/",
            "cause": cause,
            "previous_ctr": 0.05,
            "current_ctr": 0.03,
            "previous_position": 5,
            "current_position": 5.2,
        }] if status == "ready" else [],
    }


def plausible(status="significant_decline", change=-25):
    return {
        "website_id": "site.dk",
        "status": status,
        "previous_visitors": 1000,
        "current_visitors": 750,
        "visitor_change_percent": change,
    }


class TrafficRecommendationTests(unittest.TestCase):
    def test_both_declines_create_specific_high_confidence_action(self):
        result = build_traffic_recommendations(
            [search()], [plausible()]
        )[0]
        self.assertEqual("combined_traffic_decline", result["task_type"])
        self.assertEqual("høj", result["confidence"])
        self.assertEqual("https://site.dk/side/", result["target_url"])
        self.assertIn("title/meta-test", result["description"])
        self.assertEqual(3, len(result["action_steps"]))
        self.assertIn("28 hele dage", result["measurement_method"])
        self.assertEqual(-30.0, result["click_change"])

    def test_search_only_decline_is_channel_scoped(self):
        result = build_traffic_recommendations(
            [search(cause="Placeringsfald")],
            [plausible(status="growth", change=12)],
        )[0]
        self.assertEqual("search_only_decline", result["task_type"])
        self.assertEqual("middel", result["confidence"])
        self.assertIn("organiske kanal", result["explanation"])
        self.assertIn("Styrk siden", result["description"])
        self.assertIn("interne links", result["recommended_action"])

    def test_plausible_only_decline_points_away_from_search(self):
        result = build_traffic_recommendations(
            [search(status="no_decline")], [plausible()]
        )[0]
        self.assertEqual("plausible_only_decline", result["task_type"])
        self.assertIn("kanal i Plausible", result["description"])
        self.assertIn("øvrige kanaler", result["recommended_action"])

    def test_insufficient_source_creates_no_recommendation(self):
        self.assertEqual(build_traffic_recommendations(
            [search(status="insufficient_data")], [plausible()]
        ), [])

    def test_diagnosed_task_replaces_generic_seo_and_plausible_tasks(self):
        tasks = build_dashboard_priority_tasks(
            system_status={},
            seo_sites=[{
                "website": "site.dk", "trend": "declining",
                "click_change": -30,
            }],
            project_tasks=[],
            experiments=[],
            coverage=[],
            plausible_rows=[],
            search_diagnoses=[search()],
            plausible_diagnoses=[plausible()],
            limit=None,
        )
        site_tasks = [item for item in tasks if item["website"] == "site.dk"]
        self.assertEqual(1, len(site_tasks))
        self.assertEqual(
            "combined_traffic_decline", site_tasks[0]["task_type"]
        )
        self.assertEqual("pages/9_SEO.py", site_tasks[0]["target"])
        self.assertEqual("Kritisk", site_tasks[0]["priority"])


if __name__ == "__main__":
    unittest.main()
