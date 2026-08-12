"""Revenue-weighted prioritisation (Fase 2).

Per-page commission from Fase 1's uid attribution weighs into the daily-work
priority: proven earners rank higher, and a monetised page with real traffic but
no recorded commission is surfaced as a bounded monetisation opportunity.
"""

import tempfile
import unittest
from pathlib import Path

from core.database import Database
from core.decision_engine import DecisionEngine
from core.revenue_attribution import (
    page_key_for_url,
    revenue_by_page,
    revenue_by_product,
)
from core.seo_experiment_engine import SEOExperimentEngine
from core.website_registry import WebsiteRegistry


class RevenueAttributionTests(unittest.TestCase):
    def test_page_key_for_url_matches_a_sale_key(self) -> None:
        # A candidate URL must resolve to the exact key a sale attributes to.
        sale = {"valuta": "DKK", "provision": "100",
                "url": "https://romaskinen.dk/", "uid": "/guide/", "uid2": ""}
        by_page = revenue_by_page([sale])
        self.assertIn(page_key_for_url("https://romaskinen.dk/guide/"), by_page)
        # Query and fragment on the candidate URL are ignored, like the sale uid.
        self.assertEqual(
            page_key_for_url("https://romaskinen.dk/guide/?x=1#top"),
            page_key_for_url("https://romaskinen.dk/guide/"),
        )

    def test_revenue_by_page_sums_dkk_and_drops_junk(self) -> None:
        records = [
            {"valuta": "DKK", "provision": "100",
             "url": "https://a.dk/", "uid": "/side/", "uid2": ""},
            {"valuta": "DKK", "provision": "50",
             "url": "https://a.dk/", "uid": "/side/", "uid2": ""},
            {"valuta": "EUR", "provision": "999",
             "url": "https://a.dk/", "uid": "/side/", "uid2": ""},
            {"valuta": "DKK", "provision": "77",
             "url": "https://a.dk/", "uid": "[UID]", "uid2": ""},
        ]
        by_page = revenue_by_page(records)
        self.assertEqual({"a.dk/side/": 150.0}, by_page)

    def test_revenue_by_product_drops_feed_blobs(self) -> None:
        records = [
            {"valuta": "DKK", "provision": "200",
             "url": "https://a.dk/", "uid": "/", "uid2": "Flowrow-Aqua"},
            {"valuta": "DKK", "provision": "40",
             "url": "https://a.dk/", "uid": "/", "uid2": "eyJ0eXBlIjoiZmVlZCJ9"},
        ]
        self.assertEqual({"Flowrow-Aqua": 200.0}, revenue_by_product(records))


class RevenueWeightedPriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.database.initialize()
        for website, monetized in (("earner.dk", True), ("plain.dk", False)):
            self.database.upsert_website({
                "website": website, "display_name": website, "active": True,
                "monetized": monetized, "priority": "high",
                "primary_income_source": "affiliate", "niche": "test",
                "domain_age": "1", "notes": "", "status": "active",
            })
        self.registry = WebsiteRegistry(self.database)
        self.engine = DecisionEngine(
            self.database, self.registry,
            experiment_engine=SEOExperimentEngine(self.database),
        )

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def _period(
        self, website: str, path: str, start: str, end: str,
        clicks: int, impressions: int,
    ) -> None:
        url = f"https://{website}{path}"
        for dimension, page, word in (
            ("page", url, None),
            ("page_query", url, "søgeord"),
        ):
            self.database.upsert_search_console_dimension(
                dimension_type=dimension, website_id=website,
                site_url=f"https://{website}/", page_url=page, query=word,
                period_start=start, period_end=end, clicks=clicks,
                impressions=impressions,
                ctr=clicks / impressions if impressions else 0,
                average_position=7,
            )

    def _traffic(self, website: str, path: str) -> None:
        # Equal evidence on both periods with a clear click drop -> candidate.
        self._period(website, path, "2026-05-24", "2026-06-20", 400, 5000)
        self._period(website, path, "2026-06-21", "2026-07-18", 300, 5000)

    def _sale(self, website: str, uid: str, provision: str, kombiid: str) -> None:
        self.database.upsert_partner_ads_sale({
            "kombiid": kombiid, "provision": provision,
            "url": f"https://{website}/", "uid": uid, "uid2": "",
            "valuta": "DKK", "dato": "01-06-2026",
        })

    def _candidate(self, url: str) -> dict:
        ranked = self.engine.rank_candidates(self.engine.collect_candidates())
        return next(item for item in ranked if item["target_url"] == url)

    def test_recorded_commission_lifts_the_affiliate_income_factor(self) -> None:
        self._traffic("earner.dk", "/tjener/")
        self._traffic("earner.dk", "/tom/")
        self._sale("earner.dk", "/tjener/", "2000", "k-earn")

        earner = self._candidate("https://earner.dk/tjener/")
        empty = self._candidate("https://earner.dk/tom/")

        self.assertEqual(2000.0, earner["affiliate_commission"])
        self.assertEqual(0.0, empty["affiliate_commission"])
        self.assertGreater(
            earner["score_factors"]["affiliate_income"],
            empty["score_factors"]["affiliate_income"],
        )
        self.assertGreaterEqual(earner["priority_score"], empty["priority_score"])
        self.assertIn("provision", self.engine.explain_decision(earner))

    def test_traffic_without_commission_is_a_monetisation_opportunity(self) -> None:
        # earner.dk earns on another page, so a trafficked page with no sales
        # of its own is a genuine monetisation opportunity.
        self._traffic("earner.dk", "/uden-salg/")
        self._sale("earner.dk", "/andet/", "1500", "k-andet")

        candidate = self._candidate("https://earner.dk/uden-salg/")

        self.assertTrue(candidate["monetization_opportunity"])
        self.assertGreater(
            candidate["score_factors"]["monetization_opportunity"], 0
        )
        self.assertIn(
            "moneteringschance", self.engine.explain_decision(candidate)
        )

    def test_no_gap_on_a_site_that_never_earns(self) -> None:
        # A monetised site with traffic but zero commission anywhere is not an
        # opportunity — it is just non-commercial content (the helpdesken case).
        self._traffic("earner.dk", "/informationsside/")

        candidate = self._candidate("https://earner.dk/informationsside/")

        self.assertFalse(candidate["monetization_opportunity"])
        self.assertEqual(
            0, candidate["score_factors"]["monetization_opportunity"]
        )

    def test_proven_earner_has_no_monetisation_gap_flag(self) -> None:
        self._traffic("earner.dk", "/tjener/")
        self._sale("earner.dk", "/tjener/", "2000", "k-earn")

        earner = self._candidate("https://earner.dk/tjener/")

        self.assertFalse(earner["monetization_opportunity"])
        self.assertEqual(
            0, earner["score_factors"]["monetization_opportunity"]
        )

    def test_gap_boost_never_outweighs_a_proven_earner(self) -> None:
        # Equal traffic: the page with recorded commission must rank at or above
        # the monetisation-gap page — the gap lifts, it never overtakes.
        self._traffic("earner.dk", "/tjener/")
        self._traffic("earner.dk", "/uden-salg/")
        self._sale("earner.dk", "/tjener/", "2000", "k-earn")

        earner = self._candidate("https://earner.dk/tjener/")
        gap = self._candidate("https://earner.dk/uden-salg/")

        self.assertGreaterEqual(earner["priority_score"], gap["priority_score"])

    def test_non_monetised_site_gets_no_monetisation_gap(self) -> None:
        self._traffic("plain.dk", "/side/")

        candidate = self._candidate("https://plain.dk/side/")

        self.assertFalse(candidate["monetization_opportunity"])
        self.assertEqual(
            0, candidate["score_factors"]["monetization_opportunity"]
        )


if __name__ == "__main__":
    unittest.main()
