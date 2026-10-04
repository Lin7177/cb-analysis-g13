"""Run market-wide weight estimation and write results/weights/ (json + diagnostics).

Usage:
    python scripts/run_weight_estimation.py

Pipeline: month-end sessions from the price panel -> as-of features (excluding our 18
research bonds) -> forward ~120-session return labels -> Fama-MacBeth slopes with
Newey-West t + RankIC/ICIR -> dimension weights -> weights.json with full diagnostics.
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'src'))

from bquant.weights.features import FEATURES, build_monthly_features, constrained_return, forward_return, _wide  # noqa: E402
from bquant.weights.estimate import (dimension_weights, fama_macbeth, month_end_sessions,  # noqa: E402
                                     newey_west_t, rank_ic_series)

def our_codes() -> set[str]:
    """Our 18 research bonds, mapped to panel codes, from the shared base file."""
    base = pd.read_csv(HERE.parent / 'data' / 'curated' / 'base.csv')
    mapping = {'SH': '.SH', 'SZ': '.SZ'}
    codes = set()
    for key in base.bond_key:
        market, code = str(key).split(':')
        codes.add(f'{code}{mapping[market]}')
    if len(codes) != 18:
        raise AssertionError(f'expected 18 bond codes, got {len(codes)}')
    return codes

def main() -> None:
    price = _wide('price')
    scale = _wide('remaining_scale')
    ratings_path = HERE.parent / 'data' / 'curated' / 'market' / 'cb_ratings.csv'
    ratings = pd.read_csv(ratings_path, dtype={'bond_code': str})
    ratings['bond_code'] = ratings.bond_code + ratings.bond_code.map(
        lambda c: '.SH' if c.startswith('11') else '.SZ')
    excluded = our_codes()
    sessions = month_end_sessions(price.index, '2022-06-01', '2026-01-31')
    features = build_monthly_features(sessions, ratings)
    labels, labels_c, universe = {}, {}, {}
    for t in sessions:
        fwd = forward_return(price, t, horizon=120)
        fwd_c = constrained_return(price, t, horizon=120, stop=-0.15)
        if fwd.dropna().empty or (price.index.get_loc(t) + 120 > len(price.index) - 1):
            continue
        p_row = price.loc[t]
        sc_row = scale.loc[t] if t in scale.index else None
        keep = []
        for name, value in fwd.items():
            if pd.isna(value) or name in excluded:
                continue
            if not (85 <= p_row.get(name, np.nan) <= 260):
                continue
            if sc_row is not None and not (sc_row.get(name, np.nan) >= 2.0):
                continue
            keep.append(name)
        if len(keep) < 30:
            continue
        labels[t] = fwd[keep]
        labels_c[t] = fwd_c[keep]
        universe[t] = keep
    fm = fama_macbeth(features, labels_c, universe)
    ics = rank_ic_series(features, labels_c, universe)
    fm_raw = fama_macbeth(features, labels, universe)
    ics_raw = rank_ic_series(features, labels, universe)
    fm_t = {f: newey_west_t(fm[f]) for f in FEATURES}
    ic_ir = (ics.mean() / ics.std()).replace([np.inf, -np.inf], np.nan)
    weights = dimension_weights(fm, ics)
    weights_raw = dimension_weights(fm_raw, ics_raw)
    out_dir = HERE.parent / 'results' / 'weights'
    out_dir.mkdir(parents=True, exist_ok=True)
    fm.to_csv(out_dir / 'fm_slopes.csv')
    ics.to_csv(out_dir / 'rank_ic.csv')
    inputs = sorted((HERE.parent / 'data' / 'curated' / 'market').glob('*'))
    payload = {
        'method': 'Fama-MacBeth (Newey-West t) + RankIC/ICIR, monthly cross-sections, label = forward ~120-session return under a -15% drawdown-stop policy (mandate: no leverage, drawdown-averse); raw-return label kept as comparison',
        'exclusions': {'our_bonds': sorted(excluded), 'price_range': [85, 260], 'min_remaining_scale_yi': 2.0},
        'coverage': {'months': len(labels), 'avg_bonds_per_month': float(np.mean([len(v) for v in universe.values()])),
                     'first_month': str(min(labels)), 'last_month': str(max(labels))},
        'fm_slopes_mean': fm.mean().round(5).to_dict(),
        'fm_newey_west_t': {k: round(v, 3) for k, v in fm_t.items()},
        'rank_ic_mean': ics.mean().round(5).to_dict(),
        'rank_ic_ir': ic_ir.round(3).to_dict(),
        'weights': weights,
        'comparison_raw_return_label': {'dimension': weights_raw['dimension'],
                                        'fm_slopes_mean': fm_raw.mean().round(5).to_dict()},
        'input_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
    }
    (out_dir / 'weights.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: payload[k] for k in ['coverage', 'fm_newey_west_t', 'rank_ic_ir', 'weights']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
