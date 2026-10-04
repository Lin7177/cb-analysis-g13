"""Invariants for the B4 prediction module (run with the repo venv python)."""
import sys, unittest
from datetime import date
from pathlib import Path
import numpy as np

SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))

from bquant.terms import load_base, load_curve, load_daily, load_terms, session_index, term_map
from bquant.pricing.model import tree_value
from bquant.predict.exit_surface import build_surface, coupons_between, price_on_surface
from bquant.predict.simulate import bootstrap_log_returns, gbm_log_returns, summarize
from bquant.predict.walkforward import stable_seed

def synthetic_term():
    return dict(bond_key='TEST:1', coupon_rates='[0.3,0.5,1.0,1.5,1.8,2.0]',
                issue_date='2022-06-08', maturity_date='2028-06-08', conversion_start='2022-12-08',
                conversion_price='10.0', redemption_amount_including_last_coupon='115.0')

class CouponTests(unittest.TestCase):
    def test_final_redemption_never_counted_as_coupon(self):
        term = synthetic_term()  # flows: 2023..2027 coupons, 2028 final 115
        # horizon beyond maturity: final flow must not leak in as a coupon
        self.assertAlmostEqual(coupons_between(term, date(2026, 9, 30), date(2029, 1, 1)), 1.8)  # final 2.0 lives inside the 115 redemption
        # horizon exactly at a coupon date: that date is included
        self.assertAlmostEqual(coupons_between(term, date(2026, 9, 30), date(2027, 6, 8)), 1.8)

class EngineTests(unittest.TestCase):
    def test_bootstrap_reproducible_and_range(self):
        rng = np.random.default_rng(3); ret = rng.normal(0, 0.02, size=600)
        a = bootstrap_log_returns(ret, 500, 120, block=21, seed=11)
        b = bootstrap_log_returns(ret, 500, 120, block=21, seed=11)
        c = bootstrap_log_returns(ret, 500, 120, block=21, seed=12)
        self.assertTrue(np.array_equal(a, b)); self.assertFalse(np.array_equal(a, c))
        expected_scale = 0.02 * np.sqrt(120)
        self.assertLess(abs(a.std() - expected_scale) / expected_scale, 0.35)

    def test_insufficient_history_rejected(self):
        with self.assertRaises(ValueError): bootstrap_log_returns(np.zeros(30), 10, 120, block=21)

    def test_gbm_median_shift_and_summarize_monotone(self):
        tot = gbm_log_returns(0.5, 0.5, 20000, seed=5)
        self.assertAlmostEqual(np.median(tot), -0.5 ** 2 / 2 * 0.5, delta=0.02)
        pct = tot * 100; exits = np.exp(tot) * 100
        s = summarize(pct, exits)
        self.assertTrue(s['p05'] < s['p25'] < s['p50'] < s['p75'] < s['p95'])
        for key in ['p_loss', 'p_gt5', 'p_exit_gt130']: self.assertTrue(0.0 <= s[key] <= 100.0)

class SurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.terms = term_map(load_terms())
        cls.term = cls.terms['SH:111002']  # Tezhi: liquid, mid maturity
        cls.spot, cls.sigma, cls.r = 13.49, 0.35, 0.012

    def test_interp_error_small_on_coarse_grid(self):
        surf = build_surface(self.term, self.spot, self.sigma, self.r, [.02], evaluation=date(2027, 3, 30), grid_n=21, steps=201)
        err, probes, direct, interp = __import__('bquant.predict.exit_surface', fromlist=['surface_interp_error']).surface_interp_error(
            self.term, self.spot, self.sigma, self.r, .02, date(2027, 3, 30), surf, n=6, seed=2, steps=201)
        self.assertLess(err, 1.0)  # per 100 face; full grid uses 91 points so this is the loose upper bound

    def test_surface_monotone_in_spot_and_spread(self):
        surf = build_surface(self.term, self.spot, self.sigma, self.r, [.005, .05], evaluation=date(2027, 3, 30), grid_n=15, steps=201)
        spots, v05 = surf[.005]; _, v50 = surf[.05]
        self.assertTrue(np.all(np.diff(v05) > -1e-6))
        self.assertTrue(np.all(v05 >= v50 - 1e-6))

    def test_matured_branch_is_redemption_floor(self):
        term = self.terms['SZ:123072']  # Lege matures 2026-10-20
        v = tree_value(term, 1.0, 0.3, 0.01, .02, evaluation=date(2027, 3, 30))
        self.assertAlmostEqual(v, float(term['redemption_amount_including_last_coupon']))

class SeedTests(unittest.TestCase):
    def test_stable_seed_deterministic(self):
        self.assertEqual(stable_seed('SZ:123183', 'boot'), stable_seed('SZ:123183', 'boot'))
        self.assertNotEqual(stable_seed('SZ:123183', 'boot'), stable_seed('SZ:123183', 'gbm'))

if __name__ == '__main__':
    unittest.main()
