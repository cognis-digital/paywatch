"""Smoke tests for PAYWATCH. Standard library only, no network."""

import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paywatch import TOOL_NAME, TOOL_VERSION
from paywatch.core import (
    normalize_merchant,
    load_transactions,
    detect_subscriptions,
    summarize,
)
from paywatch.cli import main

DEMO_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "demos", "01-basic", "transactions.csv",
)


class TestNormalize(unittest.TestCase):
    def test_strips_noise_into_stable_key(self):
        a = normalize_merchant("NETFLIX.COM 866-579-7172 CA")
        b = normalize_merchant("NETFLIX.COM 866-579-7172 CA")
        self.assertEqual(a, b)
        self.assertIn("NETFLIX", a)

    def test_store_numbers_removed(self):
        k = normalize_merchant("PLANET FITNESS CLUB 4471")
        self.assertNotIn("4471", k)
        self.assertIn("PLANET", k)


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.txns = load_transactions(DEMO_CSV)
        # fixed "today" so forgotten-detection is deterministic
        self.today = dt.date(2026, 5, 1)
        self.subs = detect_subscriptions(self.txns, today=self.today)

    def test_loads_only_charges(self):
        self.assertTrue(self.txns)
        self.assertTrue(all(t.amount > 0 for t in self.txns))

    def test_detects_known_subscriptions(self):
        merchants = " ".join(s.merchant for s in self.subs)
        for brand in ("NETFLIX", "SPOTIFY", "ADOBE", "NYTIMES"):
            self.assertIn(brand, merchants, f"missing {brand}")

    def test_ignores_oneoff_purchases(self):
        merchants = " ".join(s.merchant for s in self.subs)
        self.assertNotIn("ATM", merchants)
        self.assertNotIn("SHELL", merchants)

    def test_price_increase_flagged_for_netflix(self):
        nfx = [s for s in self.subs if "NETFLIX" in s.merchant]
        self.assertTrue(nfx)
        self.assertTrue(nfx[0].price_increased)

    def test_planet_fitness_flagged_forgotten(self):
        pf = [s for s in self.subs if "PLANET" in s.merchant]
        self.assertTrue(pf)
        # last charge was 2026-02-07; today is 2026-05-01 -> forgotten
        self.assertTrue(pf[0].likely_forgotten)

    def test_next_charge_is_in_future_of_last(self):
        for s in self.subs:
            self.assertGreater(s.next_charge_estimate, s.last_charge)

    def test_summary_totals_positive(self):
        summary = summarize(self.subs)
        self.assertGreater(summary["total_annualized_cost"], 0)
        self.assertEqual(summary["subscription_count"], len(self.subs))


class TestCLI(unittest.TestCase):
    def test_version(self):
        with self.assertRaises(SystemExit) as cm:
            main(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_json_output_parses(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["scan", DEMO_CSV, "--format", "json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["tool"], TOOL_NAME)
        self.assertEqual(payload["version"], TOOL_VERSION)
        self.assertIn("subscriptions", payload)
        self.assertTrue(payload["subscriptions"])

    def test_table_output_runs(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["scan", DEMO_CSV])
        self.assertEqual(rc, 0)
        self.assertIn("PAYWATCH", buf.getvalue())

    def test_missing_file_nonzero_exit(self):
        rc = main(["scan", os.path.join(tempfile.gettempdir(), "nope_xyz.csv")])
        self.assertNotEqual(rc, 0)

    def test_forgotten_only_filter(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["scan", DEMO_CSV, "--format", "json", "--forgotten-only"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(all(s["likely_forgotten"] for s in payload["subscriptions"]))


if __name__ == "__main__":
    unittest.main()
