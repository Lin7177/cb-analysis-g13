"""Recompute V6 D1-D6 weights, scores, decisions, and reconciliation evidence.

B4 模块入口：与主PPT p32 合成矩阵对账（权重再生成部分实为 B0 引擎的复用）。
Does not edit presentations. Original V6 matrix values remain in the reconciliation
so corrections can be reviewed before a later presentation edit.

Historical freeze (2026-10-04): paths referencing work/ below follow the legacy
repo layout and will be repaired in the style-refactor round; the B0 entry is
scripts/b0_run_weight_estimation.py.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bquant.weights.compose import DIMS, compose, two_step_decision


def original_v6_matrix():
    decks = [p for p in (ROOT / 'work/v6').glob('*.pptx') if '备份' not in p.name]
    if len(decks) != 1:
        raise ValueError('Expected one V6 primary PPTX')
    deck = decks[0]
    with zipfile.ZipFile(deck) as archive:
        raw = archive.read('ppt/slides/slide31.xml').decode('utf-8')
    # The supplied deck contains an invalid control character in another slide.
    raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
    ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    xml = ET.fromstring(raw)
    rows = [[ ''.join(cell.itertext()).strip() for cell in row.findall('a:tc', ns)]
            for row in xml.findall('.//a:tr', ns)]
    if len(rows) != 20 or rows[0][1:7] != DIMS:
        raise ValueError('Original V6 scoring table changed; inspect before reconciling')
    return deck, {r[0]: r for r in rows[1:19]}, rows[-1]


def main():
    spec = importlib.util.spec_from_file_location('weight_runner', ROOT / 'b-quant/scripts/run_weight_estimation.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    with contextlib.redirect_stdout(io.StringIO()):
        runner.main()
    out = ROOT / 'b-quant/results/weights'
    wpath = out / 'weights.json'
    payload = json.loads(wpath.read_text(encoding='utf-8'))
    weights = payload['weights']['dimension']
    frame = compose(weights)
    gaps = pd.read_csv(ROOT / 'work/B_methods/B2/results.csv').set_index('bond_key').tree_gap_pct.to_dict()
    decision = two_step_decision(frame, gaps)
    deck, reference, weight_row = original_v6_matrix()
    display_weights = [f'{weights[d]:.0%}' for d in DIMS]
    if display_weights != weight_row[1:7]:
        raise AssertionError('Recomputed weights differ from V6 display')
    comparisons = []
    for _, row in frame.iterrows():
        old = reference[row.bond_name.replace('转债', '')]
        displayed = [f'{row[d]:.1f}' for d in DIMS]
        if displayed != old[1:7]:
            raise AssertionError(f'Dimension scores differ from V6: {row.bond_name}')
        comparisons.append(dict(bond_key=row.bond_key, bond_name=row.bond_name,
                                original_composite=float(old[7]), corrected_composite=float(row.composite),
                                original_open_rank=old[8],
                                corrected_open_rank=None if pd.isna(row.rank_open) else int(row.rank_open)))
    if not decision['PASS']:
        raise AssertionError('Restoration changes V6 final decision; seek confirmation')
    frame.to_csv(out / 'composite_scores.csv', index=False)
    eq_frame = compose(dict.fromkeys(DIMS, 1 / 6))
    eq_decision = two_step_decision(eq_frame, gaps)
    threshold_checks = {}
    for threshold in [-1, 0, 1]:
        shifted = {key: value - threshold for key, value in gaps.items()}
        threshold_checks[str(threshold)] = two_step_decision(frame, shifted)
    payload['specification'] = 'V6 D1-D6, residual diagnostic only, displayed weights reconciled with scores'
    payload['decision'] = dict(rule='V6 red lines outside score; compensation gate then weighted fill', **decision)
    wpath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    fm = pd.read_csv(out / 'fm_slopes.csv', index_col=0, parse_dates=True)
    yearly = fm.groupby(fm.index.year).mean()
    yearly.to_csv(out / 'annual_fm_slopes.csv')
    feature_table = pd.DataFrame({'fm_mean': payload['fm_slopes_mean'],
                                  'newey_west_t': payload['fm_newey_west_t'],
                                  'rank_ic_ir': payload['rank_ic_ir'],
                                  'fm_weight': payload['weights']['feature_fm'],
                                  'ic_weight': payload['weights']['feature_ic'],
                                  'combined_weight': payload['weights']['feature_final']})
    from bquant.weights.estimate import FEATURE_TO_DIM
    feature_table['dimension'] = feature_table.index.map(FEATURE_TO_DIM)
    feature_table.to_csv(out / 'feature_weight_audit.csv', index_label='feature')
    report = dict(source_deck=str(deck.relative_to(ROOT)),
                  source_deck_sha256=hashlib.sha256(deck.read_bytes()).hexdigest(),
                  original_display_weights=display_weights, dimensions_matched=108,
                  action='Use displayed V6 weights, correct original matrix composite/rank in later PPT edit',
                  comparisons=comparisons, final_decision=decision,
                  sensitivity=dict(equal_weight=eq_decision, gate_threshold_pct=threshold_checks,
                                   raw_return_weights=payload['comparison_raw_return_label']['dimension']),
                  validation_scope='Reproduction and sensitivity only; no temporal OOS weight validation',
                  limitations=['D4 beta*corr estimation proxy differs from beta*R2 scoring',
                               'D6 historical loss frequency proxy differs from model forecast distribution',
                               'Absolute FM slope weight does not establish a favorable scoring direction',
                               'Current rating snapshot is reused historically',
                               '-15% drawdown breach is encoded as -15% label, not executable stop return'])
    (out / 'v6_reconciliation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(display_weights=display_weights, dimensions_matched=108,
                          decision=decision, output=str(out.relative_to(ROOT))), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
