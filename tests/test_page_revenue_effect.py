"""Tests for page-level revenue effect of an SEO change."""

import unittest
from datetime import date
from decimal import Decimal

from core.page_revenue_effect import compute_page_revenue_effect


URL = "https://romaskinen.dk/side-a/"
CHANGE = date(2026, 4, 1)
DONE = date(2026, 6, 1)   # after the 28-day after-window has elapsed


def _rec(dato, provision, url=URL, uid="/side-a/", valuta="DKK"):
    return {
        "dato": dato, "provision": provision, "url": url,
        "uid": uid, "valuta": valuta,
    }


class PageRevenueEffectTests(unittest.TestCase):
    def test_splits_baseline_and_after_windows(self) -> None:
        records = [
            _rec("20-3-2026", "100"),   # baseline
            _rec("25-3-2026", "50"),    # baseline
            _rec("5-4-2026", "200"),    # after
            _rec("10-4-2026", "100"),   # after
            _rec("1-1-2026", "999"),    # far before -> ignored
        ]
        effect = compute_page_revenue_effect(
            records, target_url=URL, change_date=CHANGE, today=DONE, min_sales=2
        )
        self.assertEqual(Decimal("150"), effect.baseline_total)
        self.assertEqual(2, effect.baseline_sales)
        self.assertEqual(Decimal("300"), effect.after_total)
        self.assertEqual(2, effect.after_sales)
        self.assertEqual(Decimal("150"), effect.delta)
        self.assertAlmostEqual(100.0, effect.delta_pct)
        self.assertEqual("ok", effect.confidence)

    def test_only_target_page_counts(self) -> None:
        records = [
            _rec("5-4-2026", "200"),                       # match
            _rec("6-4-2026", "500", uid="/anden-side/"),   # other page
            _rec("7-4-2026", "500", url="https://baalfad.dk/side-a/"),  # other site
        ]
        effect = compute_page_revenue_effect(
            records, target_url=URL, change_date=CHANGE, today=DONE
        )
        self.assertEqual(Decimal("200"), effect.after_total)
        self.assertEqual(1, effect.after_sales)

    def test_path_normalization_matches(self) -> None:
        # No trailing slash, different case -> still the same page.
        records = [_rec("5-4-2026", "200", uid="/Side-A")]
        effect = compute_page_revenue_effect(
            records, target_url=URL, change_date=CHANGE, today=DONE
        )
        self.assertTrue(effect.matched)
        self.assertEqual(Decimal("200"), effect.after_total)

    def test_unmatched_when_no_page_sales(self) -> None:
        records = [_rec("5-4-2026", "200", uid="/en-anden/")]
        effect = compute_page_revenue_effect(
            records, target_url=URL, change_date=CHANGE, today=DONE
        )
        self.assertFalse(effect.matched)
        self.assertEqual(Decimal("0"), effect.after_total)

    def test_pending_when_window_not_elapsed(self) -> None:
        records = [_rec("5-4-2026", "200")]
        effect = compute_page_revenue_effect(
            records, target_url=URL, change_date=CHANGE, today=date(2026, 4, 15)
        )
        self.assertFalse(effect.after_complete)
        self.assertEqual("pending", effect.confidence)

    def test_confidence_insufficient_and_low(self) -> None:
        one_each = [_rec("20-3-2026", "100"), _rec("5-4-2026", "200")]
        insufficient = compute_page_revenue_effect(
            one_each, target_url=URL, change_date=CHANGE, today=DONE, min_sales=3
        )
        self.assertEqual("insufficient", insufficient.confidence)

        low = compute_page_revenue_effect(
            [
                _rec("18-3-2026", "10"), _rec("19-3-2026", "10"),
                _rec("20-3-2026", "10"), _rec("5-4-2026", "200"),
            ],
            target_url=URL, change_date=CHANGE, today=DONE, min_sales=3,
        )
        self.assertEqual("low", low.confidence)

    def test_delta_pct_none_when_no_baseline(self) -> None:
        records = [_rec("5-4-2026", "200")]
        effect = compute_page_revenue_effect(
            records, target_url=URL, change_date=CHANGE, today=DONE
        )
        self.assertEqual(Decimal("0"), effect.baseline_total)
        self.assertIsNone(effect.delta_pct)


if __name__ == "__main__":
    unittest.main()
