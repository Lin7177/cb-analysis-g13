"""Regression checks against the accepted V6 frozen presentation and market data."""
import json
import sys
import unittest
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from bquant.weights.compose import DIMS, compose, two_step_decision
from bquant.weights.estimate import dimension_weights
from b4_reconcile_v6 import original_v6_matrix


class V6WeightsTests(unittest.TestCase):
    def test_weights_reproduce_frozen_pre_restore_reference(self):
        reference = json.loads((ROOT / 'work/presentation-v4/presentation_content_v4.json').read_text(encoding='utf-8'))['meta']['weights']
        out = ROOT / 'results/weights'
        fm = pd.read_csv(out / 'fm_slopes.csv', index_col=0)
        ic = pd.read_csv(out / 'rank_ic.csv', index_col=0)
        weights = dimension_weights(fm, ic)['dimension']
        self.assertEqual(set(weights), set(DIMS))
        self.assertAlmostEqual(sum(weights.values()), 1)
        for dim in DIMS:
            self.assertAlmostEqual(weights[dim], reference[dim], places=12)

    def test_all_v6_dimension_cells_and_final_decision_match(self):
        frame = compose()
        _, matrix, _ = original_v6_matrix()
        self.assertEqual(len(frame), 18)
        for _, row in frame.iterrows():
            old = matrix[row.bond_name.replace('转债', '')]
            self.assertEqual([f'{row[d]:.1f}' for d in DIMS], old[1:7])
        gaps = pd.read_csv(ROOT / 'work/B_methods/B2/results.csv').set_index('bond_key').tree_gap_pct.to_dict()
        decision = two_step_decision(frame, gaps)
        self.assertEqual(decision['picks'], ['SZ:123183', 'SH:113659', 'SH:111002'])
        self.assertEqual(frame.set_index('bond_key').loc['SH:113633', 'redlined'], True)

    def test_stale_or_invalid_weight_schema_cannot_silently_score(self):
        for weights in [{}, dict.fromkeys(['S1','S2','S3','S4','S5','S6'], 1/6),
                        dict.fromkeys(DIMS, .1),
                        dict(D1=-.1, D2=.3, D3=.2, D4=.2, D5=.2, D6=.2)]:
            with self.assertRaises(ValueError):
                compose(weights)


if __name__ == '__main__':
    unittest.main()
